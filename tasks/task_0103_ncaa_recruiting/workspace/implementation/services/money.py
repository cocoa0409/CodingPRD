"""Rounding helpers (half-up)."""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up_int(value) -> int:
    """Round to nearest integer, half-up."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_two_dp(value) -> float:
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def is_two_decimal_places(value) -> bool:
    """Check whether a number is expressible as a fraction with two decimal places."""
    try:
        d = Decimal(str(value))
    except Exception:
        return False
    # Convert to quantized; compare.
    quantized = d.quantize(Decimal("0.01"))
    return d == quantized
