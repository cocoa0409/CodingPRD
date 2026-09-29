"""The logical production clock (PRD §2.5).

On start-up the logical clock reads exactly 2026-08-01T00:00:00Z and keeps
reading that instant until an administrator moves it via
POST /_clock/set_current_utc.  It never falls back to host wall-clock time.
"""

from datetime import datetime, date, timedelta, timezone
from functools import lru_cache

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


@lru_cache(maxsize=8192)
def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@lru_cache(maxsize=8192)
def parse_date(value):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD)."""
    text = value.strip()
    if len(text) != 10:
        raise ValueError("not a YYYY-MM-DD date: %r" % value)
    return date.fromisoformat(text)


def format_dt(moment):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    moment = moment.astimezone(timezone.utc)
    return "%s.%03dZ" % (moment.strftime("%Y-%m-%dT%H:%M:%S"), moment.microsecond // 1000)


def add_days(moment, days):
    return moment + timedelta(days=days)


class LogicalClock:
    def __init__(self):
        self._now = parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        return self._now

    def now_iso(self):
        return format_dt(self._now)

    def today(self):
        return self._now.date()

    def set(self, moment):
        self._now = moment.astimezone(timezone.utc)

    def reset(self):
        self._now = parse_iso(DEFAULT_CLOCK_ISO)


clock = LogicalClock()


def real_now_iso():
    """Wall-clock stamp used only for the response envelope's meta block."""
    return format_dt(datetime.now(timezone.utc))
