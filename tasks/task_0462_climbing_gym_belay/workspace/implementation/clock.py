"""Logical clock. Starts at 2026-01-01T00:00:00Z and stays there until set."""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()


def parse_iso8601(s):
    """Parse an ISO 8601 string into an aware UTC datetime. Returns None on failure."""
    if not isinstance(s, str):
        return None
    raw = s.strip()
    if not raw:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def to_iso_z(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits and a Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
