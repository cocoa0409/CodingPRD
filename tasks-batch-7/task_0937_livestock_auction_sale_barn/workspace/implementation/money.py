"""Decimal money / weight discipline (PRD 2.5).

Monetary amounts: two decimal places, ROUND_HALF_UP.
Derived weights:  whole pounds, ROUND_HALF_UP.
Average weight:   one decimal place, ROUND_HALF_UP.
Never float arithmetic.
"""
from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")
ONE = Decimal("0.1")
ZERO_DP = Decimal("1")


def D(value):
    """Coerce anything JSON-ish into an exact Decimal."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q2(value):
    """Money: 2 dp, round half up."""
    if value is None:
        return None
    return D(value).quantize(TWO, rounding=ROUND_HALF_UP)


def q1(value):
    """Average weight: 1 dp, round half up."""
    if value is None:
        return None
    return D(value).quantize(ONE, rounding=ROUND_HALF_UP)


def q0(value):
    """Derived weight: whole pounds, round half up."""
    if value is None:
        return None
    return D(value).quantize(ZERO_DP, rounding=ROUND_HALF_UP)


def money_out(value):
    """Render a Decimal money value into JSON."""
    if value is None:
        return None
    return float(q2(value))


def num_out(value):
    """Render a Decimal numeric value into JSON without re-quantizing."""
    if value is None:
        return None
    return float(D(value))
