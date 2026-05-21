"""Pure pricing functions: delivery fees, commissions, fines."""
from __future__ import annotations

import decimal
import math
from decimal import Decimal


def _round_half_up(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=decimal.ROUND_HALF_UP))


def delivery_fee_solo_cents(distance_km: float, is_peak: bool) -> int:
    """Base 300 + 120 per ceil(distance_km) band + 200 if peak."""
    bands = math.ceil(distance_km)
    if bands < 0:
        bands = 0
    fee = 300 + 120 * bands + (200 if is_peak else 0)
    return fee


def merge_discount_cents(solo_fee_cents: int) -> int:
    """Route-merge discount: floor of 25% of solo fee."""
    return int(math.floor(solo_fee_cents * 0.25))


def commission_tiered_cents(subtotal_cents: int) -> int:
    """15% / 18% / 22% marginal tiers with caps at 20000 and 50000; single half-up rounding."""
    tier1 = min(subtotal_cents, 20000)
    tier2 = max(0, min(subtotal_cents, 50000) - 20000)
    tier3 = max(0, subtotal_cents - 50000)
    total = (
        Decimal(tier1) * Decimal("0.15")
        + Decimal(tier2) * Decimal("0.18")
        + Decimal(tier3) * Decimal("0.22")
    )
    return _round_half_up(total)


def commission_flat_cents(subtotal_cents: int, rate: float) -> int:
    """Flat rate commission, half-up."""
    return _round_half_up(Decimal(subtotal_cents) * Decimal(str(rate)))


def late_fine_cents(minutes_late: int, final_delivery_fee_cents: int) -> int:
    """Tiered late delivery fine."""
    if minutes_late <= 0:
        return 0
    if 1 <= minutes_late <= 10:
        return 200
    if 11 <= minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    # > 30
    clawback = min(final_delivery_fee_cents, 1500)
    return clawback + 500
