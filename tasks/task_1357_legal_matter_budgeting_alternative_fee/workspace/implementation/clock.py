"""Logical clock for testing/simulation (PRD §2.6).

At startup the logical clock reads exactly 2026-08-01T00:00:00Z. After
POST /_clock/set_current_utc, all derived date/period computations use
the configured instant.
"""
from datetime import datetime, timezone

DEFAULT_START_ISO = "2026-08-01T00:00:00Z"

_current_dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def _parse_iso(value):
    """Parse an ISO-8601 timestamp string into an aware datetime (UTC)."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    """Return the current logical instant (timezone-aware, UTC)."""
    return _current_dt


def now_iso():
    """Return the current logical instant as ISO-8601 UTC with 3 fractional digits."""
    return _current_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{_current_dt.microsecond // 1000:03d}Z"


def set_current(to_iso8601):
    """Set the logical clock; returns the effective instant as ISO string."""
    global _current_dt
    _current_dt = _parse_iso(to_iso8601)
    return now_iso()
