from datetime import datetime, timezone

DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"


def parse_iso8601(s):
    """Parse an ISO8601 string to a timezone-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601_ms(dt):
    """Format a datetime as ISO8601 UTC with exactly 3 fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._now = parse_iso8601(DEFAULT_CLOCK_UTC)

    def now(self):
        return self._now

    def set(self, iso_str):
        self._now = parse_iso8601(iso_str)


clock = LogicalClock()
