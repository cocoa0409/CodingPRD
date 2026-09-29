"""In-memory data store and the server-wide logical clock.

The store starts completely empty on every boot; nothing is seeded.  Every
entity is created by the declared API surface.
"""

import uuid
from datetime import datetime, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.stores = {}
        self.standards = {}
        self.accounts = {}
        self.bills = {}
        self.intervals = {}
        self.dr_events = {}
        self.cases = {}
        self.excursions = {}
        self.overrides = {}
        self.faults = {}
        self.work_orders = {}
        self.retrofits = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


db = DB()


def new_row(bucket, fields):
    """Create a row with the full identity quartet and register it."""
    row = dict(fields)
    row["id"] = db.new_id()
    row["created_at"] = db.clock
    row["updated_at"] = db.clock
    row["version"] = 1
    row["_seq"] = db.next_seq()
    bucket[row["id"]] = row
    return row


def new_event_row(bucket, fields):
    """Create an immutable event row: id and created_at only."""
    row = dict(fields)
    row["id"] = db.new_id()
    row["created_at"] = db.clock
    row["_seq"] = db.next_seq()
    bucket[row["id"]] = row
    return row


def rows(bucket):
    """All rows of a bucket ordered by created_at ascending, then insertion."""
    return sorted(bucket.values(), key=lambda r: (r["created_at"], r["_seq"]))
