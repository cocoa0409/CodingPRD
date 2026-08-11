"""Monetary arithmetic.  PRD 2.6: every monetary field is an integer number of
cents and every non-integer intermediate is converted with round half up (ties
away from zero).  Decimal only - never float - for anything that becomes money.
"""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal(0)


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal to whole cents, halves away from zero."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    """The single non-monetary rounded quantity: balance_spread_pct."""
    q = D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def floor_div_int(numerator, denominator):
    """Integer floor division on Decimals that are known to be whole cents."""
    return int(D(numerator) // D(denominator))
