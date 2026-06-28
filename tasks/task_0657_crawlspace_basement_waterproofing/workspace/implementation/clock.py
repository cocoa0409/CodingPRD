"""Server-maintained logical clock.

PRD §2.5: All time-dependent rules are evaluated against a server-maintained
logical clock rather than wall-clock time. On startup the clock reads exactly
2026-04-01T00:00:00Z and never falls back to real time before any client sets it.
"""
from datetime import datetime, timezone

CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO 8601 instant (accepts trailing Z) into an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Clock:
    def __init__(self):
        self._now = _parse_iso(CLOCK_DEFAULT_UTC)

    def now(self):
        return self._now

    def set(self, iso_value):
        self._now = _parse_iso(iso_value)

    def reset(self):
        self._now = _parse_iso(CLOCK_DEFAULT_UTC)


# Module-level singleton clock — wiped on every process boot.
clock = Clock()
