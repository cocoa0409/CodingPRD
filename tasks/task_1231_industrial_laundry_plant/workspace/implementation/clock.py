"""The logical plant clock.

The server never reads wall-clock time. Before any clock-setting call, the
logical clock reads exactly 2026-05-01T00:00:00Z. A PlantAdmin may set it via
POST /_clock/set_current_utc.
"""

from datetime import datetime, timezone

_current = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt


def fmt(dt):
    """ISO 8601 UTC timestamp with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    """Parse an ISO 8601 datetime; naive values are treated as UTC. None on failure."""
    if not isinstance(s, str):
        return None
    try:
        t = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def parse_date(s):
    """Parse a strict-ish YYYY-MM-DD calendar date. None on failure."""
    if not isinstance(s, str):
        return None
    try:
        parts = s.split("-")
        if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
            return None
        from datetime import date

        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None
