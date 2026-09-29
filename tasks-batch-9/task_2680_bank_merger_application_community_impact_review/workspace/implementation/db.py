"""In-memory data store, logical clock and record bookkeeping.

Storage is process-memory only: plain Python dicts, empty on every boot.
Nothing is ever seeded, preloaded or hardcoded here.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# The logical clock reads exactly this instant before any /_clock call (PRD 2.4).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "institutions",
    "markets",
    "branches",
    "applications",
    "schedules",
    "analyses",
    "periods",
    "comments",
    "hearings",
    "plans",
    "line_items",
    "decisions",
    "conditions",
    "conversion_plans",
    "reports",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)


db = Store()


# --------------------------------------------------------------------------
# clock helpers
# --------------------------------------------------------------------------
def now_dt():
    return db.clock


def set_clock(dt):
    db.clock = dt


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_str():
    return fmt_dt(db.clock)


def parse_dt(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def whole_days_between(start, end):
    """Whole UTC days from start to end, floored (partial days discarded)."""
    delta = end - start
    return int(delta.total_seconds() // 86400)


# --------------------------------------------------------------------------
# record bookkeeping
# --------------------------------------------------------------------------
def _touched():
    try:
        bucket = g.get("_touched_ids", None) if hasattr(g, "get") else None
    except RuntimeError:
        return set()
    if bucket is None:
        bucket = set()
        try:
            g._touched_ids = bucket
        except RuntimeError:
            return set()
    return bucket


def new_record(fields):
    """Create a record with the common fields (PRD 2.4)."""
    stamp = now_str()
    rec = {"id": str(uuid.uuid4())}
    rec.update(fields)
    rec["created_at"] = stamp
    rec["updated_at"] = stamp
    rec["version"] = 1
    rec["_seq"] = next(db._seq)
    # A freshly created record must not be version-bumped by a cascade that
    # runs later inside the very same request.
    _touched().add(rec["id"])
    return rec


def touch(rec):
    """Refresh updated_at and increment version, at most once per request."""
    bucket = _touched()
    if rec["id"] in bucket:
        return
    bucket.add(rec["id"])
    rec["version"] = int(rec["version"]) + 1
    rec["updated_at"] = now_str()


def set_fields(rec, **changes):
    """Apply changes; touch the record only when something actually changed."""
    changed = False
    for key, value in changes.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_records(collection, predicate=None):
    items = [r for r in collection.values() if predicate is None or predicate(r)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return items
