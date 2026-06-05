"""Calculations module — implements the formulas in SCAFFOLD §1.3 / PRD §3.2 & §3.5.

title_insurance_premium  — tiered_pricing, per-tier ROUND_HALF_UP, optional 15%
                            lender-concurrent discount applied after the per-tier
                            sum and re-rounded ROUND_HALF_UP.

cd_reissue_clock_reset   — threshold predicate (any-of: |delta_bps| >= 12,
                            product_type change, prepayment_penalty false->true).

disbursement_waterfall   — created_at ASC; tie-break by purpose lexicographic
                            (EARNEST_REFUND < EXCHANGE_FUNDS < LENDER_PAYOFF
                             < SELLER_PROCEEDS < TITLE_PREMIUM). Pre-check
                            sufficiency; integer cents throughout.

earnest_refund_split     — emits one refund Disbursement per flipped deposit,
                            ordered created_at ASC tie-broken by depositor_role
                            (BUYER < BUYERS_AGENT).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


TIER1_BREAK_CENTS = 10_000_000  # 100,000 dollars
TIER2_BREAK_CENTS = 50_000_000  # 500,000 dollars
TIER3_BREAK_CENTS = 100_000_000  # 1,000,000 dollars
TIER1_RATE = Decimal("0.00450")
TIER2_RATE = Decimal("0.00400")
TIER3_RATE = Decimal("0.00350")
TIER4_RATE = Decimal("0.00300")

APR_REISSUE_BPS_THRESHOLD = 12
CD_WAIT_PERIOD_HOURS = 72


def _round_half_up_to_cents(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def title_insurance_premium_cents(purchase_price_cents: int, lender_concurrent: bool) -> int:
    """Compute premium per SCAFFOLD §1.3 title_insurance_premium.

    Per-tier ROUND_HALF_UP to whole cents, then sum. If lender_concurrent variant:
    apply 0.15 reduction (multiply by 0.85) to the per-tier sum, then ROUND_HALF_UP
    once on the reduced amount.
    """
    p = int(purchase_price_cents)

    slice1 = min(p, TIER1_BREAK_CENTS)
    slice2 = max(min(p, TIER2_BREAK_CENTS) - TIER1_BREAK_CENTS, 0)
    slice3 = max(min(p, TIER3_BREAK_CENTS) - TIER2_BREAK_CENTS, 0)
    slice4 = max(p - TIER3_BREAK_CENTS, 0)

    # cents -> dollars at formula boundary (divide by 100), then multiply by rate,
    # convert the slice premium (dollars) back to cents (multiply by 100), and
    # round half-up to whole cents per-tier.
    def slice_cents(slice_cents_val: int, rate: Decimal) -> int:
        slice_dollars = Decimal(slice_cents_val) / Decimal(100)
        slice_premium_dollars = slice_dollars * rate
        # Convert back to cents: multiply by 100.
        slice_premium_cents = slice_premium_dollars * Decimal(100)
        return _round_half_up_to_cents(slice_premium_cents)

    s1 = slice_cents(slice1, TIER1_RATE)
    s2 = slice_cents(slice2, TIER2_RATE)
    s3 = slice_cents(slice3, TIER3_RATE)
    s4 = slice_cents(slice4, TIER4_RATE)
    base = s1 + s2 + s3 + s4

    if not lender_concurrent:
        return base
    # Apply 15% reduction; multiply by 0.85; final ROUND_HALF_UP to cents.
    reduced = Decimal(base) * Decimal("0.85")
    return _round_half_up_to_cents(reduced)


def cd_reissue_is_material(
    current_apr_bps: int,
    current_product_type: str,
    current_prepayment_penalty: bool,
    req_apr_bps: int | None,
    req_product_type: str | None,
    req_prepayment_penalty: bool | None,
) -> bool:
    """Any-of predicate from SCAFFOLD §1.3 cd_reissue_clock_reset.

    Material when:
      - |req.cd_apr_bps - current.cd_apr_bps| >= 12 (>= is the documented boundary)
      - req.cd_product_type != current.cd_product_type
      - req.cd_prepayment_penalty changes from FALSE to TRUE
    A change to total_loan_amount_cents / monthly_payment_cents / prepayment true->false never re-clocks.
    Missing fields in the request body are not changes.
    """
    if req_apr_bps is not None:
        if abs(int(req_apr_bps) - int(current_apr_bps)) >= APR_REISSUE_BPS_THRESHOLD:
            return True
    if req_product_type is not None:
        if req_product_type != current_product_type:
            return True
    if req_prepayment_penalty is not None:
        if (current_prepayment_penalty is False) and (req_prepayment_penalty is True):
            return True
    return False


# Disbursement purpose lexicographic order (PRD §3.5 tie-break):
#   EARNEST_REFUND < EXCHANGE_FUNDS < LENDER_PAYOFF < SELLER_PROCEEDS < TITLE_PREMIUM.
DISBURSEMENT_PURPOSE_ORDER = {
    "EARNEST_REFUND": 0,
    "EXCHANGE_FUNDS": 1,
    "LENDER_PAYOFF": 2,
    "SELLER_PROCEEDS": 3,
    "TITLE_PREMIUM": 4,
}


def disbursement_sort_key(d: dict):
    """Key for waterfall iteration: (created_at_asc, purpose_lex)."""
    return (d["created_at"], DISBURSEMENT_PURPOSE_ORDER[d["purpose"]])


# EarnestRefund tie-break (PRD §3.6): created_at ASC, then depositor_role lex
# (BUYER < BUYERS_AGENT).
DEPOSITOR_ROLE_ORDER = {"BUYER": 0, "BUYERS_AGENT": 1}


def earnest_deposit_refund_sort_key(d: dict):
    return (d["created_at"], DEPOSITOR_ROLE_ORDER[d["depositor_role"]])
