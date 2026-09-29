"""Shared low-level helpers: ids, ISO-8601 handling, exact rounding."""
import math
import random
import string
import uuid
from datetime import datetime, timezone
from fractions import Fraction

ALNUM = string.ascii_uppercase + string.digits


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def parse_iso(value):
    """Parse an ISO-8601 instant into a tz-aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # Instant comparisons are made at millisecond resolution (PRD 2.8).
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def real_now_iso():
    return fmt_dt(datetime.now(timezone.utc))


def round_half_up(value):
    """Exact half-up rounding to an integer. `value` must be int/Fraction."""
    f = Fraction(value)
    if f >= 0:
        return int(math.floor(f + Fraction(1, 2)))
    return int(-math.floor(-f + Fraction(1, 2)))


def frac(numer, denom=1):
    return Fraction(numer, denom)
