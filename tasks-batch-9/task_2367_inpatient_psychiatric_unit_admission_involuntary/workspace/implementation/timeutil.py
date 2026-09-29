"""Datetime helpers: millisecond ISO-8601 UTC formatting, court and business calendars.

PRD §2.6: datetime values are millisecond-truncated ISO 8601 UTC with exactly three
fractional digits. Court calendar 09:00:00-16:00:00 UTC; business calendar
08:00:00-17:00:00 UTC. Both share the same weekend + holiday exclusions.
"""

from datetime import date, datetime, time, timedelta, timezone

# PRD §2.6 / scaffold HOLIDAY_DATES
HOLIDAY_DATES = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }
)

COURT_OPEN = time(9, 0, 0)
COURT_CLOSE = time(16, 0, 0)
BUSINESS_OPEN = time(8, 0, 0)
BUSINESS_CLOSE = time(17, 0, 0)

UTC = timezone.utc


def fmt(value):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    dt = value.astimezone(UTC)
    ms = dt.microsecond // 1000
    return (
        f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
        f"T{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}.{ms:03d}Z"
    )


def truncate_ms(dt):
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when the value is not parseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return truncate_ms(dt.astimezone(UTC))


def at_time(day, tm):
    return datetime(day.year, day.month, day.day, tm.hour, tm.minute, tm.second, tzinfo=UTC)


def is_holiday_or_weekend(day):
    return day.weekday() >= 5 or day in HOLIDAY_DATES


def is_judicial_day(day):
    return not is_holiday_or_weekend(day)


def roll_to_court_window(candidate):
    """Roll an instant forward onto the court calendar (PRD §3.3 judicial_day_clock).

    Repeatedly: weekend/holiday -> next day 09:00:00.000Z; before 09:00 -> same day
    09:00:00.000Z; after 16:00 -> next day 09:00:00.000Z.
    """
    c = candidate
    # Bounded loop: each iteration either fixes the time-of-day or advances one day.
    for _ in range(4000):
        day = c.date()
        if is_holiday_or_weekend(day):
            c = at_time(day + timedelta(days=1), COURT_OPEN)
            continue
        tod = c.timetz().replace(tzinfo=None)
        if tod < COURT_OPEN:
            c = at_time(day, COURT_OPEN)
            continue
        if tod > COURT_CLOSE:
            c = at_time(day + timedelta(days=1), COURT_OPEN)
            continue
        return c
    return c


def business_hours_deadline(start, budget_hours=24):
    """Add `budget_hours` business hours to `start` (PRD §3.8 / discharge_request_response_deadline)."""
    remaining = timedelta(hours=budget_hours)
    c = start
    for _ in range(4000):
        day = c.date()
        open_at = at_time(day, BUSINESS_OPEN)
        close_at = at_time(day, BUSINESS_CLOSE)
        if is_holiday_or_weekend(day) or c >= close_at:
            c = at_time(day + timedelta(days=1), BUSINESS_OPEN)
            continue
        if c < open_at:
            c = open_at
        available = close_at - c
        if available >= remaining:
            return c + remaining
        remaining = remaining - available
        c = at_time(day + timedelta(days=1), BUSINESS_OPEN)
    return c
