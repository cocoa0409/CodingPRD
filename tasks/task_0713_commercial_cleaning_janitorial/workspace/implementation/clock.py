"""Server logical clock (PRD §3.11). Starts at a fixed default; never wall-clock."""
from datetime import datetime, timezone
from constants import DEFAULT_CLOCK_ISO


class Clock:
    def __init__(self):
        self._now = parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        return self._now

    def set(self, iso):
        self._now = parse_iso(iso)
        return iso


def parse_iso(value):
    """Parse an ISO 8601 timestamp (optionally with trailing Z) into aware UTC."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
