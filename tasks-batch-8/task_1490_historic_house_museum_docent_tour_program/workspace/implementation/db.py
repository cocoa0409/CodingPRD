"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "rooms": {},
    "routes": {},
    "scripts": {},
    "slots": {},
    "docents": {},
    "shifts": {},
    "members": {},
    "bookings": {},
    "incidents": {},
    "surveys": {},
}

# The museum-wide logical clock (PRD 2.5). Startup default is exactly
# 2026-08-01T00:00:00Z; it never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}


def new_id():
    return str(uuid.uuid4())


def now():
    """Current instant of the museum's logical clock."""
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def today():
    return now().date()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """Canonical ISO 8601 UTC; fractional seconds only when non-zero."""
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def wall_now_iso():
    """Wall-clock UTC for meta.api_request_timestamp, three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
