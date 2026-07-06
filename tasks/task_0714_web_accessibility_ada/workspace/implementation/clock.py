"""Logical clock. Starts at 2026-03-01T00:00:00Z on every boot; never wall-clock."""
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self.current = DEFAULT_CLOCK

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt

    def now_iso(self):
        return to_iso(self.current)


def to_iso(dt):
    """ISO 8601 UTC with three fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 UTC instant. Returns aware datetime or raises ValueError.

    Requires an explicit UTC designator (Z or +00:00 / -00:00 offset).
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    raw = s.strip()
    if not raw:
        raise ValueError("empty")
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ValueError("bad iso")
    if dt.tzinfo is None:
        # No timezone designator -> not a valid UTC instant per spec.
        raise ValueError("no tz")
    if dt.utcoffset() != timedelta(0):
        raise ValueError("not utc")
    return dt.astimezone(timezone.utc)
