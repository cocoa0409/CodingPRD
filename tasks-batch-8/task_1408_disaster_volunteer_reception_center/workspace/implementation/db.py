"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding, no preloading.
All timestamps come from the single logical clock; the server never falls
back to wall-clock time. Startup default is exactly 2026-08-01T00:00:00Z.
"""

import re
import uuid
from datetime import datetime, timezone

# --- Logical clock -----------------------------------------------------------

_START_OF_TIME = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

clock = _START_OF_TIME


def now():
    """Current logical-clock instant (timezone-aware UTC)."""
    return clock


def set_clock(value):
    global clock
    clock = value


# --- Entity stores (all start empty) -----------------------------------------

incidents = {}
volunteers = {}
credentials = {}
background_checks = {}
clearances = {}
support_requests = {}
shifts = {}
assignments = {}
trips = {}
seat_bookings = {}
ppe_issuances = {}
hour_entries = {}
risk_reports = {}

# Monotonic insertion sequence for stable list ordering within equal
# created_at instants (the logical clock makes created_at ties common).
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


_TS_FORMAT = "%Y-%m-%dT%H:%M:%S"


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime(_TS_FORMAT)
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def parse_ts(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Returns None when the value is not a valid timestamp string.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
