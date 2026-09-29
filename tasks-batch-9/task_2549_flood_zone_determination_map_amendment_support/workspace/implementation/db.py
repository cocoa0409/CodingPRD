"""In-memory store and the logical clock.

Storage is process-local Python dicts only.  Nothing is seeded at import time or
at boot: every entity in this API is created by an API call.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD section 2.4: before any client has set it the logical clock reads exactly
# 2026-08-01T00:00:00Z, and the implementation never falls back to wall clock.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "communities",
    "lenders",
    "map_panels",
    "properties",
    "structures",
    "loan_folios",
    "determinations",
    "disputes",
    "elevation_certificates",
    "map_amendment_requests",
    "compliance_notices",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    # --- logical clock ----------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, instant):
        self.clock = instant

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(**fields):
    """Create a row carrying the common fields of PRD section 2.4."""
    now = db.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """A real mutation: refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = db.now()
    row["version"] = row["version"] + 1
    return row


def ordered(rows):
    """Collections are always returned sorted by created_at ascending.

    Insertion sequence is the tie-break so the ordering stays total when several
    rows share a logical-clock instant; the identifier is never consulted.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def all_rows(collection):
    return ordered(getattr(db, collection).values())


def add_years(dt, n):
    try:
        return dt.replace(year=dt.year + n)
    except ValueError:  # 29 Feb in a non-leap target year
        return dt.replace(year=dt.year + n, day=28)


def add_days(dt, n):
    return dt + timedelta(days=n)


def day_count(start, end):
    """Whole days from start up to but not including end."""
    return (end - start).days
