"""In-memory data store, id minting, and the logical clock.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded here.  Every entity the API exposes is created by an API call.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError

# PRD 2.4: before any clock write the logical clock reads exactly this instant
# and it never falls back to real wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.facilities = {}
        self.reporting_periods = {}
        self.job_categories = {}
        self.workers = {}
        self.vendors = {}
        self.vendor_submissions = {}
        self.payroll_records = {}
        self.submissions = {}
        self.hour_entries = {}
        self.census_days = {}
        self.findings = {}
        self.measures = {}
        self.cases = {}
        self.appeals = {}
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._seq)


def wall_now():
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_str():
    return fmt_dt(wall_now())


def clock_now():
    return db.clock


def clock_str():
    return fmt_dt(db.clock)


def plus_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------

def base_record(versioned=True):
    ts = now_str()
    rec = {"id": new_id(), "created_at": ts}
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """PRD 2.4: updated_at refreshed and version incremented on every mutation."""
    rec["updated_at"] = now_str()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def find(coll, ident, error_id):
    if not isinstance(ident, str):
        raise ApiError(error_id)
    row = coll.get(ident)
    if row is None:
        raise ApiError(error_id)
    return row


def maybe(coll, ident):
    if not isinstance(ident, str):
        return None
    return coll.get(ident)


def ordered(rows):
    """Default list ordering: created_at ascending (insertion sequence)."""
    return sorted(rows, key=lambda r: r["_seq"])
