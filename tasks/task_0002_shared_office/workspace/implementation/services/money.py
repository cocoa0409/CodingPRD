"""Money / rounding helpers."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_to_int(value) -> int:
    """Round a numeric value (float/Decimal) to the nearest integer using half-up rounding."""
    if isinstance(value, int):
        return value
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
