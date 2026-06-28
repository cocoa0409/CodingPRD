"""Server logical clock.

At startup the clock reads exactly 2026-01-01T00:00:00Z and stays there until
explicitly advanced via POST /_clock/set_current_utc. It NEVER falls back to
wall-clock time.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()


def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime.

    Accepts a trailing 'Z' and offset forms. Raises ValueError on bad input.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("invalid datetime")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso_millis():
    """Current logical clock time as ISO-8601 UTC with three fractional digits."""
    return format_iso_millis(clock.now())


def format_iso_millis(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"
