"""Business calendar arithmetic (PRD 2.5, calculation business_day_arithmetic)."""
import datetime as _dt
from decimal import Decimal, ROUND_HALF_UP

import clock
from constants import (
    BUSINESS_DAY_END_HOUR_UTC,
    BUSINESS_DAY_START_HOUR_UTC,
    BUSINESS_WEEKDAYS,
)

ONE_DAY = _dt.timedelta(days=1)


def closure_set(consulate):
    if not consulate:
        return set()
    return set(consulate.get("closure_dates") or [])


def is_business_day(day, consulate=None):
    if day.weekday() not in BUSINESS_WEEKDAYS:
        return False
    if consulate is not None:
        if clock.render_date(day) in closure_set(consulate):
            return False
    return True


def next_business_day_on_or_after(day, consulate=None):
    cur = day
    guard = 0
    while not is_business_day(cur, consulate):
        cur = cur + ONE_DAY
        guard += 1
        if guard > 3660:
            break
    return cur


def advance_business_days(day, n, consulate=None):
    """PRD 2.5: normalise onto a business day, then step n times."""
    cur = next_business_day_on_or_after(day, consulate)
    for _ in range(max(int(n), 0)):
        cur = cur + ONE_DAY
        cur = next_business_day_on_or_after(cur, consulate)
    return cur


def business_minutes_between(t1, t2, consulate=None):
    """Whole business minutes between two instants, truncated toward zero."""
    if t1 is None or t2 is None:
        return 0
    if t2 <= t1:
        return 0
    total = 0
    day = t1.date()
    last = t2.date()
    guard = 0
    while day <= last:
        guard += 1
        if guard > 3660:
            break
        if is_business_day(day, consulate):
            window_start = _dt.datetime(
                day.year, day.month, day.day, BUSINESS_DAY_START_HOUR_UTC, 0, 0,
                tzinfo=clock.UTC,
            )
            window_end = _dt.datetime(
                day.year, day.month, day.day, BUSINESS_DAY_END_HOUR_UTC, 0, 0,
                tzinfo=clock.UTC,
            )
            lo = max(t1, window_start)
            hi = min(t2, window_end)
            if hi > lo:
                total += int((hi - lo).total_seconds() // 60)
        day = day + ONE_DAY
    return total


def add_calendar_months(day, months):
    """Add whole calendar months, clamping to the last day of a shorter month."""
    months = int(months)
    year = day.year + (day.month - 1 + months) // 12
    month = (day.month - 1 + months) % 12 + 1
    last_day = _month_length(year, month)
    return _dt.date(year, month, min(day.day, last_day))


def _month_length(year, month):
    if month == 12:
        nxt = _dt.date(year + 1, 1, 1)
    else:
        nxt = _dt.date(year, month + 1, 1)
    return (nxt - _dt.date(year, month, 1)).days


def whole_years_between(born, target):
    """Floored whole years; the birthday must have occurred on or before target."""
    years = target.year - born.year
    if (target.month, target.day) < (born.month, born.day):
        years -= 1
    return years


def round_half_up(value):
    """Round a Decimal/int to whole cents, half away from zero (upward)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def day_at_hour(day, hour):
    return _dt.datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=clock.UTC)
