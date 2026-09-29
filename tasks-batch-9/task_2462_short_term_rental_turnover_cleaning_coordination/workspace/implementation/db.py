"""In-memory data store, logical clock and common-field helpers.

Storage is process-local Python dicts only.  The store is EMPTY on every boot:
no entity is ever seeded, preloaded or hardcoded at startup.  Every row is
created by a client through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4: before any client sets the clock it reads exactly this instant, and
# it never falls back to wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.properties = {}
        self.cleaners = {}
        self.bookings = {}
        self.turnovers = {}
        self.assignments = {}
        self.checklist_tasks = {}
        self.supply_lines = {}
        self.stock_movements = {}
        self.issue_reports = {}
        self.repair_orders = {}
        self.quality_audits = {}
        self.pay_lines = {}
        self.now = CLOCK_EPOCH
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def now():
    """Current reading of the server-side logical UTC clock."""
    return db.now


def set_clock(instant):
    db.now = instant


def new_id():
    return str(uuid.uuid4())


def iso(value):
    """ISO 8601 UTC with exactly three fractional digits, or None."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def base_fields(versioned=True):
    """id / created_at (+ updated_at, version for versioned resources)."""
    stamp = now()
    record = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    return record


def touch(record, bump=True):
    """Refresh updated_at and bump version.

    PRD 2.10: "Version bumps follow the mutation, wherever it lands" -- a
    cascade that mutates a resource other than the addressed one still bumps
    that resource's own version.
    """
    record["updated_at"] = now()
    if bump:
        record["version"] = record.get("version", 1) + 1


def ordered(records):
    """Deterministic insertion order helper."""
    return sorted(records, key=lambda r: r["_seq"])
