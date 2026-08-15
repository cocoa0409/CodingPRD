"""Logical clock. Defaults to 2026-08-01T00:00:00Z; never falls back to wall-clock."""

from datetime import datetime, timezone, date

_DEFAULT = "2026-08-01T00:00:00Z"
_current = None  # datetime (aware UTC) once set


def _parse_iso(value):
    """Parse an ISO 8601 timestamp (with optional trailing Z) into an aware UTC datetime."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def set_current(to_iso8601):
    global _current
    _current = _parse_iso(to_iso8601)
    return current_iso()


def current_dt():
    if _current is None:
        return _parse_iso(_DEFAULT)
    return _current


def current_iso():
    dt = current_dt()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def current_date():
    """Calendar date of the logical clock (a datetime.date)."""
    return current_dt().date()


def today_iso():
    return current_date().isoformat()


def parse_date(value):
    """Parse YYYY-MM-DD into a datetime.date; raises ValueError on bad input."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    parts = value.split("-")
    if len(parts) != 3:
        raise ValueError("bad date")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))
