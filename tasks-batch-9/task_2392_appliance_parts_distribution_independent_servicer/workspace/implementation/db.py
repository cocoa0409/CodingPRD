"""In-memory data store and logical clock.

The store starts completely empty on every boot.  Nothing is seeded, preloaded
or hardcoded here: every entity is created by an API call.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# PRD 2.4: the logical clock reads 2026-08-01T00:00:00Z until it is set.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.branches = {}
        self.parts = {}
        self.model_part_xrefs = {}
        self.pricing_tiers = {}
        self.servicer_accounts = {}
        self.technician_certifications = {}
        self.inventory_records = {}
        self.price_files = {}
        self.price_file_lines = {}
        self.part_orders = {}
        self.order_lines = {}
        self.substitute_requests = {}
        self.warranty_claims = {}
        self.return_authorizations = {}
        self.clock = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def now():
    """Current logical time.  Never falls back to the real wall clock."""
    return db.clock


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_stored(ts):
    """Parse a timestamp string previously produced by fmt()/input parsing."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def _touched_set():
    seen = getattr(g, "_touched_rows", None)
    if seen is None:
        seen = set()
        g._touched_rows = seen
    return seen


def base_row(versioned=True):
    """Common fields for a freshly created row."""
    stamp = fmt(now())
    row = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    # A row created during this request must not also be version-bumped by a
    # cascade later in the same request.
    _touched_set().add(row["id"])
    return row


def touch(row):
    """Register a mutation: refresh updated_at and bump version by exactly 1.

    A row is bumped at most once per HTTP request, even when several cascade
    hops revisit it.
    """
    if "version" not in row:
        return
    seen = _touched_set()
    row["updated_at"] = fmt(now())
    if row["id"] in seen:
        return
    seen.add(row["id"])
    row["version"] = row["version"] + 1


def sort_key(row):
    return (row["created_at"], row["_seq"])


def whole_days_between(earlier, later):
    """Floored whole days from earlier to later (both aware datetimes)."""
    if earlier is None or later is None:
        return 0
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


def days_ago(count):
    return now() - timedelta(days=count)
