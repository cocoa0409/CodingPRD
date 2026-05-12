"""Money arithmetic: integer cents with ROUND_HALF_UP."""
from decimal import Decimal, ROUND_HALF_UP


def D(x) -> Decimal:
    """Convert anything to Decimal safely (via str of floats)."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round_half_up(value) -> int:
    """Round value to integer using ROUND_HALF_UP."""
    d = D(value) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
