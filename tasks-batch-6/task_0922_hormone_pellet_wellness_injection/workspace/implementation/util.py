"""Timekeeping, datetime rendering and rounding discipline (PRD 2.4 and 2.6)."""
import math
import re
import uuid
import random
import string
from datetime import datetime, timedelta, timezone
from fractions import Fraction

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


class DatetimeParseError(ValueError):
    pass


def parse_dt(value):
    """Parse an ISO 8601 instant.  Fractional digits are optional on input."""
    if not isinstance(value, str):
        raise DatetimeParseError("not a string")
    m = _ISO_RE.match(value.strip())
    if not m:
        raise DatetimeParseError("malformed datetime")
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    off = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError as exc:
        raise DatetimeParseError(str(exc))
    if off in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if off[0] == "+" else -1
    body = off[1:].replace(":", "")
    delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * delta).replace(tzinfo=timezone.utc)


def fmt_dt(dt):
    """Render an instant as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def days_between(a, b):
    """Whole 24-hour periods from a to b, floored (PRD 2.4)."""
    return math.floor((b - a).total_seconds() / 86400)


def hours_between(a, b):
    """Exact, unfloored hours from a to b (PRD 2.4)."""
    return (b - a).total_seconds() / 3600.0


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def frac(value):
    """Exact Fraction from an int / float / Decimal-ish input."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def round_half_up(value):
    """Round a non-negative exact rational half up to a whole unit."""
    f = frac(value)
    if f < 0:
        # Round half up applied to a non-negative magnitude, then re-signed.
        return -round_half_up(-f)
    return (2 * f.numerator + f.denominator) // (2 * f.denominator)


def ceil_div_frac(value):
    f = frac(value)
    return -((-f.numerator) // f.denominator)


def floor_frac(value):
    f = frac(value)
    return f.numerator // f.denominator


def numout(value):
    """Render an exact rational as an int when integral, else as a float."""
    f = frac(value)
    if f.denominator == 1:
        return int(f)
    return float(f)


def new_id():
    return str(uuid.uuid4())


_REQ_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))
