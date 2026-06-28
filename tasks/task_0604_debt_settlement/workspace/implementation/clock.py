"""Logical clock. Starts at 2026-01-01T00:00:00Z; never falls back to wall clock."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = _DEFAULT

    def reset(self):
        self.now = _DEFAULT

    def set(self, dt):
        self.now = dt

    def get(self):
        return self.now


clock = Clock()


def parse_iso8601(s):
    """Parse an ISO8601 instant to a tz-aware UTC datetime. Returns None on failure."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601(dt):
    """Format a datetime as ISO8601 UTC with three fractional digits and Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
