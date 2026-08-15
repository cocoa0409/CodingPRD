"""Logical clock (PRD §2.4). Starts at 2026-08-01T00:00:00Z; never wall-clock."""
from datetime import datetime, timezone

DEFAULT_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = DEFAULT_START


def now():
    return _current


def now_iso():
    return format_iso(_current)


def set_current(dt):
    global _current
    _current = dt
    return _current


def format_iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime into an aware UTC datetime. Returns None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat.
    candidate = s
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
