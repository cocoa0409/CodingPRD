"""Server logical clock (PRD §2.11).

Before any clock is set, the logical clock reads 2026-04-01T00:00:00Z, and it
never falls back to wall-clock time. An administrative test-driving capability
sets the logical clock to a supplied instant via to_iso8601.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._current = _parse_iso(DEFAULT_CLOCK_ISO)

    def reset(self):
        self._current = _parse_iso(DEFAULT_CLOCK_ISO)

    def set_iso(self, iso_str):
        self._current = _parse_iso(iso_str)

    def now(self):
        return self._current


def _parse_iso(s):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso(s):
    return _parse_iso(s)


clock = LogicalClock()
