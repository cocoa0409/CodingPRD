"""In-memory data store. Starts empty on every boot."""
import uuid
import secrets

from clock import Clock


class DB:
    def __init__(self):
        self.zones = {}
        self.hosts = {}
        self.properties = {}
        self.permits = {}
        self.lottery_rounds = {}
        self.complaints = {}
        self.tax_filings = {}
        self.listing_reports = {}
        self.platforms = {}
        self.clock = Clock()
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def new_api_key():
    return "pk_" + secrets.token_hex(16)


def new_request_id():
    return "req_" + secrets.token_hex(12)
