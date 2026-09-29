"""Shared low-level helpers: instant parsing/formatting and exact arithmetic."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
import math
import uuid


# --------------------------------------------------------------------------
# identifiers
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# instants
# --------------------------------------------------------------------------

def parse_instant(value):
    """Parse an ISO-8601 string into an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_instant(dt):
    """Canonical ISO-8601 UTC rendering; millisecond digits only when non-zero."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_stamp(dt):
    """ISO-8601 UTC with exactly three fractional digits (created_at/updated_at)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def minutes_between(start, end):
    """Signed minutes from start to end as an exact Fraction of minutes."""
    return Fraction((end - start).total_seconds()).limit_denominator(10 ** 9) / 60


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=float(minutes))


def floor_div_minutes(minutes, per):
    return int(math.floor(float(minutes) / per))


# --------------------------------------------------------------------------
# exact arithmetic
# --------------------------------------------------------------------------

def round_half_up(value):
    """Round a Decimal/Fraction/int to the nearest integer, halves away from zero."""
    if isinstance(value, Fraction):
        num, den = value.numerator, value.denominator
        if num >= 0:
            return (2 * num + den) // (2 * den)
        return -((-2 * num + den) // (2 * den))
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount, bps):
    """round_half_up(amount * bps / 10000) in exact decimal arithmetic."""
    return round_half_up(Decimal(int(amount)) * Decimal(int(bps)) / Decimal(10000))


def ratio_bps(numerator, denominator):
    """round_half_up(numerator / denominator * 10000); 0 when denominator is 0."""
    if not denominator:
        return 0
    return round_half_up(Decimal(int(numerator)) * Decimal(10000) / Decimal(int(denominator)))
