"""Time, date and decimal helpers.

All datetime values that leave this service are rendered as ISO 8601 UTC
strings with exactly three fractional digits (PRD 2.5), except
``response_deadline_at`` which the PRD pins to whole seconds.
"""

import re
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]00:00)$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_dt(value):
    """Parse a strict ISO 8601 UTC instant. Returns None when invalid."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=UTC,
        )
    except ValueError:
        return None


def fmt_dt(value):
    if value is None:
        return None
    dt = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_dt_sec(value):
    if value is None:
        return None
    dt = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def midnight(d):
    """Instant 00:00:00Z of the given date (accepts date or YYYY-MM-DD)."""
    if d is None:
        return None
    if isinstance(d, str):
        d = parse_date(d)
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def add_months(d, months):
    """Add calendar months, clamping the day of month to the target month."""
    if isinstance(d, str):
        d = parse_date(d)
    total = (d.year * 12 + (d.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = d.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def days_until(target_date, current):
    """floor((target_date at 00:00:00Z - current) / 86400 seconds).

    ``timedelta`` normalises to a non-negative seconds/microseconds part, so
    ``delta.days`` already is the mathematical floor of the day count.
    """
    delta = midnight(target_date) - current
    return delta.days


def dec(value):
    """Coerce a JSON scalar into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


ONE = Decimal(1)


def rhu(value, places=0):
    """Round half up to ``places`` decimal places."""
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def ceil_div(numerator, denominator):
    """Ceiling of an exact rational division (integers or Decimals)."""
    n = dec(numerator)
    d = dec(denominator)
    q = n / d
    floored = q.to_integral_value(rounding="ROUND_FLOOR")
    if q != floored:
        floored += 1
    return int(floored)


def num(value):
    """Render a Decimal for JSON: int when integral, else float."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def minute_of_day(dt):
    d = dt.astimezone(UTC)
    return d.hour * 60 + d.minute
