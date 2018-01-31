from bs4 import BeautifulSoup
from cum import config, exceptions, output
from cum.scrapers.base import BaseChapter, BaseSeries, download_pool
from functools import partial
from mimetypes import guess_type
import concurrent.futures
import re
import requests

class MangadexSeries(BaseSeries):
    url_re = re.compile(r'https?://mangadex\.com/manga/([0-9]+)')
    # Example inputs:
    # Vol. 2 Ch. 18 - Strange-flavored Ramen
    # Ch. 7 - Read Online
    # Vol. 01 Ch. 001-013 - Read Online
    name_re = re.compile(r'Ch\. ?([A-Za-z0-9\.\-]*)(?: - (.*))')
    chapter_re = re.compile(r'/chapter/([0-9]+)')

    def __init__(self, url, **kwargs):
        super().__init__(url, **kwargs)
        self._get_page()
        self.chapters = self.get_chapters()

    def _get_page(self):
        r = requests.get(self.url)
        self.soup = BeautifulSoup(r.text, config.get().html_parser)

    def get_chapters(self):
        links = self.soup.find_all('a')
        chapters = []

        manga_name = self.name
        for a in links:
            url = a.get('href')
            url_match = re.search(self.chapter_re, url)

            # if it's a chapter link
            if url_match:
                name = a.string
                name = name.strip()
                print(name)
                print('https://mangadex.com' + url)
                name_parts = re.search(self.name_re, name)
                chapter = name_parts.group(1)
                title = name_parts.group(2)
                groups = [] # [g.string if g.get('href') else false for g in a.parent.parent.find_all('a')]
                c = MangadexChapter(name=manga_name, alias=self.alias,
                                    chapter=chapter, url='https://mangadex.com' + url,
                                    groups=groups, title=title)
                chapters.append(c)
        return chapters

    @property
    def name(self):
        title_re = re.compile(r'^(.+) \(Manga\) - MangaDex')
        title = self.soup.find('title').string.strip()
        title_result = re.search(title_re, title)
        print("manga title" + title_result.group(1))
        return title_result.group(1)


class MangadexChapter(BaseChapter):
    # img_path_re = re.compile(
    #     # Example:
    #     # /data/22a5848d68bf6d3cad936ef89d575535/x1.jpg
    #   # sometimes on some cdn
    #   # https://s2.mangadex.com/22a5848d68bf6d3cad936ef89d575535/x1.jpg
    #     r'["\'](?:/data)/([A-Za-z0-9]{32})/([a-zA-Z0-9]+)\..+["\']'
    # )
    hash_re = re.compile(r'var dataurl ?= ?\'([A-Za-z0-9]{32})\'')
    url_re = re.compile(r'/chapter/([0-9]+)')
    # Example: (mind that the trailing comma is invalid json)
    # var page_array = [
    # 'x1.jpg','x2.jpg','x3.jpg','x4.jpg','x5.jpg','x6.png',];
    pages_re = re.compile(r'var page_array ?= ?\[([^\]]+)\]', re.DOTALL)
    # 'x1.jpg'
    single_page_re = re.compile(r'\s?\'([^\']+)\',?')
    uses_pages = True

    @staticmethod
    def _reader_get(url, page_index):
        return requests.get(url)

    def available(self):
        self.r = self.reader_get(1)
        if not len(self.r.text):
            return False
        elif self.r.status_code == 404:
            return False
        else:
            return True

    def download(self):
        if getattr(self, 'r', None):
            r = self.r
        else:
            r = self.reader_get(1)
        soup = BeautifulSoup(r.text, config.get().html_parser)

        print('GONNA DOWNLOAD' + self.url)
        chapter_hash_result = re.search(self.hash_re, r.text)
        chapter_hash = chapter_hash_result.group(1)
        pages_var = re.search(self.pages_re, r.text)
        print(pages_var)
        pages = [''.join(i) for i in re.findall(self.single_page_re, pages_var.group(1))]
        print(pages)
        files = [None] * len(pages)
        futures = []
        last_image = None
        with self.progress_bar(pages) as bar:
            for i, page in enumerate(pages):
                try:
                    if guess_type(page)[0]:
                        print(chapter_hash)
                        print(page)
                        image = 'https://mangadex.com/data/' + chapter_hash + '/' + page
                    else:
                        print('guess type failed? {}'.format(guess_type(page)))
                        raise ValueError
                    r = requests.get(image, stream=True)
                    if r.status_code == 404:
                        r.close()
                        raise ValueError
                except ValueError:  # If we fail to do prediction, scrape
                    print('TOOD try to save this by scraping or something')
                    # r = self.reader_get(i + 1)
                    # soup = BeautifulSoup(r.text, config.get().html_parser)
                    # image = soup.find('img', id='comic_page').get('src')
                    # image2_match = re.search(self.next_img_path_re, r.text)
                    # if image2_match:
                    #     pages[i + 1] = image2_match.group(1)
                    # r = requests.get(image, stream=True)
                fut = download_pool.submit(self.page_download_task, i, r)
                fut.add_done_callback(partial(self.page_download_finish,
                                              bar, files))
                futures.append(fut)
                last_image = image
            concurrent.futures.wait(futures)
            self.create_zip(files)

    def from_url(url):
        chapter_hash = re.search(BatotoChapter.url_re, url).group(1)
        r = BatotoChapter._reader_get(url, 1)
        soup = BeautifulSoup(r.text, config.get().html_parser)
        try:
            series_url = soup.find('a', href=BatotoSeries.url_re)['href']
        except TypeError:
            raise exceptions.ScrapingError('Chapter has no parent series link')
        series = BatotoSeries(series_url)
        for chapter in series.chapters:
            if chapter.url.lstrip('htps') == url.lstrip('htps'):
                return chapter

    def reader_get(self, page_index):
        return self._reader_get(self.url, page_index)
