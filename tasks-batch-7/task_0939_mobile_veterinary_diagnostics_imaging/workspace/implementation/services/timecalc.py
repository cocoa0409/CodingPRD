"""Wall minutes, business minutes and the forward business-minute walk (PRD 2.5)."""

from datetime import timedelta

from core import clock
from core.constants import (
    DEFAULT_BUSINESS_CLOSE_MINUTE,
    DEFAULT_BUSINESS_DAYS,
    DEFAULT_BUSINESS_OPEN_MINUTE,
)


def clinic_calendar(clinic):
    if clinic is None:
        return (
            DEFAULT_BUSINESS_OPEN_MINUTE,
            DEFAULT_BUSINESS_CLOSE_MINUTE,
            list(DEFAULT_BUSINESS_DAYS),
        )
    return (
        clinic.get("business_open_minute", DEFAULT_BUSINESS_OPEN_MINUTE),
        clinic.get("business_close_minute", DEFAULT_BUSINESS_CLOSE_MINUTE),
        clinic.get("business_days", list(DEFAULT_BUSINESS_DAYS)),
    )


def wall_minutes_between(t0, t1):
    """max(0, floor((t1 - t0) seconds / 60)) — the calendar is ignored."""
    if t0 is None or t1 is None:
        return 0
    delta = (clock.to_utc(t1) - clock.to_utc(t0)).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // 60)


def business_minutes_between(t0, t1, clinic):
    """Whole minutes inside the clinic's opening windows between two instants."""
    if t0 is None or t1 is None:
        return 0
    t0 = clock.to_utc(t0)
    t1 = clock.to_utc(t1)
    if t1 <= t0:
        return 0
    open_min, close_min, days = clinic_calendar(clinic)
    total = 0
    day = t0.date()
    last = t1.date()
    while day <= last:
        if day.weekday() in days:
            midnight = clock.midnight_utc(day)
            win_start = midnight + timedelta(minutes=open_min)
            win_end = midnight + timedelta(minutes=close_min)
            lo = t0 if t0 > win_start else win_start
            hi = t1 if t1 < win_end else win_end
            if hi > lo:
                total += int((hi - lo).total_seconds() // 60)
        day = day + timedelta(days=1)
    return total


def advance_business_minutes(t0, n, clinic):
    """Advance `t0` by `n` business minutes on the clinic's calendar."""
    if t0 is None:
        return None
    t0 = clock.to_utc(t0)
    if n <= 0:
        return t0
    open_min, close_min, days = clinic_calendar(clinic)
    if not days or close_min <= open_min:
        return t0
    remaining = n
    cursor = t0
    day = cursor.date()
    # Bounded walk: 240 business minutes never needs more than a few weeks, but
    # a pathological clinic calendar (one open day a week, one minute long) is
    # still finite.  Cap the search at ~20 years of days.
    for _ in range(7500):
        if day.weekday() in days:
            midnight = clock.midnight_utc(day)
            win_start = midnight + timedelta(minutes=open_min)
            win_end = midnight + timedelta(minutes=close_min)
            if win_end > cursor:
                lo = cursor if cursor > win_start else win_start
                avail = int((win_end - lo).total_seconds() // 60)
                if avail >= remaining:
                    return lo + timedelta(minutes=remaining)
                remaining -= avail
                cursor = win_end
        day = day + timedelta(days=1)
    return cursor
