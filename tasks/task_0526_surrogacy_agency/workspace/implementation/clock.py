"""Server-controlled logical clock (PRD §2.11).

On startup reads exactly 2026-05-01T00:00:00Z and never falls back to wall
clock. set_current_utc advances it deterministically.
"""
from datetime import datetime, timezone

DEFAULT_UTC = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_UTC

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()


def parse_iso8601(value):
    """Parse an ISO 8601 UTC datetime string. Returns aware datetime or raises."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
