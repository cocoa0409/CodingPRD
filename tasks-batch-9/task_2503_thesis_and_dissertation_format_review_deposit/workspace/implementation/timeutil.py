"""Timestamp rendering/parsing plus the business-day and month arithmetic
helpers defined in PRD section 2.7 and section 3.7.
"""

import calendar
from datetime import date, datetime, timedelta, timezone

# Institutional holidays (PRD section 2.7).
HOLIDAYS = {
    date(2026, 11, 26),
    date(2026, 11, 27),
    date(2026, 12, 24),
    date(2026, 12, 25),
    date(2027, 1, 1),
}


def iso(instant):
    """ISO 8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    inst = instant.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        inst.year,
        inst.month,
        inst.day,
        inst.hour,
        inst.minute,
        inst.second,
        inst.microsecond // 1000,
    )


def date_str(instant):
    """YYYY-MM-DD in UTC."""
    if instant is None:
        return None
    inst = instant.astimezone(timezone.utc)
    return "%04d-%02d-%02d" % (inst.year, inst.month, inst.day)


def parse_iso(text):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_business_day(day):
    return day.weekday() < 5 and day not in HOLIDAYS


def business_days_between(earlier, later):
    """Business days strictly after date(earlier) up to and including date(later)."""
    start = earlier.astimezone(timezone.utc).date()
    end = later.astimezone(timezone.utc).date()
    if end <= start:
        return 0
    count = 0
    cursor = start
    while cursor < end:
        cursor = cursor + timedelta(days=1)
        if is_business_day(cursor):
            count += 1
    return count


def add_business_days(instant, days):
    """Advance the calendar date by `days` business days, preserving time-of-day."""
    base = instant.astimezone(timezone.utc)
    cursor = base.date()
    counted = 0
    while counted < days:
        cursor = cursor + timedelta(days=1)
        if is_business_day(cursor):
            counted += 1
    return datetime(
        cursor.year,
        cursor.month,
        cursor.day,
        base.hour,
        base.minute,
        base.second,
        base.microsecond,
        tzinfo=timezone.utc,
    )


def add_months(instant, months):
    """Advance an instant by whole calendar months, clamping the day of month."""
    base = instant.astimezone(timezone.utc)
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return datetime(
        year,
        month,
        day,
        base.hour,
        base.minute,
        base.second,
        base.microsecond,
        tzinfo=timezone.utc,
    )


def whole_minutes(start, end):
    return (end - start).total_seconds() / 60.0
