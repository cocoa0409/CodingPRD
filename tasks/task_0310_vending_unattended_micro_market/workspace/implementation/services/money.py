"""Monetary rounding: round-half-up to whole cents (PRD 2.7)."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric value to the nearest integer, halves rounding up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
