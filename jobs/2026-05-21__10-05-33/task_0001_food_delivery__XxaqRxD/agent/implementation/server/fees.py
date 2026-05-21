"""Fiscal computations: delivery fee, commission, fines."""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

from .clock import parse_iso


PEAK_WINDOWS = ((11, 13), (18, 20))  # [start, end) in hours UTC


def is_peak_at(dt) -> bool:
    """The PRD specifies '11:00 through 13:00 UTC' and '18:00 through 20:00 UTC' —
    we interpret these as inclusive of the start and exclusive of the end."""
    hour = dt.hour + dt.minute / 60 + dt.second / 3600 + dt.microsecond / 3.6e9
    for start, end in PEAK_WINDOWS:
        if start <= hour < end:
            return True
    return False


def solo_delivery_fee_cents(distance_km: float, is_peak: bool) -> int:
    """base 300 + 120/band + 200 peak surcharge."""
    bands = math.ceil(distance_km)
    if bands < 0:
        bands = 0
    fee = 300 + 120 * bands + (200 if is_peak else 0)
    return int(fee)


def final_delivery_fee_for_assignment(solo_fee: int, group_size: int) -> tuple[int, int]:
    """Returns (final_fee_cents, discount_cents_absorbed_by_platform).

    Group_size is the number of assignments in the route group containing this
    assignment. Solo deliveries (no group, or group of one) get no discount.
    """
    if group_size < 2:
        return solo_fee, 0
    discount = math.floor(solo_fee * 0.25)
    return solo_fee - discount, discount


def tiered_commission_cents(subtotal_cents: int) -> int:
    tier1 = min(subtotal_cents, 20_000)
    tier2 = max(0, min(subtotal_cents, 50_000) - 20_000)
    tier3 = max(0, subtotal_cents - 50_000)
    decimal_total = (
        Decimal(tier1) * Decimal("0.15")
        + Decimal(tier2) * Decimal("0.18")
        + Decimal(tier3) * Decimal("0.22")
    )
    return int(decimal_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def flat_commission_cents(subtotal_cents: int, rate: float) -> int:
    return int(
        (Decimal(subtotal_cents) * Decimal(str(rate))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def commission_cents(subtotal_cents: int, rate_override: float | None) -> int:
    if rate_override is None:
        return tiered_commission_cents(subtotal_cents)
    return flat_commission_cents(subtotal_cents, rate_override)


def late_fine_cents(minutes_late: int, final_delivery_fee_cents: int) -> int:
    """Tiered late-delivery fine per PRD §3.7."""
    if minutes_late <= 0:
        return 0
    if minutes_late <= 10:
        return 200
    if minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    # >30 minutes: clawback (min of final fee or 1500) plus 500 customer comp.
    clawback = min(final_delivery_fee_cents, 1500)
    return clawback + 500


def minutes_late(actual_iso: str, promised_iso: str) -> int:
    """Non-negative floor of (actual - promised) in minutes."""
    actual = parse_iso(actual_iso)
    promised = parse_iso(promised_iso)
    diff = (actual - promised).total_seconds()
    if diff <= 0:
        return 0
    return int(diff // 60)
