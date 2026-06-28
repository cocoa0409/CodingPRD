"""Server-controlled logical clock (PRD §2.5).

On startup the clock reads exactly 2026-01-01T00:00:00Z and before any
clock-setting call it holds that default and never falls back to real time.
All time stored internally as a timezone-aware datetime in UTC.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = _DEFAULT


def reset():
    global _current
    _current = _DEFAULT


def now():
    return _current


def set_now(dt):
    global _current
    _current = dt


def parse_iso8601(s):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime.

    Accepts a trailing 'Z' and optional fractional seconds. Returns None on failure.
    """
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


def to_iso8601(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
