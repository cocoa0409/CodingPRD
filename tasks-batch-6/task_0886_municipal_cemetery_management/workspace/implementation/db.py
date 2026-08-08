"""In-memory data store and logical clock. Fresh/empty on every process boot."""
import itertools
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.cemeteries = {}
        self.plots = {}
        self.holders = {}
        self.decedents = {}
        self.deeds = {}
        self.interments = {}
        self.disinterments = {}
        self.markers = {}
        self.invoices = {}
        self.payments = {}
        self.care_entries = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._seq)
