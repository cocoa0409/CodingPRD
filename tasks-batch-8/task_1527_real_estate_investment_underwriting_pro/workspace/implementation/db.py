"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "deals": {},
    "properties": {},
    "rent_roll_periods": {},
    "operating_expenses": {},
    "market_assumptions": {},
    "scenarios": {},
    "debt_sizings": {},
    "waterfalls": {},
    "ic_memos": {},
    "ic_votes": {},
}

# Logical clock for tests. Initialized at module import; never falls back to wall clock.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOGICAL_CLOCK = {"now": DEFAULT_CLOCK_DT}


def new_id():
    return str(uuid.uuid4())


def _format_iso(dt):
    """Format a tz-aware UTC datetime as ISO 8601 with three fractional digits and Z suffix."""
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.")
    return s + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Current logical UTC time as ISO 8601 with three fractional digits."""
    return _format_iso(LOGICAL_CLOCK["now"])


def now_dt():
    """Current logical UTC time as a tz-aware datetime."""
    return LOGICAL_CLOCK["now"]


def set_logical_clock(dt):
    """Advance the logical clock. Accepts a tz-aware datetime."""
    LOGICAL_CLOCK["now"] = dt.astimezone(timezone.utc)


def parse_iso_to_dt(s):
    """Parse an ISO 8601 string into a tz-aware UTC datetime. Accepts trailing 'Z' or numeric offset."""
    if not isinstance(s, str):
        return None
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
