from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO8601 string to a timezone-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Clock:
    def __init__(self):
        self.current = parse_iso(DEFAULT_CLOCK)

    def now(self):
        return self.current

    def set(self, iso_str):
        self.current = parse_iso(iso_str)
        return self.current


def iso_millis(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
