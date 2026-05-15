"""Numeric helpers: half-up rounding using Decimal."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value, places: int) -> float:
    """Round value to `places` decimal places using ROUND_HALF_UP.

    Returns a float. Empty/None input is treated as 0.
    """
    if value is None:
        return 0.0
    d = Decimal(str(value))
    quant = Decimal(10) ** -places
    return float(d.quantize(quant, rounding=ROUND_HALF_UP))


def decimal_value(value) -> Decimal:
    if value is None:
        return Decimal(0)
    return Decimal(str(value))
