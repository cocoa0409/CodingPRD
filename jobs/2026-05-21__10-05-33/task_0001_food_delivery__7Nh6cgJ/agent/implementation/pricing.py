"""Commission and delivery-fee computations."""

from __future__ import annotations

import math
from decimal import Decimal

from money import round_half_up_to_cent


def tiered_commission_cents(subtotal_cents: int) -> int:
    """15% / 18% / 22% marginal tiers, summed in Decimal, half-up to cent at the end."""
    s = int(subtotal_cents)
    tier1 = min(s, 20_000)
    tier2 = max(0, min(s, 50_000) - 20_000)
    tier3 = max(0, s - 50_000)
    total = (Decimal(tier1) * Decimal("0.15")
             + Decimal(tier2) * Decimal("0.18")
             + Decimal(tier3) * Decimal("0.22"))
    return round_half_up_to_cent(total)


def flat_commission_cents(subtotal_cents: int, rate: float) -> int:
    total = Decimal(int(subtotal_cents)) * Decimal(str(rate))
    return round_half_up_to_cent(total)


def solo_delivery_fee_cents(distance_km: float, is_peak: bool) -> int:
    bands = math.ceil(distance_km) if distance_km > 0 else 0
    peak = 200 if is_peak else 0
    return 300 + 120 * bands + peak


def merged_delivery_fee_cents(solo_fee_cents: int) -> int:
    discount = math.floor(solo_fee_cents * 0.25)
    return solo_fee_cents - discount
