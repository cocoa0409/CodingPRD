"""Logical clock. Starts at 2026-01-01T00:00:00Z and never falls back to wall-clock."""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = DEFAULT_CLOCK

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt


clock = Clock()


def iso_now_real():
    """Real wall-clock ISO timestamp for response meta (api_request_timestamp)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def to_iso(dt):
    """Format a datetime as ISO8601 UTC with 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO8601 string into an aware UTC datetime. Raises ValueError on failure."""
    if not isinstance(s, str) or not s:
        raise ValueError("invalid datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
