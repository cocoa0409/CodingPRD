"""Date / datetime helpers.

All instants in this service are ISO 8601 UTC with exactly three fractional
digits and a trailing ``Z`` (PRD 2.5).  Date arithmetic is performed in whole
days and whole calendar months; month arithmetic clamps an overflowing
day-of-month down to the last day of the target month (PRD 2.6).
"""
from calendar import monthrange
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def fmt(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # tolerate a space separator and date-only forms
        try:
            dt = datetime.fromisoformat(text.replace(" ", "T"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def midnight(year, month, day):
    return datetime(year, month, day, 0, 0, 0, 0, tzinfo=UTC)


def last_day_of_month(year, month):
    return monthrange(year, month)[1]


def fiscal_year_end(fiscal_year, fye_month):
    """Last calendar day of (fiscal_year, fye_month) at 00:00:00.000Z."""
    return midnight(fiscal_year, fye_month, last_day_of_month(fiscal_year, fye_month))


def add_months(dt, months):
    """Advance whole calendar months, clamping the day down when it overflows."""
    total = (dt.year * 12) + (dt.month - 1) + months
    year = total // 12
    month = (total % 12) + 1
    day = min(dt.day, last_day_of_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def whole_days_between(start, end):
    """floor((end - start) / 1 day) -- partial days are discarded.

    ``timedelta`` normalises so that 0 <= seconds < 86400, which makes
    ``delta.days`` exactly the floor of the quotient, including for negative
    intervals.
    """
    return (end - start).days
