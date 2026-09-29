"""The logical race clock (PRD 2.4).

Nothing in this system reads real wall-clock time.  The clock begins at the
fixed instant 2026-08-01T00:00:00Z and moves only when an operator sets it.
"""
import calendar
from datetime import date, datetime, timedelta, timezone

from errors import invalid

INITIAL_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self.current = INITIAL_UTC

    def now(self):
        return self.current

    def set(self, value):
        self.current = value


clock = LogicalClock()


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_dt(clock.now())


def parse_dt(value, field="timestamp"):
    """Parse an ISO 8601 datetime (Z or offset suffix; naive means UTC)."""
    if not isinstance(value, str) or not value.strip():
        raise invalid("%s must be an ISO 8601 datetime string" % field)
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise invalid("%s must be an ISO 8601 datetime string" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    if not isinstance(value, str):
        raise invalid("%s must be an ISO 8601 date (YYYY-MM-DD)" % field)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise invalid("%s must be an ISO 8601 date (YYYY-MM-DD)" % field)


def date_at_midnight_utc(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def subtract_months(d, months):
    """Month arithmetic that keeps the same day-of-month, clamping to the
    length of the target month (PRD 3.3)."""
    total = (d.year * 12 + (d.month - 1)) - months
    year = total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
