from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-03-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO 8601 UTC instant into an aware datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Clock:
    def __init__(self):
        self.current = parse_iso(DEFAULT_CLOCK)

    def now(self):
        return self.current

    def now_iso(self):
        return fmt_iso(self.current)

    def set(self, iso):
        self.current = parse_iso(iso)
