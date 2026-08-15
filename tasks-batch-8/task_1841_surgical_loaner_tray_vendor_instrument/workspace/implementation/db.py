"""In-memory data store plus the logical, test-drivable clock.

Storage is in-memory only: plain module-level dicts keyed by id. Restarting
the process wipes every byte of state. Nothing is seeded at startup.
"""

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# Before any clock call has been made, the current time is exactly
# 2026-08-01T00:00:00Z (never the wall clock).
_clock_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_dt() -> datetime:
    """Current logical time as an aware UTC datetime."""
    return _clock_now


def set_clock(new_now: datetime) -> None:
    global _clock_now
    _clock_now = new_now


# ---------------------------------------------------------------------------
# Stores: one dict per entity type, keyed by id. All start empty.
# ---------------------------------------------------------------------------

vendors = {}
reps = {}
or_rooms = {}
sterilizer_units = {}
cases = {}
delay_events = {}
requests = {}
trays = {}
check_ins = {}
turns = {}
escalations = {}
access_passes = {}
pickups = {}
claims = {}
penalties = {}


# Monotonic creation sequence used for claim_seq (1-based creation order
# within a request) and for deterministic list ordering fallbacks.
_creation_seq = [0]


def next_creation_seq() -> int:
    _creation_seq[0] += 1
    return _creation_seq[0]


def new_id() -> str:
    """Mint a new UUID4 string id (no type prefix)."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with three fractional digits, e.g.
    2026-08-01T00:00:00.000Z. Datetimes are exact to the second; the
    fractional part is always .000 for logical-clock derived values."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.
    Accepts trailing 'Z' or numeric offsets. Returns None on failure."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_minutes(delta) -> int:
    """Whole minutes of a timedelta, floored at zero."""
    seconds = delta.total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60)
