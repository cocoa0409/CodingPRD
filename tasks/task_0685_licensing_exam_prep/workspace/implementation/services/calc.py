"""Calculation primitives (scaffold §1.3, PRD §2.8, §3.x).

All money is integer cents; all scores/counts integers. round_half_up is used
wherever a non-integer intermediate must become an integer (PRD §2.8).
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round half away from zero to nearest integer. PRD §2.8: a fractional part
    of exactly one-half rounds away from zero to the next whole unit."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) with exact rational arithmetic."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
