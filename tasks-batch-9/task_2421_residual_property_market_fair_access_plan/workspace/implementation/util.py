"""Formatting, parsing and rounding helpers.

PRD 2.5: money is whole cents, rounded half-up (away from zero) at each named
step.  Ratios are half-up to four decimals.
PRD 2.6: instants and calendar dates are distinct classes of value.
"""

from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal(0)


def D(value):
    """Exact Decimal from an int/float/str/Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu_cents(value):
    """Round half-up to a whole number of cents (PRD 2.5)."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu4(value):
    """Round half-up to four decimal places (PRD 2.5 ratio discipline)."""
    return D(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def rhu2(value):
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(raw):
    """Parse an ISO-8601 instant; returns an aware UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # bare calendar date is also an acceptable instant literal
        try:
            dt = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(raw):
    """Parse a strict YYYY-MM-DD calendar date; returns a date or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def date_of(instant_or_str):
    """Calendar date of a stored instant string / datetime."""
    if instant_or_str is None:
        return None
    if isinstance(instant_or_str, datetime):
        return instant_or_str.astimezone(timezone.utc).date()
    dt = parse_instant(instant_or_str)
    return dt.date() if dt else None


def days_between(start, end):
    """Whole days from start date to end date (may be negative)."""
    return (end - start).days


def add_days(value, days):
    return value + timedelta(days=days)


__all__ = [
    "D", "ZERO", "rhu_cents", "rhu4", "rhu2", "iso_ms", "parse_instant",
    "parse_date", "fmt_date", "date_of", "days_between", "add_days",
    "datetime", "date", "timezone", "timedelta", "Decimal",
]
