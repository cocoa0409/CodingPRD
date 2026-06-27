"""Logical clock (PRD §2.4).

On server startup the clock reads exactly 2026-01-01T00:00:00Z and never falls
back to wall-clock time. It is the sole time source for is_teen, next_run_at
due checks, and accrued_at / ran_at stamps.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = _DEFAULT

    def set(self, dt):
        self.now = dt

    def current(self):
        return self.now


def parse_iso8601(value):
    """Parse an ISO 8601 timestamp (optionally with a trailing 'Z') to an
    aware UTC datetime. Returns None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Bare date like 2013-06-26
        try:
            dt = datetime.strptime(value.strip(), "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a bare ISO date (YYYY-MM-DD) or a full ISO datetime into an
    aware UTC datetime at the start of that day. Returns None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    # Try a bare date first.
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
        return d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return parse_iso8601(s)


def iso(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"
