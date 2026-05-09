"""Round-half-up helpers (no banker's rounding)."""
from decimal import ROUND_HALF_UP, Decimal


def round_half_up_int(value) -> int:
    """Round a numeric value to the nearest integer, half-up."""
    if isinstance(value, Decimal):
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_decimals(value, places: int) -> float:
    """Round to N decimal places with round-half-up; return float."""
    quant = Decimal("1").scaleb(-places) if places else Decimal("1")
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return float(d.quantize(quant, rounding=ROUND_HALF_UP))
