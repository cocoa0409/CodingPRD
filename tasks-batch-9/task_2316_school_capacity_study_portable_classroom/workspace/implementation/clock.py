"""Logical clock (PRD 2.4).

At server startup the logical clock reads exactly 2026-08-01T00:00:00Z and it
never falls back to real wall-clock time.  Every server-stamped timestamp and
every year/date derivation in the system reads this clock.
"""

from datetime import datetime, timezone, date

STARTUP_UTC = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(text):
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self.current = STARTUP_UTC

    def reset(self):
        self.current = STARTUP_UTC

    def set(self, dt):
        self.current = dt

    def now(self):
        return self.current

    def iso(self):
        return format_instant(self.current)

    def year(self):
        return self.current.year

    def today(self):
        return date(self.current.year, self.current.month, self.current.day)


clock = LogicalClock()
