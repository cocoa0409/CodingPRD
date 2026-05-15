"""Monetary precision helpers — round_half_up to integer cents or to N decimal places."""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(value) -> int:
    """Round a numeric value (int/float/Decimal) to integer cents using round-half-up."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    rounded = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded)


def round_half_up_decimal(value, places: int) -> Decimal:
    """Round to N decimal places using round-half-up; return Decimal."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    quantum = Decimal(10) ** -places
    return d.quantize(quantum, rounding=ROUND_HALF_UP)


def round_half_up_float(value, places: int) -> float:
    """Round to N decimal places using round-half-up; return float."""
    return float(round_half_up_decimal(value, places))
