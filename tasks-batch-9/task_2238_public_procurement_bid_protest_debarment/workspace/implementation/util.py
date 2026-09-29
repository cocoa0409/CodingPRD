"""Date / money helpers.

PRD §2.7: money is integer cents, round-half-up; scores carry two decimals with
round-half-up; time arithmetic uses whole calendar days (preserving time of day)
and whole calendar months (preserving day-of-month, clamping to the last day of a
shorter target month). Instants are compared at millisecond precision.
"""

import calendar
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# instants
# --------------------------------------------------------------------------- #

def parse_dt(value):
    """Parse an ISO-8601 instant into a UTC-aware datetime truncated to ms.

    Raises ValueError when the value is not a parseable instant.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def fmt_dt(dt):
    """Render a datetime as an ISO 8601 UTC instant with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    """Whole calendar months, preserving day-of-month and clamping short months."""
    months = int(months)
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def months_between(start, end):
    """Whole calendar months elapsed from start to end (never negative)."""
    if end <= start:
        return 0
    n = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, n) > end:
        n -= 1
    return n if n > 0 else 0


def whole_minutes(start, end):
    """Length of a window in whole minutes, or None when it is not whole."""
    delta = end - start
    seconds = delta.total_seconds()
    if seconds < 0:
        return None
    if abs(seconds % 60) > 1e-9:
        return None
    return int(round(seconds / 60.0))


def floor_utc_day(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


# --------------------------------------------------------------------------- #
# arithmetic
# --------------------------------------------------------------------------- #

def dec(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def rhu_cents(value):
    """Round half-up to a whole cent."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half-up to two decimal places, returned as a Decimal."""
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num(value):
    """Render a numeric field: int when integral, else float."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    d = dec(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)
