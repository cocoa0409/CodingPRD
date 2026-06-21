"""Server-controlled logical clock (PRD §2.10).

At startup the clock reads exactly 2026-01-01T00:00:00Z and never falls back to
wall-clock time. A SeniorUnderwriter advances it via
POST /surety/_clock/set_current_utc. The clock governs the elapsed-month
measurement used by premium_earning (cancel) and rider_premium (rider apply).
"""

from datetime import datetime, timezone

DEFAULT_INSTANT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_INSTANT

    def now(self):
        return self._now

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


def months_between(start, end):
    """Whole calendar months from start to end (PRD §3.5/§3.6 elapsed_months).

    Counts complete months elapsed: the count increments only once the
    day-of-month (and intra-day time) of `end` reaches that of `start`. Can be
    negative if end < start; callers clamp to [0, term_months].
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # If the end's day/time has not yet reached the start's day/time, the most
    # recent month is not complete, so subtract one.
    if (end.day, end.hour, end.minute, end.second, end.microsecond) < (
        start.day, start.hour, start.minute, start.second, start.microsecond
    ):
        months -= 1
    return months
