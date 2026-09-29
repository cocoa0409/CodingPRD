"""In-memory data store.

The store is EMPTY on every boot.  Nothing is seeded, preloaded or hardcoded:
every entity is created through the declared API surface.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# PRD 2.5: before the clock has been set for the first time it reads exactly
# 2026-08-01T00:00:00Z.  The server never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

LOCK = threading.RLock()


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant.  Raises ValueError when unparseable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def whole_days(later, earlier):
    """Whole UTC days between two instants, discarding any partial day (floor)."""
    return (later - earlier).days


def add_days(dt, days):
    return dt + timedelta(days=int(days))


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        self.search_rings = {}
        self.landlords = {}
        self.jurisdictions = {}
        self.candidates = {}
        self.leases = {}
        self.zoning_applications = {}
        self.structural_analyses = {}
        self.modification_designs = {}
        self.environmental_reviews = {}
        self.construction_permits = {}
        self.utility_providers = {}
        self.backhaul_orders = {}
        self.on_air_plans = {}

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The logical clock."""
    return db.clock


def new_record(fields):
    ts = db.clock
    rec = {"id": str(uuid.uuid4())}
    rec.update(fields)
    rec["created_at"] = fmt_dt(ts)
    rec["updated_at"] = fmt_dt(ts)
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    rec["_dt"] = {"created_at": ts, "updated_at": ts}
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at and increment version."""
    ts = db.clock
    rec["updated_at"] = fmt_dt(ts)
    rec["_dt"]["updated_at"] = ts
    rec["version"] += 1


def set_dt(rec, field, dt_value, raw=None):
    """Store a datetime field.  ``raw`` preserves a client supplied literal."""
    if dt_value is None:
        rec[field] = None
        rec["_dt"][field] = None
        return
    rec[field] = raw if raw is not None else fmt_dt(dt_value)
    rec["_dt"][field] = dt_value


def get_dt(rec, field):
    return rec.get("_dt", {}).get(field)


def sort_key(rec):
    """Default collection ordering: created_at ascending (stable by insertion)."""
    return (rec["_dt"]["created_at"], rec["_seq"])


def sorted_records(collection):
    return sorted(collection.values(), key=sort_key)


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
