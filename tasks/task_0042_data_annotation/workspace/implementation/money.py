"""Decimal-based money helpers — round-half-up everywhere."""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value) -> int:
    """Round any number to nearest integer cents, half-up."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value) -> float:
    """Round to four decimal places, half-up; returned as float."""
    d = Decimal(str(value))
    quantized = d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(quantized)
