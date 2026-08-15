"""In-memory data store and logical clock. Everything here is process-local:
restarting the process wipes all state. No disk persistence of any kind."""

import uuid
from datetime import datetime, timezone

# Logical clock: starts at exactly 2026-08-01T00:00:00Z, never wall-clock.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# Monotonic insertion sequence for stable created_at tie-breaking.
_SEQ = {"n": 0}

STORE = {
    "generators": {},
    "readings": {},
    "accounts": {},
    "certificates": {},
    "trades": {},
    "programs": {},
    "subscriptions": {},
    "bills": {},
    "retirements": {},
    "obligations": {},
    "reports": {},
}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def clock_now():
    return CLOCK["now"]


def set_clock(dt):
    CLOCK["now"] = dt


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_ts():
    return fmt_ts(CLOCK["now"])
