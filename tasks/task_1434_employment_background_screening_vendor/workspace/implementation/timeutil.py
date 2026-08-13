"""Logical clock + business-time arithmetic (PRD section 2.4)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

BUS_START_HOUR = 9
BUS_END_HOUR = 17


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


CLOCK = LogicalClock()


def now():
    return CLOCK.now()


def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    else:
        raise ValueError("not a datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _is_business_day(d):
    return d.weekday() < 5  # Mon..Fri


def business_hours_between(start, end):
    """Sum overlap of [start, end] with business windows (Mon-Fri 09:00-17:00Z).

    Returns Decimal hours, 2 decimal places, ROUND_HALF_UP.
    """
    if end <= start:
        return Decimal("0.00")
    total_seconds = 0.0
    day = start.date()
    last = end.date()
    one_day = timedelta(days=1)
    while day <= last:
        if _is_business_day(day):
            wstart = datetime(day.year, day.month, day.day,
                              BUS_START_HOUR, 0, 0, tzinfo=timezone.utc)
            wend = datetime(day.year, day.month, day.day,
                            BUS_END_HOUR, 0, 0, tzinfo=timezone.utc)
            lo = max(start, wstart)
            hi = min(end, wend)
            if hi > lo:
                total_seconds += (hi - lo).total_seconds()
        day += one_day
    hours = Decimal(str(total_seconds)) / Decimal("3600")
    return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sla_due_at(dispatched_at, tat_business_hours):
    """Walk forward from dispatch through business windows until tat hours elapse."""
    remaining = float(tat_business_hours) * 3600.0
    cursor = dispatched_at
    while True:
        if _is_business_day(cursor.date()):
            wstart = cursor.replace(hour=BUS_START_HOUR, minute=0,
                                    second=0, microsecond=0)
            wend = cursor.replace(hour=BUS_END_HOUR, minute=0,
                                  second=0, microsecond=0)
            s = max(cursor, wstart)
            if s < wend:
                avail = (wend - s).total_seconds()
                if avail >= remaining:
                    return s + timedelta(seconds=remaining)
                remaining -= avail
        cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0,
                                                      second=0, microsecond=0)


def business_day_add(dt, n):
    """Nth following business day at 00:00:00Z; the send day is excluded."""
    d = dt.date()
    count = 0
    while count < n:
        d += timedelta(days=1)
        if _is_business_day(d):
            count += 1
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def business_days_span_exclusive_inclusive(start_date, end_date):
    """Business days in (start_date exclusive, end_date inclusive]."""
    if end_date <= start_date:
        return 0
    d = start_date
    count = 0
    while d < end_date:
        d += timedelta(days=1)
        if _is_business_day(d):
            count += 1
    return count


def anniversary_years(d1, d2):
    """Full calendar years between date d1 and date d2 (anniversary method)."""
    years = d2.year - d1.year
    if (d2.month, d2.day) < (d1.month, d1.day):
        years -= 1
    return years


def subtract_years(d, n):
    """Calendar-anniversary year subtraction on a date (Feb 29 clamps)."""
    try:
        return d.replace(year=d.year - n)
    except ValueError:
        return d.replace(year=d.year - n, day=28)
