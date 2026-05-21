"""Fiscal computation: delivery fees, commissions, fines."""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP


def solo_delivery_fee_cents(distance_km: float, is_peak: bool) -> int:
    """Solo-rider delivery fee per PRD §3.4."""
    base = 300
    bands = math.ceil(distance_km)
    if bands < 0:
        bands = 0
    per_km = 120 * bands
    peak = 200 if is_peak else 0
    return base + per_km + peak


def compute_provisional_delivery_fee(distance_km: float, is_peak: bool) -> int:
    return solo_delivery_fee_cents(distance_km, is_peak)


def merge_discount_cents(solo_fee_cents: int) -> int:
    """25% route-merge discount, floor-rounded to whole cents."""
    return int(math.floor(solo_fee_cents * Decimal("0.25")))


def final_delivery_fee_cents(distance_km: float, is_peak: bool, merged: bool) -> int:
    solo = solo_delivery_fee_cents(distance_km, is_peak)
    if not merged:
        return solo
    return solo - merge_discount_cents(solo)


def compute_tiered_commission(subtotal_cents: int) -> int:
    """Tiered platform commission with a single final half-up rounding step (PRD §3.4)."""
    t1_cap = 20_000
    t2_cap = 50_000
    t1 = min(subtotal_cents, t1_cap)
    t2 = max(0, min(subtotal_cents, t2_cap) - t1_cap)
    t3 = max(0, subtotal_cents - t2_cap)
    total = (
        Decimal(t1) * Decimal("0.15")
        + Decimal(t2) * Decimal("0.18")
        + Decimal(t3) * Decimal("0.22")
    )
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_provisional_commission(subtotal_cents: int) -> int:
    return compute_tiered_commission(subtotal_cents)


def compute_final_commission(subtotal_cents: int, override_rate) -> int:
    if override_rate is not None:
        amt = Decimal(subtotal_cents) * Decimal(str(override_rate))
        return int(amt.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return compute_tiered_commission(subtotal_cents)


def compute_late_fine_amount(minutes_late: int, final_delivery_fee_cents: int) -> int:
    """Tiered late-delivery fine per PRD §3.7."""
    if minutes_late <= 0:
        return 0
    if minutes_late <= 10:
        return 200
    if minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    # >30 minutes
    clawback = min(final_delivery_fee_cents, 1500)
    return clawback + 500


def compute_bonus_tier(on_time_rate: float, acceptance_rate: float, rating: float) -> str:
    """PRD §3.3: weighted sum 0.6*on_time + 0.3*acc + 0.1*(rating/5), rounded half-up to 3dp."""
    score_dec = (
        Decimal(str(on_time_rate)) * Decimal("0.6")
        + Decimal(str(acceptance_rate)) * Decimal("0.3")
        + (Decimal(str(rating)) / Decimal("5")) * Decimal("0.1")
    )
    score = score_dec.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if score >= Decimal("0.900"):
        return "PLATINUM"
    if score >= Decimal("0.800"):
        return "GOLD"
    if score >= Decimal("0.700"):
        return "SILVER"
    return "BRONZE"
