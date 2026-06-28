"""Server-side logical clock.

PRD 2.5: All time-sensitive behavior reads a single server-side logical clock
rather than wall-clock time. Before any clock has been set, the server's startup
default is 2026-04-01T00:00:00Z, and the clock never falls back to wall-clock time.
"""
from datetime import datetime, timezone

# PRD 2.5 / SCAFFOLD run-ops + clock endpoint: startup default.
DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO 8601 UTC instant (accepting trailing 'Z') into aware datetime."""
    if not isinstance(value, str):
        raise ValueError("instant must be a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Clock:
    def __init__(self):
        self._now = _parse_iso(DEFAULT_CLOCK_ISO)

    def set(self, iso_value):
        self._now = _parse_iso(iso_value)

    def now(self):
        return self._now


clock = Clock()


def parse_iso(value):
    return _parse_iso(value)
