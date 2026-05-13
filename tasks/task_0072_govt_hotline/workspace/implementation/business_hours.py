"""Business-hours arithmetic.

Business window: Monday-Friday, 09:00 UTC - 17:00 UTC. Eight business hours per
business day, no overnight or weekend window.

`add_business_hours(base, h)` walks `h` business hours forward from `base`,
skipping non-business intervals, and returns the resulting wall-clock datetime.

`business_seconds_between(a, b)` measures business seconds in [a, b) (a <= b).
Used for SURVEY_EXPIRY (48 business hours), REOPEN_WINDOW (72 business hours),
SUPERVISION_REMINDER_INTERVAL (24 business hours).
"""

from datetime import datetime, timezone, timedelta

BUSINESS_DAY_START_HOUR = 9
BUSINESS_DAY_END_HOUR = 17
BUSINESS_HOURS_PER_DAY = BUSINESS_DAY_END_HOUR - BUSINESS_DAY_START_HOUR  # 8


def _is_business_day(dt: datetime) -> bool:
    return dt.weekday() < 5  # Mon-Fri


def _business_day_start(dt: datetime) -> datetime:
    return dt.replace(hour=BUSINESS_DAY_START_HOUR, minute=0, second=0, microsecond=0)


def _business_day_end(dt: datetime) -> datetime:
    return dt.replace(hour=BUSINESS_DAY_END_HOUR, minute=0, second=0, microsecond=0)


def add_business_hours(base: datetime, hours: int) -> datetime:
    """Walk `hours` business hours forward from `base`. Returns the resulting datetime in UTC.

    If `base` is outside business hours, the walk starts at the next business
    day's 09:00. The walk is precise in seconds: 8 hours = 28,800 business
    seconds per day.
    """
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    cur = base.astimezone(timezone.utc)
    remaining = int(hours) * 3600  # business seconds left to add

    while remaining > 0:
        if not _is_business_day(cur):
            # Jump to next business day's 09:00 UTC
            cur = _business_day_start(cur) + timedelta(days=1)
            while not _is_business_day(cur):
                cur = cur + timedelta(days=1)
            continue

        day_start = _business_day_start(cur)
        day_end = _business_day_end(cur)

        if cur < day_start:
            cur = day_start
            continue
        if cur >= day_end:
            # past today's business window; advance to next day's start
            cur = day_start + timedelta(days=1)
            while not _is_business_day(cur):
                cur = cur + timedelta(days=1)
            continue

        # cur is in [day_start, day_end)
        seconds_today = int((day_end - cur).total_seconds())
        if remaining <= seconds_today:
            cur = cur + timedelta(seconds=remaining)
            remaining = 0
        else:
            remaining -= seconds_today
            # advance to next day's start
            cur = day_start + timedelta(days=1)
            while not _is_business_day(cur):
                cur = cur + timedelta(days=1)
    return cur


def business_seconds_between(a: datetime, b: datetime) -> int:
    """Whole business seconds in [a, b). Returns 0 if b <= a."""
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    if b <= a:
        return 0
    a = a.astimezone(timezone.utc)
    b = b.astimezone(timezone.utc)

    total = 0
    cur = a
    while cur < b:
        if not _is_business_day(cur):
            cur = _business_day_start(cur) + timedelta(days=1)
            while not _is_business_day(cur):
                cur = cur + timedelta(days=1)
            continue
        day_start = _business_day_start(cur)
        day_end = _business_day_end(cur)
        if cur < day_start:
            cur = day_start
            continue
        if cur >= day_end:
            cur = day_start + timedelta(days=1)
            while not _is_business_day(cur):
                cur = cur + timedelta(days=1)
            continue
        seg_end = min(day_end, b)
        total += int((seg_end - cur).total_seconds())
        cur = seg_end
    return total


def business_hours_between(a: datetime, b: datetime) -> float:
    return business_seconds_between(a, b) / 3600.0
