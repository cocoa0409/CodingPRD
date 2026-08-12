"""Logical clock — single source of time for the whole server.

Starts at 2026-05-01T00:00:00Z and only advances via POST /_clock/set_current_utc.
"""

from datetime import datetime, timezone

_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = _START


def now():
    """Return the current logical clock as an aware datetime (UTC)."""
    return _current


def set_current(dt):
    global _current
    _current = dt
    return _current


def iso(dt):
    """Format datetime as ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO8601 datetime string. Returns aware UTC datetime or None on failure."""
    if not isinstance(s, str):
        return None
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def parse_date(s):
    """Parse a YYYY-MM-DD date string. Returns a date or None on failure."""
    if not isinstance(s, str):
        return None
    try:
        from datetime import date as _date
        parts = s.strip().split("-")
        if len(parts) != 3:
            return None
        return _date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, AttributeError):
        return None
