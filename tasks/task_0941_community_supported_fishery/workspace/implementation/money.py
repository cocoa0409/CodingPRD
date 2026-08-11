"""Pound and cent arithmetic (PRD 2.6).

Pounds are two-decimal Decimals partitioned by exact subtraction.  Cents are
integers derived by round-half-up.  No float ever touches either quantity.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, ROUND_CEILING
from fractions import Fraction

CENT = Decimal("1")
LB = Decimal("0.01")


def round_half_up(value):
    """Round a Decimal/Fraction to a whole number of cents, half away from zero."""
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    return int(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def trunc_lb(value):
    """Truncate downward to two decimal places (0.01 lb)."""
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    return Decimal(value).quantize(LB, rounding=ROUND_DOWN)


def lb(value):
    """Normalise a pound quantity to exactly two decimal places."""
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    return Decimal(value).quantize(LB)


def ceil_int(value):
    """Round a Decimal up to the next whole number."""
    return int(Decimal(value).quantize(CENT, rounding=ROUND_CEILING))


def to_number(value):
    """Serialise a Decimal pound/temperature quantity as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
