"""In-memory data store + logical clock.

State lives in Python dictionaries and dies with the process: no database file,
no JSON dump, no cache directory, no pickle.  Nothing is seeded at startup --
the store begins empty and every entity is built through the declared API.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.members = {}
        self.children = {}
        self.plans = {}
        self.subscriptions = {}
        self.catalog_items = {}
        self.copies = {}
        self.wishlist_entries = {}
        self.boxes = {}
        self.box_items = {}
        self.fees = {}
        self.shipments = {}
        self.ledger = {}
        # Global monotonic insertion sequence (created_at tie-break).
        self.seq = itertools.count(1)
        # Logical clock: default exactly 2026-05-01T00:00:00Z, never wall-clock.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_verbatim = "2026-05-01T00:00:00Z"


DB = Store()
LOCK = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(DB.seq)


def clock():
    return DB.clock


def clock_date():
    return DB.clock.date()


def set_clock(dt, verbatim):
    DB.clock = dt
    DB.clock_verbatim = verbatim
