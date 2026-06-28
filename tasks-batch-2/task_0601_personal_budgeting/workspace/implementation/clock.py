"""Server-controlled logical clock (PRD §3.7).

At startup the clock reads exactly 2026-01-01T00:00:00Z and never falls back to
wall-clock time. A PlatformAdmin advances it via POST /_clock/set_current_utc.
The cash-flow forecast and period dating read this clock.
"""

from datetime import datetime, timezone, timedelta, date

DEFAULT_INSTANT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_INSTANT

    def now(self):
        return self._now

    def today(self):
        return self._now.date()

    def set(self, instant):
        self._now = instant


clock = LogicalClock()


def parse_iso8601(value):
    """Parse an ISO 8601 instant. Accepts trailing 'Z'. Returns tz-aware UTC datetime.

    Raises ValueError on malformed input.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601_ms(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits and 'Z'."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(d, n):
    return d + timedelta(days=n)
