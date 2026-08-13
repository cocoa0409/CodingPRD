"""Date helpers: parsing, business days, weekend roll-forward, month arithmetic."""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone


def parse_date(value):
    """Parse an ISO YYYY-MM-DD date string; return date or None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_instant(value):
    """Parse an ISO 8601 datetime (accepts trailing Z); return aware datetime or None."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.endswith('Z'):
        v = v[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_date(d):
    return d.isoformat()


def business_days_between(start, end):
    """Count of days d with start < d <= end and weekday(d) in Mon..Fri."""
    days = 0
    d = start + timedelta(days=1)
    while d <= end:
        if d.weekday() < 5:
            days += 1
        d += timedelta(days=1)
    return days


def roll_forward_weekend(d):
    """Saturday/Sunday roll forward to the following Monday; weekdays unchanged."""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def add_months(d, months):
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    last = monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def last_day_of_month(d):
    return date(d.year, d.month, monthrange(d.year, d.month)[1])
