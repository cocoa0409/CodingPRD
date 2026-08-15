"""In-memory data store and the server logical clock.

The store starts empty on every boot. Nothing is seeded here or anywhere else;
every entity is constructed through the declared API surface.
"""
import threading
from datetime import datetime, timedelta, timezone

STORE = {
    "rooms": {},
    "staff": {},
    "cases": {},
    "assignments": {},
    "lots": {},
    "usages": {},
    "dose_records": {},
    "beds": {},
    "submissions": {},
}

_LOCK = threading.RLock()

# Logical clock: startup default is exactly 2026-08-01T00:00:00Z and never
# falls back to wall-clock time.
_clock_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_last_tick = None
_seq_counter = 0


def logical_now():
    """Current logical-clock reading (second resolution, UTC)."""
    return _clock_now


def set_clock(dt):
    global _clock_now
    with _LOCK:
        _clock_now = dt.astimezone(timezone.utc).replace(microsecond=0)


def tick():
    """Monotonic timestamp derived from the logical clock.

    Used for created_at / updated_at / api_request_timestamp. Strictly
    increasing across the process so created_at ordering is always defined,
    even while the logical clock is frozen.
    """
    global _last_tick
    with _LOCK:
        base = _clock_now
        if _last_tick is None or base > _last_tick:
            cur = base
        else:
            cur = _last_tick + timedelta(milliseconds=1)
        _last_tick = cur
        return cur


def next_seq():
    """Global creation-order counter (defines created_at ASC ordering)."""
    global _seq_counter
    with _LOCK:
        _seq_counter += 1
        return _seq_counter
