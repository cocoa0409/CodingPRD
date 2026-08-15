"""Logical clock (PRD §2.5).

Startup default is exactly 2026-08-01T00:00:00Z. The clock advances only via
POST /r2t4/_clock/set_current_utc and never falls back to wall-clock.
"""

from datetime import datetime, timezone

_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = _DEFAULT


def now() -> datetime:
    return _current


def set_current(dt: datetime) -> None:
    global _current
    _current = dt


def current_date():
    return _current.date()


def iso(dt: datetime) -> str:
    """Format an aware UTC datetime as ISO 8601 with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso(_current)


def parse_iso_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None on failure.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
