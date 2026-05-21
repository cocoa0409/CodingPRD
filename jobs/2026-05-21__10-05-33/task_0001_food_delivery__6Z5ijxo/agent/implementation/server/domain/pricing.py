import math
from decimal import Decimal
from ..money import round_half_up_cents


def solo_delivery_fee_cents(distance_km: float, is_peak: bool) -> int:
    bands = max(0, math.ceil(distance_km))
    base = 300
    per_band = 120 * bands
    peak = 200 if is_peak else 0
    return int(base + per_band + peak)


def route_merge_discount_cents(solo_fee_cents: int) -> int:
    return int(math.floor(solo_fee_cents * 0.25))


def tiered_commission_cents(subtotal_cents: int) -> int:
    """Marginal 15/18/22 tiered across 20k and 50k boundaries. Sum in decimal,
    round half-up once at the end."""
    tier1 = min(subtotal_cents, 20000)
    tier2 = max(0, min(subtotal_cents, 50000) - 20000)
    tier3 = max(0, subtotal_cents - 50000)
    total = (Decimal(tier1) * Decimal("0.15")
             + Decimal(tier2) * Decimal("0.18")
             + Decimal(tier3) * Decimal("0.22"))
    return round_half_up_cents(total)


def commission_cents(subtotal_cents: int, override_rate) -> int:
    if override_rate is None:
        return tiered_commission_cents(subtotal_cents)
    return round_half_up_cents(Decimal(subtotal_cents) * Decimal(str(override_rate)))


def late_fine_cents(minutes_late: int, final_delivery_fee_cents: int) -> int:
    if minutes_late <= 0:
        return 0
    if 1 <= minutes_late <= 10:
        return 200
    if 11 <= minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    # > 30
    earnings_clawback = min(final_delivery_fee_cents, 1500)
    return earnings_clawback + 500
