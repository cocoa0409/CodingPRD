"""Monetary precision helpers (PRD §2.8). Integer cents, round half up."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(value):
    """Round a Decimal/number value half up to the nearest whole cent (int)."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
