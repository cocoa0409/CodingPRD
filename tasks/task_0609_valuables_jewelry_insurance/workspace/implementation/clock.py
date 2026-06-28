"""Logical clock (PRD §2.6).

On startup the clock reads exactly 2026-01-01T00:00:00Z. It is the sole source
of "now" for every time comparison; the system never falls back to wall-clock.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

_now = None  # datetime (tz-aware UTC)


def parse_iso(value):
    """Parse an ISO-8601 UTC instant into a tz-aware UTC datetime."""
    if value is None:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset():
    global _now
    _now = parse_iso(DEFAULT_CLOCK)


def now():
    global _now
    if _now is None:
        reset()
    return _now


def now_iso():
    return to_iso(now())


def to_iso(dt):
    """Render a tz-aware datetime as ISO-8601 UTC with millisecond precision."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def set_now(dt):
    global _now
    _now = dt.astimezone(timezone.utc)


reset()
