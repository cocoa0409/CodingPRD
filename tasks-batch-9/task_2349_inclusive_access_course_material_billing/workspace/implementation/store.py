"""In-memory data store, logical clock and common-field helpers.

Storage is pure Python dicts.  The store is EMPTY on every boot: nothing is
seeded, preloaded or hardcoded.  Every entity is created through the declared
API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# PRD 2.4: before the clock has ever been set its value is 2026-08-01T00:00:00Z.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.terms = {}
        self.students = {}
        self.agreements = {}
        self.titles = {}
        self.tiers = {}
        self.sections = {}
        self.adoptions = {}
        self.enrollments = {}
        self.charges = {}
        self.ledger_entries = {}
        self.opt_out_requests = {}
        self.runs = {}
        self.reports = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_dt(db.clock)


def today():
    return db.clock.date()


def base_record(versioned=True):
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": db.seq()}
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(obj):
    """Register a mutation: refresh updated_at and bump version exactly once
    per entity per request (PRD 2.5 / 2.9)."""
    if obj is None:
        return
    key = id(obj)
    touched = getattr(g, "touched_entities", None)
    if touched is None:
        touched = set()
        g.touched_entities = touched
    if key in touched:
        return
    touched.add(key)
    obj["version"] = obj.get("version", 1) + 1
    obj["updated_at"] = now_iso()


def in_order(values):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))
