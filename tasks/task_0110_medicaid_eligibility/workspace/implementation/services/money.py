"""Decimal/round-half-up precision helpers (PRD §2.6)."""

from decimal import Decimal, ROUND_HALF_UP


_TWO_PLACES = Decimal("0.01")


def to_decimal(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def round2(v) -> Decimal:
    """Round half-up to 2 decimal places, returns Decimal."""
    return to_decimal(v).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def round2_float(v) -> float:
    """Round half-up to 2 decimals, return float for JSON serialization."""
    return float(round2(v))
