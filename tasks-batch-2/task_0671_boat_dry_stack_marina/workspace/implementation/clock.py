"""Logical clock. PRD §1 / §4: server startup default is 2026-04-01T00:00:00Z and
the clock never falls back to wall-clock time. Every 'now' (offer deadlines,
slot openings, seasonal month, days-waiting) is read from this logical clock."""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._current = parse_iso(DEFAULT_CLOCK_ISO)

    def set(self, iso_str):
        self._current = parse_iso(iso_str)

    def now(self):
        """Return the current logical clock as a timezone-aware UTC datetime."""
        return self._current


def parse_iso(s):
    """Parse an ISO-8601 instant. Accepts trailing 'Z' and offsets; returns a
    timezone-aware UTC datetime. Raises ValueError/TypeError on bad input."""
    if not isinstance(s, str):
        raise ValueError("clock value must be a string")
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


clock = LogicalClock()
