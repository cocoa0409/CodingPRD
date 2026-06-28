"""Logical clock. PRD §2.4: on server startup the clock reads exactly
2026-01-01T00:00:00Z, and before any clock-setting call it stays at that
default and never falls back to real time."""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()


def parse_iso8601(s):
    """Parse an ISO 8601 string into a tz-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601(dt):
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
