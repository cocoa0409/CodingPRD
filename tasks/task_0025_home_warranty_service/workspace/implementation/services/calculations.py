"""Calculation rules (scaffold §1.3, PRD §3.7 / §3.8).

All monetary math is done in Decimal at integer-cent granularity with
ROUND_HALF_UP. We never use float arithmetic for money.

Note: ContractPackage.copay_share_pct arrives as a JSON number (float),
but we convert via str(Decimal(...)) to avoid IEEE-754 noise before the
multiplication.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


# Renewal-premium constants (scaffold §1.3 renewal_premium)
EARLY_RENEWAL_DAYS_THRESHOLD = 14  # Boundary: D >= 15 qualifies, D <= 14 does not.
EARLY_RENEWAL_DISCOUNT_PCT = Decimal("0.10")
ITEM_SURCHARGE_PCT_PER_ITEM = Decimal("0.02")


def _round_half_up(d: Decimal) -> int:
    """Round a Decimal to the nearest integer using ROUND_HALF_UP."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _as_decimal_pct(pct) -> Decimal:
    """Convert a percentage value (JSON number or Decimal) to a Decimal.

    Uses str() round-trip to avoid float noise (e.g., 0.1 -> '0.1').
    """
    if isinstance(pct, Decimal):
        return pct
    return Decimal(str(pct))


# --- §1.3 provisional_copay --------------------------------------------------


def compute_provisional_copay_cents(
    *, repair_cost_cents: int, copay_cap_cents: int,
    copay_share_pct, service_fee_cents: int
) -> int:
    """Computed at SUBMITTED -> ASSESSED.

    excess = max(0, R - C)
    copay_above_cap = round_half_up(excess * P)
    provisional = copay_above_cap + service_fee_cents
    """
    excess = max(0, repair_cost_cents - copay_cap_cents)
    if excess == 0:
        copay_above_cap = 0
    else:
        copay_above_cap = _round_half_up(Decimal(excess) * _as_decimal_pct(copay_share_pct))
    return copay_above_cap + int(service_fee_cents)


# --- §1.3 final_copay --------------------------------------------------------


def compute_final_copay_cents(
    *, repair_cost_cents: int, copay_cap_cents: int,
    copay_share_pct, service_fee_charged_cents: int
) -> int:
    """Computed at DISPATCHED -> RESOLVED.

    SF is pinned at DISPATCHED (0 when is_return_visit, else package SF).
    """
    excess = max(0, repair_cost_cents - copay_cap_cents)
    if excess == 0:
        copay_above_cap = 0
    else:
        copay_above_cap = _round_half_up(Decimal(excess) * _as_decimal_pct(copay_share_pct))
    return copay_above_cap + int(service_fee_charged_cents)


# --- §1.3 is_return_visit ----------------------------------------------------


def is_return_visit(
    *, last_dispatch_completed_utc: Optional[str], window_days: int, clock_now_iso: str
) -> bool:
    """Strict comparison: T < L + W*86400 → true; T == L + W*86400 → false."""
    if last_dispatch_completed_utc is None:
        return False
    import db  # local import; db is a pure module
    L = db.parse_iso_dt(last_dispatch_completed_utc)
    T = db.parse_iso_dt(clock_now_iso)
    assert L is not None and T is not None
    delta_seconds = (T - L).total_seconds()
    # Compare at 1-second granularity using <= test on integer seconds.
    return delta_seconds < window_days * 86400


# --- §1.3 renewal_premium ----------------------------------------------------


def compute_renewal_premium_cents(
    *, annual_premium_cents: int, days_remaining: int, covered_item_count: int
) -> int:
    """Pricing tiers on D:
      D >= 15 → base = P - round_half_up(P * 0.10)        (early renewal)
      D <= 14 → base = P                                   (at expiry)

    Surcharge (mode (b) — rounding order pinned):
      extra_items = max(0, N_items - 1)
      per_item_cents = round_half_up(P * 0.02)
      surcharge_total = per_item_cents * extra_items
    """
    P = Decimal(annual_premium_cents)
    if days_remaining >= 15:
        discount_cents = _round_half_up(P * EARLY_RENEWAL_DISCOUNT_PCT)
        base_after_discount = annual_premium_cents - discount_cents
    else:
        base_after_discount = annual_premium_cents

    extra_items = max(0, covered_item_count - 1)
    per_item_cents = _round_half_up(P * ITEM_SURCHARGE_PCT_PER_ITEM)
    surcharge_total = per_item_cents * extra_items

    return base_after_discount + surcharge_total
