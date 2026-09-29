"""Business-day calendar helpers.  Monday..Friday are business days; no holidays."""
import re
from datetime import date, datetime, timedelta, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$")


def parse_date(text):
    """Return a date for a well-formed ISO YYYY-MM-DD string, else None."""
    if not isinstance(text, str) or not DATE_RE.match(text):
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        return None


def fmt_date(d):
    return d.isoformat() if d is not None else None


def is_business_day(d):
    return d.weekday() < 5


def next_business_day_after(d):
    nxt = d + timedelta(days=1)
    while not is_business_day(nxt):
        nxt += timedelta(days=1)
    return nxt


def business_days_between(a, b):
    """Count business days x with a < x <= b."""
    if b <= a:
        return 0
    count = 0
    cur = a + timedelta(days=1)
    while cur <= b:
        if is_business_day(cur):
            count += 1
        cur += timedelta(days=1)
    return count


def last_day_of_month(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def add_months(d, months):
    """Advance by whole months, clamping the day to the last day of the target month."""
    total = (d.year * 12 + (d.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(d.day, last_day_of_month(year, month))
    return date(year, month, day)


def parse_instant(text):
    """Parse an ISO-8601 instant (Z or offset).  Returns aware UTC datetime or None."""
    if not isinstance(text, str) or not text:
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
