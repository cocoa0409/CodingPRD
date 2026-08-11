"""Time, day-arithmetic and decimal helpers.

PRD 2.4 / 2.5 and scaffold value_conventions:
  * every rendered instant is ISO 8601 UTC with exactly three fractional
    digits and a trailing ``Z``;
  * a value the domain calls a *date* is normalised to 00:00:00.000Z;
  * whole-day arithmetic preserves the time of day;
  * "whole days between A and B" is floor((B - A) / 86400 s);
  * money / volume / pH / ABV carry 2 decimals, rounded half up.
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, InvalidOperation

UTC = timezone.utc

TWOPLACES = Decimal("0.01")


# --------------------------------------------------------------- instants


def parse_instant(value):
    """Parse an ISO 8601 string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    parsed = None
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def render_instant(value):
    """ISO 8601 UTC, exactly three fractional digits, trailing Z."""
    if value is None:
        return None
    moment = value.astimezone(UTC)
    millis = moment.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        millis,
    )


def normalise_date(value):
    """Collapse an instant onto 00:00:00.000Z of its own UTC calendar day."""
    if value is None:
        return None
    moment = value.astimezone(UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def add_days(value, days):
    """Whole-day arithmetic; the time of day is preserved."""
    if value is None:
        return None
    return value + timedelta(days=int(days))


def add_hours(value, hours):
    if value is None:
        return None
    return value + timedelta(hours=float(hours))


def add_minutes(value, minutes):
    if value is None:
        return None
    return value + timedelta(minutes=float(minutes))


def whole_days_between(start, end):
    """floor((end - start) / 86400 s); may be negative."""
    if start is None or end is None:
        return 0
    return int(math.floor((end - start).total_seconds() / 86400.0))


def same_utc_year(a, b):
    if a is None or b is None:
        return False
    return a.astimezone(UTC).year == b.astimezone(UTC).year


def yyyymmdd(value):
    moment = value.astimezone(UTC)
    return "%04d%02d%02d" % (moment.year, moment.month, moment.day)


def age_at_least(birth_instant, at_instant, years):
    """True when the person born at `birth_instant` has reached `years` by
    `at_instant`, measured on UTC calendar dates."""
    if birth_instant is None or at_instant is None:
        return False
    birth = birth_instant.astimezone(UTC).date()
    now = at_instant.astimezone(UTC).date()
    try:
        threshold = birth.replace(year=birth.year + int(years))
    except ValueError:  # 29 February
        threshold = birth.replace(year=birth.year + int(years), day=28)
    return now >= threshold


# --------------------------------------------------------------- decimals


def dec(value):
    """Decimal from an int / float / str / Decimal without binary noise."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InvalidOperation("bool is not a number")
    return Decimal(str(value))


def round2(value):
    if value is None:
        return None
    return dec(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def floor_div_units(numerator, denominator):
    """floor(numerator / denominator) as a plain int, in exact decimal."""
    quotient = dec(numerator) / dec(denominator)
    return int(quotient.to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(math.ceil(float(value)))


ZERO = Decimal("0.00")
