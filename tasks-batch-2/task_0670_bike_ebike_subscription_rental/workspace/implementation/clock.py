"""Logical clock. PRD 2.4: server startup default is 2026-04-01T00:00:00Z and
the clock never falls back to wall-clock time."""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._current = _parse_iso(DEFAULT_CLOCK_ISO)

    def set(self, iso_str):
        self._current = _parse_iso(iso_str)

    def now(self):
        """Return the current logical clock as a timezone-aware datetime (UTC)."""
        return self._current


def _parse_iso(s):
    """Parse an ISO-8601 instant. Accepts trailing 'Z' and offsets; returns a
    timezone-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("clock value must be a string")
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_clock_field(s):
    """Parse a client-supplied clock/datetime field used in bodies (return_due,
    window bounds, incident, expires_at). Returns aware UTC datetime or raises ValueError."""
    return _parse_iso(s)


clock = LogicalClock()
