"""Logical clock. Default 2026-05-01T00:00:00Z, never falls back to wall time."""
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def set(self, dt):
        self.now = dt


def parse_iso(s):
    """Parse an ISO 8601 UTC instant. Returns aware datetime in UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso_ms(dt):
    """ISO 8601 UTC with three fractional digits and trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    return dt + timedelta(days=days)
