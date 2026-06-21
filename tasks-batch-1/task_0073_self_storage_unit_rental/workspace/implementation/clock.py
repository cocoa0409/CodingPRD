from datetime import datetime, timezone


class Clock:
    """Server-maintained logical clock (PRD §2.9)."""

    def __init__(self):
        self._now = datetime.now(timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


def parse_iso8601(value):
    """Parse an ISO 8601 string to an aware UTC datetime. Returns None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso8601(dt):
    """Format an aware datetime as ISO 8601 UTC with millisecond precision."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
