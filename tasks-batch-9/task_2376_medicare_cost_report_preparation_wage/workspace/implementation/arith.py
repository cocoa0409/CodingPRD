"""Exact rational arithmetic with pinned rounding (PRD 2.9).

Every ratio/percentage/weight is evaluated as an exact Fraction and only then
rounded, half up (ties away from zero), or floored where the text says floored.
"""

from decimal import Decimal
from fractions import Fraction


def F(value):
    """Exact Fraction of an int / float / Decimal / Fraction / numeric string."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Decimal):
        return Fraction(value)
    return Fraction(str(value))


def rhu_int(value):
    """Round half up to a whole unit; ties go away from zero."""
    frac = F(value)
    num, den = frac.numerator, frac.denominator
    negative = num < 0
    if negative:
        num = -num
    whole, rest = divmod(num, den)
    if rest * 2 >= den:
        whole += 1
    return -whole if negative else whole


def rhu(value, places):
    """Round half up to `places` decimals, returned as a fixed-scale Decimal."""
    scaled = F(value) * (10 ** places)
    whole = rhu_int(scaled)
    quantum = Decimal(1).scaleb(-places)
    return (Decimal(whole) * quantum).quantize(quantum)


def floor_int(value):
    """Floor toward negative infinity."""
    frac = F(value)
    return frac.numerator // frac.denominator


def dec(value, places):
    """Coerce to a fixed-scale Decimal without re-rounding beyond `places`."""
    return rhu(value, places)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def places_of(value):
    exponent = Decimal(str(value)).as_tuple().exponent
    return -exponent if exponent < 0 else 0
