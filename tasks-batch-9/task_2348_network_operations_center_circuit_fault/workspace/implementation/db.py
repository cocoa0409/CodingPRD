"""In-memory data store and the service's logical clock.

The store always boots empty — nothing is seeded, preloaded or hardcoded.
Every timestamp the server stamps comes from the logical clock, never from the
host wall clock.
"""

import itertools
import uuid
from datetime import datetime

from timeutil import UTC

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "carriers",
    "circuits",
    "devices",
    "paths",
    "segments",
    "alarms",
    "incidents",
    "tickets",
    "test_results",
    "claims",
    "windows",
    "failover_tests",
    "readings",
    "orders",
    "reviews",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_EPOCH
        self.counter = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})


db = Store()


def now():
    return db.clock


def set_clock(instant):
    # The clock only ever moves forward.
    if instant > db.clock:
        db.clock = instant
    return db.clock


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    rec = {"id": new_id(), "_seq": next(db.counter), "created_at": db.clock}
    if versioned:
        rec["updated_at"] = db.clock
        rec["version"] = 1
    return rec


def _touched():
    try:
        from flask import g, has_request_context

        if has_request_context():
            bucket = getattr(g, "touched_records", None)
            if bucket is None:
                bucket = set()
                g.touched_records = bucket
            return bucket
    except Exception:
        pass
    return set()


def touch(rec):
    """Refresh updated_at and advance version by exactly 1 per record per request."""
    if rec is None or "version" not in rec:
        return rec
    seen = _touched()
    key = rec["id"]
    if key in seen:
        rec["updated_at"] = db.clock
        return rec
    seen.add(key)
    rec["updated_at"] = db.clock
    rec["version"] = rec["version"] + 1
    return rec


def rows(collection):
    """All rows of a collection in ascending created_at (insertion) order."""
    return sorted(collection.values(), key=lambda r: r["_seq"])
