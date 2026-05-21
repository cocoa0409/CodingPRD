"""Pure calculation functions specified in scaffold §1.3.

All money is in integer cents. Rounding is round_half_up where specified;
all other arithmetic is integer-only.
"""
from __future__ import annotations

from typing import Dict, List

from core.utils import round_half_up_int


BP_DENOM = 10000


# ---------------------------------------------------------------------------
# contribution_amount
# ---------------------------------------------------------------------------
def compute_contribution_amount(
    *,
    gross_pay_cents: int,
    contribution_rate_bp: int,
    annual_accrual_cap_cents: int,
    ytd_accrual_cents: int,
    discount_bp: int,
) -> int:
    """Compute the per-pay-period contribution amount in cents (capped)."""
    raw_amount_cents = round_half_up_int(
        gross_pay_cents * contribution_rate_bp, BP_DENOM
    )
    remaining_accrual_cents = annual_accrual_cap_cents - ytd_accrual_cents
    # remaining_cash_cap = floor(remaining_accrual * (10000 - discount_bp) / 10000)
    remaining_cash_cap_cents = (
        remaining_accrual_cents * (BP_DENOM - discount_bp)
    ) // BP_DENOM
    capped = max(0, remaining_cash_cap_cents)
    return min(raw_amount_cents, capped)


# ---------------------------------------------------------------------------
# purchase_settlement
# ---------------------------------------------------------------------------
def compute_purchase_price(
    *,
    grant_date_fmv_cents: int,
    purchase_date_fmv_cents: int,
    lookback_enabled: bool,
    discount_bp: int,
) -> Dict[str, int]:
    if lookback_enabled:
        chosen_fmv_cents = min(grant_date_fmv_cents, purchase_date_fmv_cents)
    else:
        chosen_fmv_cents = purchase_date_fmv_cents
    purchase_price_cents = round_half_up_int(
        chosen_fmv_cents * (BP_DENOM - discount_bp), BP_DENOM
    )
    return {
        "chosen_fmv_cents": chosen_fmv_cents,
        "purchase_price_cents": purchase_price_cents,
    }


def compute_purchase_settlement(
    *,
    grant_date_fmv_cents: int,
    purchase_date_fmv_cents: int,
    lookback_enabled: bool,
    discount_bp: int,
    posted_contribution_cents: int,
    annual_accrual_cap_cents: int,
    ytd_accrual_cents: int,
) -> Dict[str, int]:
    """Run steps A–F of the purchase_settlement calculation.

    Returns a dict with chosen_fmv_cents, purchase_price_cents,
    contributions_used_cents, shares_purchased, refund_cents,
    accrual_charge_cents.
    """
    base = compute_purchase_price(
        grant_date_fmv_cents=grant_date_fmv_cents,
        purchase_date_fmv_cents=purchase_date_fmv_cents,
        lookback_enabled=lookback_enabled,
        discount_bp=discount_bp,
    )
    chosen_fmv_cents = base["chosen_fmv_cents"]
    purchase_price_cents = base["purchase_price_cents"]

    contributions_used_cents = posted_contribution_cents

    # Step D — floor to whole shares
    if purchase_price_cents == 0:
        shares_purchased = 0
    else:
        shares_purchased = contributions_used_cents // purchase_price_cents
    refund_cents = contributions_used_cents - shares_purchased * purchase_price_cents

    # Step E — proposed IRC 423 accrual charge at GRANT-DATE FMV.
    accrual_charge_cents = shares_purchased * grant_date_fmv_cents
    remaining_accrual_cents = annual_accrual_cap_cents - ytd_accrual_cents

    # Step F — reduce shares to fit remaining accrual.
    if accrual_charge_cents > remaining_accrual_cents:
        if grant_date_fmv_cents == 0:
            shares_purchased = 0
        else:
            shares_purchased = max(0, remaining_accrual_cents) // grant_date_fmv_cents
        refund_cents = contributions_used_cents - shares_purchased * purchase_price_cents
        accrual_charge_cents = shares_purchased * grant_date_fmv_cents

    return {
        "chosen_fmv_cents": chosen_fmv_cents,
        "purchase_price_cents": purchase_price_cents,
        "contributions_used_cents": contributions_used_cents,
        "shares_purchased": shares_purchased,
        "refund_cents": refund_cents,
        "accrual_charge_cents": accrual_charge_cents,
    }


# ---------------------------------------------------------------------------
# disposition_tax_split
# ---------------------------------------------------------------------------
def compute_disposition_tax_split(
    *,
    classification: str,
    shares_disposed: int,
    sale_price_per_share_cents: int,
    purchase_price_cents: int,
    chosen_fmv_cents: int,
    purchase_date_fmv_cents: int,
    discount_bp: int,
) -> Dict[str, int]:
    if classification == "QUALIFYING":
        actual_gain_per_share = sale_price_per_share_cents - purchase_price_cents
        theoretical_discount_per_share = round_half_up_int(
            chosen_fmv_cents * discount_bp, BP_DENOM
        )
        ordinary_per_share = max(
            0, min(actual_gain_per_share, theoretical_discount_per_share)
        )
        ordinary_income_cents = shares_disposed * ordinary_per_share
        capital_basis_per_share = purchase_price_cents + ordinary_per_share
        capital_gain_cents = shares_disposed * (
            sale_price_per_share_cents - capital_basis_per_share
        )
    else:  # DISQUALIFYING
        ordinary_per_share = max(
            0, purchase_date_fmv_cents - purchase_price_cents
        )
        ordinary_income_cents = shares_disposed * ordinary_per_share
        capital_basis_per_share = purchase_price_cents + ordinary_per_share
        capital_gain_cents = shares_disposed * (
            sale_price_per_share_cents - capital_basis_per_share
        )

    return {
        "ordinary_income_cents": ordinary_income_cents,
        "capital_gain_cents": capital_gain_cents,
    }


# ---------------------------------------------------------------------------
# purchase_dilution_warning_score
# ---------------------------------------------------------------------------
def compute_dilution_score(
    *,
    max_contribution_rate_bp: int,
    annual_accrual_cap_cents: int,
    active_enrollment_count: int,
    eligible_employee_count: int,
) -> int:
    rate_factor = min(1.0, max_contribution_rate_bp / 1500.0)
    cap_factor = annual_accrual_cap_cents / 2500000.0
    denom_employees = max(1, eligible_employee_count)
    participation = active_enrollment_count / denom_employees

    if rate_factor < 0.5:
        weighted = (
            0.4 * rate_factor
            + 0.3 * cap_factor * rate_factor * rate_factor
            + 0.3 * participation * rate_factor * rate_factor
        )
    else:
        weighted = (
            0.4 * rate_factor
            + 0.3 * cap_factor
            + 0.3 * participation
        )

    # round_half_up at the final 100x scaling.
    scaled = weighted * 100.0
    # Use integer round_half_up by converting via a milli-scale to dodge float
    # imprecision.
    scaled_milli = int(round_half_up_int(int(round(scaled * 1000)), 1000))
    # Note: round_half_up_int already takes integer numerator/denominator; we
    # divide by 1000 to bring back to int score.
    # Implement explicit round-half-up on floats:
    floor_val = int(scaled)
    frac = scaled - floor_val
    if frac >= 0.5 - 1e-9:
        score = floor_val + 1 if scaled >= 0 else floor_val
    else:
        score = floor_val
    # Clamp to [0, 100].
    return max(0, min(100, score))
