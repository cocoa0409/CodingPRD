"""Decimal arithmetic helpers.

PRD 2.5: all monetary amounts are decimal quantities carried to 2 decimal
places and every rounding uses round-half-up. Intermediate factors are held
unrounded; rounding is applied to the money coming out of a formula.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 40

TWO = Decimal("0.01")
ZERO = Decimal("0.00")


def dec(value):
    """Coerce a JSON number (int/float) or string into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q2(value):
    """Round half-up to 2 decimal places."""
    return dec(value).quantize(TWO, rounding=ROUND_HALF_UP)


def floor_div(numerator, denominator):
    """Whole-block count: the quotient discarding any remainder."""
    return int(dec(numerator) // dec(denominator))
