"""Time, numeric and rounding helpers.

Every value rounded to two decimal places uses ROUND_HALF_UP (PRD 2.6).
Never use float arithmetic for effort percentages, person-months or scores.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

TWO = Decimal("0.01")
ONE = Decimal("1")


# ---------------------------------------------------------------- timestamps

def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_dt(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO-8601 instant (or plain date) into an aware UTC datetime.

    Returns None when the value is not a parseable instant.
    """
    if isinstance(value, datetime):
        d = value
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(text)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def parse_date(value):
    d = parse_dt(value)
    return None if d is None else d.date()


def plus_days(dt, days):
    return dt + timedelta(days=days)


# ------------------------------------------------------------------ decimals

def dec(value):
    """Coerce a JSON number/str into Decimal, or None when impossible."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
    return None


def round2(value):
    """Round half up to two decimal places."""
    return dec(value).quantize(TWO, rounding=ROUND_HALF_UP)


def round_int(value):
    """Round half up to a whole number."""
    return int(dec(value).quantize(ONE, rounding=ROUND_HALF_UP))


def num(value):
    """Serialize a Decimal as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def decimal_places(value):
    d = dec(value)
    if d is None:
        return 0
    exp = d.normalize().as_tuple().exponent
    if not isinstance(exp, int):
        return 0
    return max(0, -exp)
