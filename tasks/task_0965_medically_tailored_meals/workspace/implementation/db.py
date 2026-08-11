"""In-memory data store, logical clock, id/timestamp helpers.

The store starts completely empty on every boot. All entities are created
exclusively through the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone, timedelta

# Global reentrant lock: serializes request handling so multi-step operations
# (cascades, ledger moves) are atomic even under concurrent requests.
lock = threading.RLock()

store = {
    "members": {},
    "referrals": {},
    "prescriptions": {},
    "menu_items": {},
    "menu_cycles": {},
    "cycle_items": {},
    "routes": {},
    "deliveries": {},
    "readings": {},
    "reauthorizations": {},
    "assessments": {},
    "claims": {},
}

# Logical clock: starts at exactly 2026-05-01T00:00:00Z, never wall-clock.
_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _DEFAULT_CLOCK


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_ts_lock = threading.Lock()
_last_ts = None


def now_iso():
    """Wall-clock timestamp, strictly monotonic so created_at ordering is stable."""
    global _last_ts
    with _ts_lock:
        t = datetime.now(timezone.utc)
        if _last_ts is not None and t <= _last_ts:
            t = _last_ts + timedelta(microseconds=1)
        _last_ts = t
    return format_ts(t)


def logical_now_iso():
    """Timestamp from the logical clock (used for delivered_at / confirmed_at)."""
    return format_ts(_clock)
