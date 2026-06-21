"""Calculation rules (SCAFFOLD §1.3 / PRD §3.8, §3.9, §3.12, §2.7).

All money is integer cents. Raw values are computed as floats then rounded to
whole cents with round-half-up. Decimal is used for the half-up rounding step
so the boundary (x.5 -> x+1) is exact regardless of float representation.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# Constants (SCAFFOLD §1.3 constants blocks).
DECLINING_RATE = 0.97
SHORT_RATE_PENALTY = 0.10
VALIDATION_WINDOW_DAYS = 90
AMOUNT_TOLERANCE_CENTS = 500
CLAIM_COOLDOWN_DAYS = 30
COVERAGE_FLOOR_CENTS = 0

TRANSFER_RATE_YEAR1 = 1500
TRANSFER_RATE_YEAR1_3 = 2500
TRANSFER_RATE_YEAR3_PLUS = 4000
CATEGORY_SURCHARGE_CENTS = 1000
TRANSFER_FEE_FLOOR_CENTS = 1000


def round_half_up(raw) -> int:
    """Round a numeric cents value to a whole integer cent, round-half-up."""
    return int(Decimal(str(raw)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def refund_proration_raw(base_cents: int, elapsed_months: int, lifespan_months: int,
                         depreciation_method: str) -> int:
    """Raw (rounded) depreciated refund payout, BEFORE the remaining-coverage cap.

    base = min(purchase_price_cents, msrp_cents)  -- caller supplies it.
    STRAIGHT_LINE:    base * max(0, L - elapsed)/L
    DECLINING_BALANCE: base * DECLINING_RATE ** elapsed
    Returns the value rounded to whole cents (cap is applied by the caller).
    """
    if depreciation_method == "STRAIGHT_LINE":
        L = lifespan_months
        remaining_fraction = max(0, (L - elapsed_months)) / L
        raw = base_cents * remaining_fraction
    elif depreciation_method == "DECLINING_BALANCE":
        raw = base_cents * (DECLINING_RATE ** elapsed_months)
    else:
        raise ValueError(f"unknown depreciation_method {depreciation_method}")
    return round_half_up(raw)


def premium_refund(amount_paid_cents: int, extension_months: int, elapsed_months: int,
                   premium_refund_method: str) -> int:
    """Unused-premium refund for extended-warranty cancellation (PRD §3.9)."""
    P = amount_paid_cents
    T = extension_months
    if T == 0:
        return 0
    unused = max(0, T - elapsed_months)
    if premium_refund_method == "PRO_RATA":
        raw = P * unused / T
    elif premium_refund_method == "SHORT_RATE":
        raw = P * unused / T * (1 - SHORT_RATE_PENALTY)
    else:
        raise ValueError(f"unknown premium_refund_method {premium_refund_method}")
    return round_half_up(raw)


def transfer_fee(category: str, elapsed_months: int, remaining_coverage_cents: int) -> int:
    """Tiered transfer fee (PRD §3.12). Order pinned: rate -> +surcharge -> floor -> cap."""
    if elapsed_months < 12:
        rate = TRANSFER_RATE_YEAR1
    elif elapsed_months < 36:
        rate = TRANSFER_RATE_YEAR1_3
    else:
        rate = TRANSFER_RATE_YEAR3_PLUS
    surcharge = CATEGORY_SURCHARGE_CENTS if category == "APPLIANCE" else 0
    raw = rate + surcharge
    return min(max(raw, TRANSFER_FEE_FLOOR_CENTS), remaining_coverage_cents)
