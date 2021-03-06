import json
from urllib.parse import quote

import yaml
from cdxj_indexer.main import CDXJIndexer
from warcio.timeutils import iso_date_to_timestamp, timestamp_to_iso_date
from boilerpy3 import extractors


HTML_MIME_TYPES = ("text/html", "application/xhtml", "application/xhtml+xml")

PAGE_INDEX = "text/pages.pdx"


class WACZIndexer(CDXJIndexer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = {}
        self.lists = {}
        self.title = ''
        self.desc = ''

    def process_index_entry(self, it, record, *args):
        type_ = record.rec_headers.get('WARC-Type')
        if type_ == 'warcinfo':
            self.parse_warcinfo(record)

        elif type_ in CDXJIndexer.DEFAULT_RECORDS:
            if type_ in ('response' 'resource'):
                self.extract_text(record)

            super().process_index_entry(it, record, *args)

    def parse_warcinfo(self, record):
        """Parse WARC information.

        :param record: WARC information

        :returns: WARC information or None
        :rtype: dict or None
        """
        warcinfo = {}
        warcinfo_buff = record.raw_stream.read(record.length)
        warcinfo_buff = warcinfo_buff.decode('utf-8')
        metadata = None
        for line in warcinfo_buff.rstrip().split('\n'):
            parts = line.split(':', 1)

            if parts[0] == 'json-metadata':
                metadata = json.loads(parts[1])
            elif len(parts) == 2:
                warcinfo[parts[0]] = parts[1].strip()

        if not metadata:
            return

        if metadata['type'] == 'collection':
            self.title = metadata.get('title', '')
            self.desc = metadata.get('desc', '')

        elif metadata['type'] == 'recording':
            pages = metadata.get('pages', [])
            for page in pages:
                id_ = page['timestamp'] + '/' + page['url']
                self.pages[id_] = page


    def extract_text(self, record):
        url = record.rec_headers.get('WARC-Target-URI')
        date = record.rec_headers.get('WARC-Date')

        id_ = iso_date_to_timestamp(date) + '/' + url
        if id_ not in self.pages:
            return

        mime = self.get_record_mime_type(record)

        if mime not in HTML_MIME_TYPES:
            return

        if record.http_headers and record.http_headers.get_statuscode().startswith('3'):
            return

        extractor = extractors.ArticleExtractor()

        content = record.content_stream().read()

        try:
            content = content.decode("utf-8")

            doc = extractor.get_doc(content)

            if doc.content:
                self.pages[id_]["text"] = doc.content

            if doc.title:
                self.pages[id_]["title"] = doc.title
        except
            # skip text extraction in case of errors
            pass

    def get_record_mime_type(self, record):
        if record.http_headers:
            # if the record has HTTP headers, use the Content-Type from those (eg. 'response' record)
            content_type = record.http_headers["Content-Type"]
        else:
            # otherwise, use the Content-Type from WARC headers
            content_type = record.rec_headers["Content-Type"]

        mime = content_type or ""
        return mime.split(";")[0]

    def serialize_cdxj_pages(self, pages):
        yield '!meta 0 ' + json.dumps({'format': 'cdxj-pages-1.0', 'title': 'All Pages'})

        for line in pages.values():
            ts = timestamp_to_iso_date(line['timestamp'])
            title = quote(line.get('title') or line.get('url'), safe=':/?&=')

            data = {'url': line['url']}
            if 'text' in line:
                data['text'] = line['text']

            yield title + ' ' + ts + ' ' + json.dumps(data)

    def serialize_json_pages(self, pages):
        yield json.dumps({'format': 'json-pages-1.0', 'title': 'All Pages'}) + "\n"

        for line in pages.values():
            ts = timestamp_to_iso_date(line['timestamp'])
            title = line.get('title')

            data = {'url': line['url'], 'ts': ts}
            if title:
                data['title']= title

            if 'text' in line:
                data['text'] = line['text']

            yield json.dumps(data) + "\n"

    def generate_metadata(self, res):
        desc = res.desc or self.desc
        title = res.title or self.title
        textIndex = PAGE_INDEX if res.text else ''

        data = {}
        if title:
            data['title'] = title

        if desc:
            data['desc'] = desc

        if textIndex:
            data['textIndex'] = textIndex

        data['pages'] = [
            {'title': page['title'],
             'date': page['timestamp'],
             'url': page['url']} for page in self.pages.values()]

        return yaml.dump(data)

