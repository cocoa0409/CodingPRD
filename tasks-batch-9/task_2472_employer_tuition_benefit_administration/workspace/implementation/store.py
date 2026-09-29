"""In-memory data store and the logical clock.

Storage is process-local Python dicts only.  The store starts completely empty
on every boot: no entity is ever seeded, preloaded or hardcoded here.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4 — before the clock has ever been set it reads exactly this instant and
# it never falls back to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "employers",
    "policies",
    "employees",
    "schools",
    "agreements",
    "programs",
    "listings",
    "requests",
    "enrollments",
    "invoices",
    "claims",
    "outcomes",
    "obligations",
    "tax_entries",
    "sessions",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso_ms(datetime.now(timezone.utc))


def new_id():
    return str(uuid.uuid4())


def new_record(fields, common=True):
    record = dict(fields)
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = db.next_seq()
    if common:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    # a row created in this request is already at its final version
    _first_touch_in_request(record)
    return record


def _first_touch_in_request(record):
    """True the first time a record is touched inside the current request.

    PRD 2.4/2.8: a resource's version increments by exactly 1 per mutation, and a
    request that mutates the same row through several cascade hops is still one
    mutation of that row.
    """
    try:
        from flask import g, has_request_context
    except ImportError:  # pragma: no cover - Flask is always present at runtime
        return True
    if not has_request_context():
        return True
    seen = getattr(g, "_touched_ids", None)
    if seen is None:
        seen = set()
        g._touched_ids = seen
    key = record.get("id")
    if key in seen:
        return False
    seen.add(key)
    return True


def touch(record):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.4 / 2.8)."""
    record["updated_at"] = now_iso()
    if _first_touch_in_request(record):
        record["version"] = record.get("version", 1) + 1
    return record


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
