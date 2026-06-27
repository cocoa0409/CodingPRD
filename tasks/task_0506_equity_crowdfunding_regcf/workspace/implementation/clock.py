"""Logical clock (PRD 2.9).

The server boots with the logical clock set to exactly 2026-01-01T00:00:00Z.
Until it is explicitly set, the clock reads this default and never falls back to
real wall-clock time. A ComplianceOfficer may move it (forward or backward) via
POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

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
    """Parse an ISO 8601 instant -> timezone-aware UTC datetime, or raise ValueError."""
    if not isinstance(s, str) or not s.strip():
        raise ValueError("invalid datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


clock = Clock()
