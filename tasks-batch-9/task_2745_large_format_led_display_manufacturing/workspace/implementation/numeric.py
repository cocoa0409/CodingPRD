"""Exact arithmetic helpers.

Every rounding operation in this system is ROUND HALF UP: a value exactly at
the midpoint rounds away from zero (PRD 2.5).  All intermediate arithmetic is
carried out on Fraction values so that no binary floating point error can move
a value across a boundary.
"""
import math
from decimal import Decimal
from fractions import Fraction


def to_fraction(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(value)
    raise TypeError("unsupported numeric type: %r" % (type(value),))


def round_half_up(value, places=0):
    """Round half away from zero to `places` decimals, returning a Decimal."""
    frac = to_fraction(value)
    scaled = frac * (10 ** places)
    if scaled >= 0:
        integral = math.floor(scaled + Fraction(1, 2))
    else:
        integral = -math.floor(-scaled + Fraction(1, 2))
    if places == 0:
        return Decimal(integral)
    return Decimal(integral).scaleb(-places)


def round_half_up_int(value):
    return int(round_half_up(value, 0))


def ceil_frac(value):
    return math.ceil(to_fraction(value))


def floor_frac(value):
    return math.floor(to_fraction(value))


def decimal_places(value):
    """Number of decimal places a JSON-supplied number carries."""
    if isinstance(value, int):
        return 0
    if isinstance(value, Decimal):
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int):
            return 0
        return max(0, -exponent)
    return 0


def is_integral(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, Decimal):
        try:
            return value == value.to_integral_value()
        except Exception:
            return False
    return False
