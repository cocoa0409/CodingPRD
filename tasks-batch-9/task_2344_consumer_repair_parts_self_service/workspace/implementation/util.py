"""Shared low-level helpers: ids, timestamps, exact arithmetic."""
import calendar
import math
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from fractions import Fraction

UTC = timezone.utc

# The logical clock starts here on every fresh boot (PRD 2.5).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def new_token(prefix="PT"):
    return prefix + "-" + "".join(random.choice(_ALNUM) for _ in range(16))


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_ts(value):
    """Parse an ISO 8601 timestamp (or plain date) into an aware UTC datetime.

    Raises ValueError when the value is not parseable.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # Tolerate a space separator between date and time.
        try:
            dt = datetime.fromisoformat(text.replace(" ", "T", 1))
        except ValueError:
            raise ValueError("bad timestamp: %r" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def end_of_day(dt):
    """The inclusive last instant of dt's calendar day: 23:59:59.999Z."""
    return dt.replace(hour=23, minute=59, second=59, microsecond=999000)


def add_years(dt, years):
    """Add whole calendar years, clamping Feb 29 down to Feb 28."""
    year = dt.year + int(years)
    month = dt.month
    day = dt.day
    last = calendar.monthrange(year, month)[1]
    if day > last:
        day = last
    return dt.replace(year=year, month=month, day=day)


def whole_months_between(start, end):
    """Number of complete calendar months from start to end (0 when end <= start)."""
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    elif end.day == start.day:
        if (end.hour, end.minute, end.second, end.microsecond) < (
            start.hour, start.minute, start.second, start.microsecond
        ):
            months -= 1
    return max(0, months)


def whole_days_between(start, end):
    """Number of complete days from start to end (0 when end <= start)."""
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 86400)


# --------------------------------------------------------------------------
# exact arithmetic
# --------------------------------------------------------------------------

def frac(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def round_half_up(value):
    """Round an exact rational to the nearest integer, halves away from zero."""
    f = frac(value)
    num, den = f.numerator, f.denominator
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def round_half_up_places(value, places):
    """Round an exact rational to `places` decimals, halves away from zero.

    Returns a float suited to JSON serialisation.
    """
    scale = 10 ** places
    scaled = round_half_up(frac(value) * scale)
    return scaled / scale


def ceil_frac(value):
    return math.ceil(frac(value))


def as_number(value):
    """Serialise an exact rational as a JSON number without float noise."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    f = frac(value)
    if f.denominator == 1:
        return int(f)
    return round_half_up_places(f, 6)


def days(n):
    return timedelta(days=n)
