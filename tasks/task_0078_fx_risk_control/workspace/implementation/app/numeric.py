"""Decimal helpers — never use float for money."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Union

Number = Union[int, float, str, Decimal]

TWO_DP = Decimal("0.01")
SIX_DP = Decimal("0.000001")
ZERO = Decimal("0")


def to_decimal(value: Any) -> Decimal:
    """Convert anything numeric-shaped into a Decimal, going through str
    so we never inherit float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # bool is a subclass of int; reject it as a numeric input.
        raise TypeError("boolean is not a numeric value")
    if isinstance(value, (int,)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value.strip())
    raise TypeError(f"cannot coerce {type(value).__name__} to Decimal")


def round_half_up(value: Number, decimals: int = 2) -> Decimal:
    quant = Decimal(10) ** -decimals
    return to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def fmt_money(value: Number, decimals: int = 2) -> float:
    """Render a decimal money value as a float for JSON, after quantising.

    Tests compare with `==` against numeric literals, so we must return
    a numeric type rather than a string.  Quantising before the float
    conversion guarantees the trailing-precision rounding is locked
    in even though float carries it loosely.
    """
    return float(round_half_up(value, decimals))


def fmt_rate(value: Number) -> float:
    return float(round_half_up(value, 6))
