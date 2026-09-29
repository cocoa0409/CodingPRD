"""Numeric, temporal and formatting helpers.

Every monetary, ratio and height quantity in this service is carried as
decimal.Decimal and rounded half-up, never as a float (PRD 2.6).
"""
import calendar
import datetime as _dt
import math
import random
import string
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

UTC = _dt.timezone.utc

D0 = Decimal("0")
D1 = Decimal("1")


# --------------------------------------------------------------------------
# decimal helpers
# --------------------------------------------------------------------------
def dec(value):
    """Coerce int / str / Decimal into Decimal without going through float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    if places < 0:
        q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half-up to a whole number, returned as int."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def ceil_to_step(value, step):
    """Round *value* up to the next whole multiple of *step*."""
    v = dec(value)
    s = dec(step)
    steps = (v / s).quantize(Decimal(1), rounding=ROUND_CEILING)
    return (steps * s).normalize() + D0


def ceil_steps(value, step):
    """Number of whole *step* units needed to cover *value* (rounded up)."""
    v = dec(value)
    s = dec(step)
    return int((v / s).quantize(Decimal(1), rounding=ROUND_CEILING))


def decimal_places(value):
    """Number of significant decimal places carried by a parsed JSON number."""
    d = dec(value)
    if d == d.to_integral_value():
        return 0
    d = d.normalize()
    exp = d.as_tuple().exponent
    return max(0, -int(exp))


def q1(value):
    return round_half_up(value, 1)


def q3(value):
    return round_half_up(value, 3)


# --------------------------------------------------------------------------
# temporal helpers
# --------------------------------------------------------------------------
TS_FORMAT_LEN = 3


def format_ts(value):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    v = value
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    v = v.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond // 1000,
    )


def format_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def parse_ts(text):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(text):
    """Parse a strict YYYY-MM-DD calendar date, or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return None
    try:
        return _dt.date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        return None


def add_days(value, days):
    return value + _dt.timedelta(days=int(days))


def add_years(base_date, years):
    """Calendar-year arithmetic with a day clamp for 29 February."""
    year = base_date.year + int(years)
    month = base_date.month
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return _dt.date(year, month, day)


def start_of_day(value):
    return _dt.datetime(value.year, value.month, value.day, tzinfo=UTC)


def whole_days_between(start, end):
    """Whole elapsed days from *start* to *end*, truncated downward."""
    delta = end - start
    return math.floor(delta.total_seconds() / 86400.0)


def whole_minutes_between(start, end):
    delta = end - start
    if delta.total_seconds() <= 0:
        return 0
    return math.floor(delta.total_seconds() / 60.0)


# --------------------------------------------------------------------------
# identifiers
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def jsonable(value):
    """Recursively convert Decimal / datetime / date into JSON primitives."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value() and value.as_tuple().exponent >= 0:
            return int(value)
        return float(value)
    if isinstance(value, _dt.datetime):
        return format_ts(value)
    if isinstance(value, _dt.date):
        return format_date(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value
