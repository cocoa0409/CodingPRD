"""In-memory data store plus the logical clock.

The store starts empty on every boot. Nothing here may seed, preload, or
hardcode entities — tests construct all state through the declared API.
"""
import re
import threading
import uuid
from datetime import datetime, timezone

LOCK = threading.RLock()

STORES = {
    "sites": {},
    "stalls": {},
    "rate_plans": {},
    "amenity_products": {},
    "drivers": {},
    "fleet_accounts": {},
    "driver_authorizations": {},
    "bookings": {},
    "booking_amenities": {},
    "waitlist_entries": {},
    "incidents": {},
    "invoices": {},
}

# Monotonic insertion sequence (stable ordering under identical created_at).
SEQ = {"n": 0}


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
_CLOCK = {"now": None}
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
_ISO_Z_RE = re.compile(r"Z$")


def _parse_dt(value):
    """Parse an ISO-8601 datetime into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    s = _ISO_Z_RE.sub("+00:00", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    if _CLOCK["now"] is None:
        _CLOCK["now"] = _parse_dt(DEFAULT_CLOCK_ISO)
    return _CLOCK["now"]


def set_clock(value):
    dt = _parse_dt(value)
    if dt is None:
        return None
    _CLOCK["now"] = dt
    return dt


# --------------------------------------------------------------------------
# Timestamp formatting
# --------------------------------------------------------------------------
def fmt_ts(dt):
    """Common-field timestamp: ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """Domain instant: seconds precision, preserving sub-second data if set."""
    if dt is None:
        return None
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
