"""Arithmetic and calendar helpers.

Money is always integer cents.  Rounding, wherever a percentage or an average is
applied to money, is round half up (away from zero at the exact half).
"""

import calendar
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal/number to an integer, half away from zero."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of_cents(pct, cents):
    """round_half_up(pct * cents) -> integer cents."""
    return round_half_up(dec(pct) * Decimal(int(cents)))


def ratio(numerator, denominator, places):
    """round_half_up(numerator / denominator, places) as a Decimal."""
    quantum = Decimal(1).scaleb(-int(places))
    return (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        quantum, rounding=ROUND_HALF_UP
    )


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

def parse_datetime(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date into an aware UTC midnight datetime."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def add_months(dt, months):
    total = dt.month - 1 + int(months)
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    from datetime import timedelta

    return dt + timedelta(days=int(days))
