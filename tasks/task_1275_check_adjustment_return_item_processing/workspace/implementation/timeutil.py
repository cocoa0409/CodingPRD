"""Logical-time helpers: parsing, calendar/business day reckoning (PRD §2.4)."""
from datetime import datetime, timedelta, timezone


def parse_dt(value):
    """Parse an ISO 8601 string (accepts trailing Z or offsets) to aware UTC."""
    if not isinstance(value, str):
        raise ValueError('not an ISO8601 string')
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_business_day(d):
    """A business day is a Monday-through-Friday date."""
    return d.weekday() < 5


def add_business_days(dt, n):
    """Advance a timestamp by n business days, preserving time-of-day."""
    cur = dt
    added = 0
    while added < n:
        cur = cur + timedelta(days=1)
        if is_business_day(cur.date()):
            added += 1
    return cur


def business_days_elapsed(start_date, end_date):
    """Count of Mon-Fri dates D with start_date < D <= end_date.

    Strictly after the event's date, up to and including the current date.
    """
    if end_date <= start_date:
        return 0
    days = (end_date - start_date).days
    count = 0
    for i in range(1, days + 1):
        if is_business_day(start_date + timedelta(days=i)):
            count += 1
    return count


def calendar_days_elapsed(start_date, end_date):
    """Whole calendar days from start_date to end_date (0 when same day)."""
    if end_date <= start_date:
        return 0
    return (end_date - start_date).days


def next_business_day_1700(dt):
    """17:00:00Z on the next business day strictly after dt's date."""
    d = dt.date() + timedelta(days=1)
    while not is_business_day(d):
        d = d + timedelta(days=1)
    return datetime(d.year, d.month, d.day, 17, 0, 0, tzinfo=timezone.utc)
