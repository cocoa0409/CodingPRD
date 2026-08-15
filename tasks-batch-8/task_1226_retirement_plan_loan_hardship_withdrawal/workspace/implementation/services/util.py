"""Shared helpers: id/timestamp generation, date arithmetic, common fields."""

import uuid
from datetime import timedelta

from clock import CLOCK, format_iso, format_date_iso, _parse_iso


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return CLOCK.now_iso()


def today():
    """Logical clock as a datetime."""
    return CLOCK.now()


def add_months(dt, months):
    """Add calendar months, preserving day-of-month where possible (clamp to month end)."""
    month_index = dt.year * 12 + (dt.month - 1) + months
    y = month_index // 12
    m = month_index % 12 + 1
    # clamp day
    if m == 12:
        next_month_first = dt.replace(year=y + 1, month=1, day=1)
    else:
        next_month_first = dt.replace(year=y, month=m + 1, day=1)
    last_day = (next_month_first - timedelta(days=1)).day
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap years
        return dt.replace(year=dt.year + years, day=28)


def quarter_last_day(dt):
    """Last day of the calendar quarter containing dt, at date granularity
    (midnight at the start of the last day — PRD section 2.5 computes
    deadlines at date granularity, and the cure boundary is inclusive of the
    deadline date)."""
    q = (dt.month - 1) // 3  # 0..3
    end_month = q * 3 + 3
    if end_month == 12:
        first_next = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        first_next = dt.replace(month=end_month + 1, day=1)
    return (first_next - timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                    microsecond=0)


def last_day_of_next_quarter(dt):
    """Last day of the calendar quarter immediately following the quarter containing dt."""
    q = (dt.month - 1) // 3
    end_month = q * 3 + 3
    if end_month == 12:
        first_next = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        first_next = dt.replace(month=end_month + 1, day=1)
    # first day of next quarter
    nq_first = first_next
    # last day of next quarter
    return quarter_last_day(nq_first)


def system_fields_create(obj):
    """Stamp created_at/updated_at/version onto a primary resource dict."""
    ts = now_iso()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def touch(obj):
    """Refresh updated_at and bump version on a primary resource."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


def touch_no_version(obj):
    """Refresh updated_at without a version bump (rare; version always bumps in this scaffold)."""
    obj["updated_at"] = now_iso()
    return obj


def iso(dt):
    return format_iso(dt)


def date_iso(dt):
    """Render a clock-derived date stamp at date granularity (no fractional
    digits), matching the logical clock's canonical reading."""
    return format_date_iso(dt)


def parse(s):
    return _parse_iso(s)
