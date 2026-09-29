"""Precision, clock and formatting helpers.

Every monetary or mass quantity in this service is a decimal.Decimal.
Floats are never used for arithmetic and Python's banker's-rounding
``round()`` is never called: PRD 2.6 mandates half-up rounding.
"""
import datetime as _dt
import random
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP

UTC = _dt.timezone.utc

ONE_DP = Decimal("0.1")
TWO_DP = Decimal("0.01")


def dec(value):
    """Coerce an int/float/Decimal into an exact Decimal (via str for floats)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    return Decimal(str(value))


def q1(value):
    """Round half up to one decimal place (masses, leak rates, thresholds)."""
    return dec(value).quantize(ONE_DP, rounding=ROUND_HALF_UP)


def q2(value):
    """Round half up to two decimal places (money, multipliers)."""
    return dec(value).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Returns an aware datetime, or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def fmt_instant(value):
    """Render an instant as ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    value = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def add_days(instant, days):
    """Add an exact multiple of 24 hours (PRD 2.6: no timezone/DST arithmetic)."""
    return instant + _dt.timedelta(days=int(days))


def add_minutes(instant, minutes):
    return instant + _dt.timedelta(minutes=int(minutes))


def add_calendar_years_midnight(instant, years):
    """Advance the calendar year, then normalise to 00:00:00Z.

    PRD 3.8: a 29 February anchor clamps to 28 February in the target year.
    """
    year = instant.year + int(years)
    month = instant.month
    day = instant.day
    if month == 2 and day == 29:
        day = 28
    return _dt.datetime(year, month, day, 0, 0, 0, 0, tzinfo=UTC)


def whole_days_between(start, end):
    """floor((end - start) / 86400 seconds); may be negative."""
    seconds = (end - start).total_seconds()
    return int(seconds // 86400)


def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
