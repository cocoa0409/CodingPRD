"""Server logical clock.

At startup the clock reads exactly 2026-05-01T00:00:00Z and never falls back to
wall-clock time. An administrative endpoint advances it to an explicit instant.
All time-dependent behaviour reads this clock.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()


def parse_iso8601(s):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None on failure.
    """
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601_ms(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
