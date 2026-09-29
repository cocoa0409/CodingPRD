"""Monetary precision and rounding (PRD 2.5).

All amounts are integers denominated in whole cents. Every product of a money
value and a percentage or contract multiplier is rounded half up -- a fractional
part of exactly one half rounds away from zero.
"""

from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    """Exact Decimal for a JSON number, never a binary float."""
    return Decimal(str(value))


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def multiply_cents(cents, factor):
    """cents * factor rounded half up to whole cents."""
    return round_half_up(dec(cents) * dec(factor))
