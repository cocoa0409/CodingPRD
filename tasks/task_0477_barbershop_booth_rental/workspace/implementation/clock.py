"""Logical clock. Default is 2026-01-01T00:00:00Z; never falls back to wall-clock."""
from datetime import datetime, timezone

_DEFAULT = "2026-01-01T00:00:00Z"

# Module-level state. The store starts empty on every boot; the clock starts at
# the documented default.
_current = None  # datetime (aware, UTC)


def _parse_iso(s):
    """Parse an ISO 8601 instant (accepts trailing Z) into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset():
    global _current
    _current = _parse_iso(_DEFAULT)


def set_current(iso_str):
    global _current
    _current = _parse_iso(iso_str)


def now():
    """Return the current logical clock as an aware UTC datetime."""
    if _current is None:
        reset()
    return _current


def now_date():
    """Return the logical clock's calendar date as YYYY-MM-DD."""
    return now().date().isoformat()


reset()
