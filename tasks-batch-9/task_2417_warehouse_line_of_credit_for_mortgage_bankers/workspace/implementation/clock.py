"""The logical clock (PRD 2.4).

The service never reads the wall clock for business behaviour.  Its mandatory
default value before any call is 2026-08-01T00:00:00Z.  Setting it changes no
business state and recomputes nothing.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_RAW = "2026-08-01T00:00:00Z"
SECONDS_PER_DAY = 86400


def parse_iso(text):
    """Parse an ISO 8601 UTC timestamp.  Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class LogicalClock(object):
    def __init__(self):
        self.raw = DEFAULT_RAW
        self.dt = parse_iso(DEFAULT_RAW)

    def set(self, raw, dt):
        previous_raw = self.raw
        self.raw = raw
        self.dt = dt
        return previous_raw

    def now(self):
        return self.dt

    def date(self):
        return self.dt.date()


clock = LogicalClock()


def elapsed_days(start, end):
    """Complete 86,400-second periods elapsed from ``start`` to ``end``, with
    any partial period discarded (PRD 3.6 / 3.9)."""
    if start is None or end is None:
        return 0
    delta = end - start
    total_seconds = delta.days * SECONDS_PER_DAY + delta.seconds
    return total_seconds // SECONDS_PER_DAY


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def wall_now():
    return datetime.now(timezone.utc)
