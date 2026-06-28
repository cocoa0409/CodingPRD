"""The server-maintained logical clock (PRD §2.4).

On server startup the clock reads exactly 2026-01-01T00:00:00Z, and before any
clock-setting call is made it holds this default and never falls back to the
host's real time. A StudioManager may move it to an arbitrary UTC instant.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


# Process-global logical clock. Recreated on every process boot (fresh state).
clock = Clock()


def parse_iso8601(value):
    """Parse an ISO 8601 string into a tz-aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def to_iso8601_millis(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with exactly three fractional
    digits and a trailing Z (PRD §2.2 / §2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # microseconds -> milliseconds
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % millis)
