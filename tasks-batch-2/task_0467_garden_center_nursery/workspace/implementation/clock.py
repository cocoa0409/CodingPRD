"""Logical clock (PRD §2.4). Default 2026-01-01T00:00:00Z; never wall-clock."""
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


def parse_iso8601(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso8601_millis(dt):
    """Render an aware datetime as ISO-8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
