"""In-memory data store, logical clock, id/timestamp generation.

The store starts empty on every boot. No seeding of any kind.
"""

import itertools
import uuid
from datetime import datetime, timezone, timedelta

store = {
    "growers": {},
    "fields": {},
    "cuttings": {},
    "weather_reports": {},
    "storage_sites": {},
    "bale_lots": {},
    "spoilage_events": {},
    "forage_tests": {},
    "market_indices": {},
    "buyers": {},
    "freight_lanes": {},
    "quotes": {},
    "contracts": {},
    "delivery_loads": {},
    "load_allocations": {},
    "baling_service_orders": {},
}

_seq = itertools.count(1)

# Logical clock: startup default is exactly 2026-08-01T00:00:00Z and never
# falls back to wall-clock time.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_last_ts = None


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def iso_ms(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    """Wall-clock UTC timestamp, 3 fractional digits, strictly monotonic."""
    global _last_ts
    t = datetime.now(timezone.utc)
    t = t.replace(microsecond=(t.microsecond // 1000) * 1000)
    if _last_ts is not None and t <= _last_ts:
        t = _last_ts + timedelta(milliseconds=1)
    _last_ts = t
    return iso_ms(t)


def stamp_new(e):
    """Populate common system fields on a freshly created entity."""
    ts = now_ts()
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_seq"] = next_seq()
    return e


def stamp_new_light(e):
    """Lightweight entities (weather reports, spoilage events, market indices)
    carry only id + created_at; no updated_at / version."""
    e["created_at"] = now_ts()
    e["_seq"] = next_seq()
    return e


def touch(e):
    """Every mutation refreshes updated_at and increments version by one."""
    e["updated_at"] = now_ts()
    e["version"] += 1
