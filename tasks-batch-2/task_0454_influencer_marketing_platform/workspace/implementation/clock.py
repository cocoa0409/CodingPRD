"""Logical clock.

At server startup the logical clock reads exactly 2026-01-01T00:00:00Z, and
before any clock-setting call it stays at that default and never falls back to
real wall-clock time (PRD 2.5). The clock can be moved both forward and backward.
"""
from datetime import datetime, timezone

# Default logical clock value at startup (PRD 2.5).
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = _DEFAULT

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt

    def now_iso(self):
        return format_iso(self.current)


def format_iso(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 instant. Returns a timezone-aware UTC datetime or raises ValueError."""
    if not isinstance(s, str) or not s:
        raise ValueError("invalid datetime")
    raw = s.strip()
    txt = raw
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


clock = Clock()
