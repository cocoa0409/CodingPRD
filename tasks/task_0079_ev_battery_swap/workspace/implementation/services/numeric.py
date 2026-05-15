"""Half-up rounding helpers using Decimal."""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value, places: int = 0) -> Decimal:
    """Round a float/int/Decimal half-up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantizer = Decimal("1") if places == 0 else Decimal("1." + ("0" * places))
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)


def round_half_up_cents(value) -> int:
    return int(round_half_up(value, 0))


def round_half_up_float(value, places: int) -> float:
    return float(round_half_up(value, places))


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
