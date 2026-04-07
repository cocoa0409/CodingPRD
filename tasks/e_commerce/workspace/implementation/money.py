"""Monetary precision helpers. All money goes through round_money()."""

from decimal import Decimal, ROUND_HALF_UP

_TWO_PLACES = Decimal("0.01")


def round_money(value) -> float:
    """Round to 2 decimal places using half-up, return as float for JSON."""
    return float(Decimal(str(value)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))
