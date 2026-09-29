"""Exact arithmetic helpers.

PRD 2.6: every rounding in this specification uses round-half-up (a value exactly
at the midpoint rounds away from zero).  Never float, never banker's rounding.
Rational intermediates (room-type inventory shares, credits-per-shift) are carried
as `fractions.Fraction` so that "exact rational, never rounded here" is literal.
"""

from decimal import Decimal
from fractions import Fraction


QUARTER_CREDIT = Decimal("0.25")
MAX_SINGLE_ROOM_CREDITS = Decimal("3.00")
LINEN_REFRESH_CREDITS = Decimal("0.25")
RECLEAN_CREDIT_FACTOR = Decimal("0.60")
RESTRICTED_DUTY_FACTOR = Decimal("0.75")
WAIVER_HEADROOM_FACTOR_DEFAULT = Decimal("1.25")
WAIVER_HEADROOM_FACTOR_STRICT = Decimal("1.00")


def to_frac(value):
    """Convert any numeric input to an exact Fraction."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(Decimal(repr(value)))
    raise TypeError("unsupported numeric type %r" % type(value))


def round_half_up(value, places):
    """Round-half-up to `places` decimals, away from zero at the midpoint."""
    f = to_frac(value)
    scale = 10 ** places
    n = f * scale
    num, den = n.numerator, n.denominator
    if num >= 0:
        q = (2 * num + den) // (2 * den)
    else:
        q = -((-2 * num + den) // (2 * den))
    return Decimal(q).scaleb(-places)


def dec2(value):
    return round_half_up(value, 2)


def dec1(value):
    return round_half_up(value, 1)


def dec4(value):
    return round_half_up(value, 4)


def dec0(value):
    """Round half up to a whole number, returned as int."""
    return int(round_half_up(value, 0))


def ceil_exact(value):
    """Ceiling applied to the exact rational, never to a pre-rounded quotient."""
    f = to_frac(value)
    return -((-f.numerator) // f.denominator)


def floor_exact(value):
    f = to_frac(value)
    return f.numerator // f.denominator


def trunc_toward_zero(value):
    """Whole units truncated toward zero (PRD 2.6 duration derivations)."""
    f = to_frac(value)
    if f >= 0:
        return f.numerator // f.denominator
    return -((-f.numerator) // f.denominator)


def snap_quarter_credits(raw):
    """PRD 3.4: divide by 0.25, round the quarters half up, multiply back,
    then apply the floor clamp before the ceiling clamp."""
    quarters = round_half_up(to_frac(raw) / to_frac(QUARTER_CREDIT), 0)
    snapped = (Decimal(quarters) * QUARTER_CREDIT).quantize(Decimal("0.01"))
    if snapped < QUARTER_CREDIT:
        snapped = QUARTER_CREDIT
    if snapped > MAX_SINGLE_ROOM_CREDITS:
        snapped = MAX_SINGLE_ROOM_CREDITS
    return snapped.quantize(Decimal("0.01"))


def jsonnum(value):
    """Render a stored Decimal for the JSON payload."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Fraction):
        return float(value)
    return value
