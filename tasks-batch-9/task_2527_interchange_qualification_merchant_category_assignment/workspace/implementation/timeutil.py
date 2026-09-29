"""Millisecond-resolution UTC instants, ISO-8601 rendering, quarter arithmetic
and the half-up rounding primitives mandated by PRD section 2.7."""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?"
    r"(\.\d{1,9})?\s*(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_iso_ms(value):
    """Parse an ISO-8601 instant into integer epoch milliseconds.

    Returns None when the value is not a parseable instant.
    """
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    tz = m.group(8)
    millis = 0
    if frac:
        digits = (frac[1:] + "000")[:3]
        millis = int(digits)
    try:
        base = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except ValueError:
        return None
    total = int((base - EPOCH).total_seconds()) * 1000 + millis
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        try:
            off_h = int(body[:2])
            off_m = int(body[2:4]) if len(body) >= 4 else 0
        except ValueError:
            return None
        total -= sign * (off_h * 3600 + off_m * 60) * 1000
    return total


def fmt_ms(ms):
    """Render epoch milliseconds as ISO-8601 UTC with exactly three fractional digits."""
    if ms is None:
        return None
    secs, millis = divmod(int(ms), 1000)
    dt = EPOCH + timedelta(seconds=secs)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, millis,
    )


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date string, or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def date_of_ms(ms):
    """The UTC calendar date containing the given instant."""
    secs = int(ms) // 1000
    return (EPOCH + timedelta(seconds=secs)).date()


def quarter_of_date(d):
    """(year, quarter) for a calendar date."""
    return (d.year, (d.month - 1) // 3 + 1)


def quarter_of_ms(ms):
    return quarter_of_date(date_of_ms(ms))


def quarter_bounds(year, quarter):
    """Inclusive first and last calendar dates of a UTC calendar quarter."""
    first_month = 3 * (quarter - 1) + 1
    start = date(year, first_month, 1)
    if quarter == 4:
        end = date(year, 12, 31)
    else:
        end = date(year, first_month + 3, 1) - timedelta(days=1)
    return start, end


def days_in_quarter(year, quarter):
    start, end = quarter_bounds(year, quarter)
    return (end - start).days + 1


def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) over integers, exact."""
    numerator = int(numerator)
    denominator = int(denominator)
    if denominator == 0:
        raise ZeroDivisionError("denominator must be non-zero")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    # Half-up on a negative value rounds away from zero.
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def round_half_up_2dp(numerator, denominator):
    """round_half_up(numerator / denominator, 2) as a Decimal with two places."""
    q = Decimal(int(numerator)) / Decimal(int(denominator))
    return q.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def dec2(value):
    """Normalise a numeric input to a two-place Decimal."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def as_number(value):
    """JSON-friendly rendering of a Decimal quantity."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
