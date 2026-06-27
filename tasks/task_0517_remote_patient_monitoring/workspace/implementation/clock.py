"""Logical clock (PRD §2.12).

At server startup the clock reads exactly 2026-05-01T00:00:00Z, and it never
falls back to wall-clock time; before any explicit set call it holds precisely
this default.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()


def parse_iso8601(value):
    """Parse an ISO-8601 instant into a timezone-aware UTC datetime.

    Returns None if value is not a parseable ISO-8601 datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_ts(dt):
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
