"""Fee, commission, and fine formulas."""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal


_BASE_FEE_CENTS = 300
_PER_BAND_CENTS = 120
_PEAK_SURCHARGE_CENTS = 200


def delivery_fee(distance_km: float, is_peak: bool) -> int:
    """Solo-rider delivery fee, integer cents."""
    bands = math.ceil(distance_km) if distance_km > 0 else 0
    fee = _BASE_FEE_CENTS + bands * _PER_BAND_CENTS
    if is_peak:
        fee += _PEAK_SURCHARGE_CENTS
    return fee


def merge_discount(solo_fee_cents: int) -> int:
    """25% discount, floor-rounded to whole cent."""
    return int(math.floor(solo_fee_cents * 0.25))


def tiered_commission(subtotal_cents: int) -> int:
    """Marginal-tiered commission, half-up rounded once at the end."""
    tier1 = min(subtotal_cents, 20_000)
    tier2 = max(0, min(subtotal_cents, 50_000) - 20_000)
    tier3 = max(0, subtotal_cents - 50_000)
    total = (
        Decimal(tier1) * Decimal("0.15")
        + Decimal(tier2) * Decimal("0.18")
        + Decimal(tier3) * Decimal("0.22")
    )
    rounded = total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded)


def flat_commission(subtotal_cents: int, rate: float) -> int:
    """Flat-rate override commission, half-up rounded."""
    rounded = (Decimal(subtotal_cents) * Decimal(str(rate))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(rounded)


def late_fine(minutes_late: int, final_delivery_fee_cents: int) -> int:
    """Late-delivery fine tiers — returns 0 if minutes_late <= 0."""
    if minutes_late <= 0:
        return 0
    if 1 <= minutes_late <= 10:
        return 200
    if 11 <= minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    # > 30
    return min(final_delivery_fee_cents, 1500) + 500
