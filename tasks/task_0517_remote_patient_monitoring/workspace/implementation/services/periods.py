"""Calendar-month interval helpers for billing periods.

The month is treated as the half-open calendar interval
[first-day-00:00Z, next-month-first-day-00:00Z) (PRD §3.8).
"""
from datetime import datetime, timezone


def month_start(year, month):
    return datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)


def next_month_start(year, month):
    if month == 12:
        return datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def month_interval(year, month):
    """Return (start_inclusive, end_exclusive) for the month."""
    return month_start(year, month), next_month_start(year, month)


def instant_in_month(dt, year, month):
    """True iff dt falls within the half-open month interval."""
    start, end = month_interval(year, month)
    return start <= dt < end


def month_fully_elapsed(year, month, now):
    """The month has fully elapsed relative to the clock iff now is at or
    after the first instant of the following month (PRD §3.8)."""
    return now >= next_month_start(year, month)


def last_calendar_day_end(year, month):
    """The end of the period's last calendar day == the next month's start
    (half-open). Timely filing is measured from the period's last calendar
    day; we use the next-month-start instant as the inclusive month-end edge."""
    return next_month_start(year, month)
