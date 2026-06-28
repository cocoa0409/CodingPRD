"""Server-controlled logical clock (PRD §2.9).

At startup the clock reads exactly 2026-04-01T00:00:00Z, and until it is
explicitly set it stays at that default and never falls back to real time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        """Current logical instant as a tz-aware datetime."""
        return self._now

    def set(self, dt):
        self._now = dt


# Module-level singleton, reset on each fresh process boot.
clock = LogicalClock()


def parse_iso8601(s):
    """Parse an ISO 8601 instant (accepts trailing 'Z') to tz-aware UTC datetime.

    Returns None if unparseable.
    """
    if not isinstance(s, str):
        return None
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso8601(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
