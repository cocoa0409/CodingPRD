"""Calculation rules (PRD 2.6, 3.4, 3.5, 3.6, 3.8, 3.9).

Every amount is an integer number of whole cents; every proportion is an
integer number of basis points.  Rounding order is pinned per rule.
"""
from decimal import Decimal, ROUND_HALF_UP

from store import (
    AMU_DISCOUNT_BP,
    MAX_SPLIT_BP,
    PENALTY_MULTIPLIER,
    PENETRATION_GRACE_BP,
    RIGHTS_CREDIT_BP,
    add_days,
)


def round_half_up(numerator, denominator):
    """Exact half-up rounding of numerator/denominator (away from zero)."""
    return int(
        (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    )


def floor_div(numerator, denominator):
    """Truncation toward negative infinity."""
    return int(numerator) // int(denominator)


# --- calculation: offer_projected_total_fee ---------------------------------
def contract_year_count(term_months):
    return -((-int(term_months)) // 12)


def year_month_attribution(term_months):
    count = contract_year_count(term_months)
    return [min(12, term_months - 12 * (n - 1)) for n in range(1, count + 1)]


def compound_annual_ladder(base_rate, escalator_bp, term_months):
    """Year n escalates off the ALREADY-ROUNDED year n-1 rate."""
    count = contract_year_count(term_months)
    ladder = [int(base_rate)]
    for _ in range(2, count + 1):
        ladder.append(round_half_up(ladder[-1] * (10000 + int(escalator_bp)), 10000))
    return ladder


def simple_annual_ladder(base_rate, escalator_bp, term_months):
    """Year n escalates off the unrounded base with a linear multiplier."""
    count = contract_year_count(term_months)
    return [
        round_half_up(int(base_rate) * (10000 + int(escalator_bp) * (n - 1)), 10000)
        for n in range(1, count + 1)
    ]


def whole_term_total_fee(ladder, basis, term_months):
    """Per-year rate rounded FIRST, then multiplied by basis and months."""
    months = year_month_attribution(term_months)
    total = 0
    for index, rate in enumerate(ladder):
        total += rate * int(basis) * months[index]
    return total


# --- calculation: subscriber_basis_determination ---------------------------
def subscriber_basis(adjusted, method):
    if method == "BILLED_HOUSEHOLDS":
        basis = int(adjusted)
    elif method == "WEIGHTED_STREAMING_DEVICES":
        basis = floor_div(int(adjusted) * 10, 25)
    else:  # AVERAGE_MONTHLY_UNIQUE
        basis = round_half_up(int(adjusted) * AMU_DISCOUNT_BP, 10000)
    return max(0, basis)


# --- calculation: blackout_notice_deadline ---------------------------------
def blackout_notice_deadline(incumbent_expiry_utc, required_days):
    return add_days(incumbent_expiry_utc, -int(required_days))


def required_notice_days(distributor_type):
    return 14 if distributor_type == "VMVPD" else 30


# --- calculation: interim_extension_rate ----------------------------------
def interim_extension_rate(basis_kind, prior_rate, last_station_offer_rate):
    if basis_kind == "PRIOR_RATE":
        return int(prior_rate)
    if basis_kind == "LAST_STATION_OFFER":
        return int(last_station_offer_rate)
    # MIDPOINT always floors, never rounds half up.
    return floor_div(int(prior_rate) + int(last_station_offer_rate), 2)


# --- calculation: penetration_shortfall_penalty ---------------------------
def penetration_penalty(basis, video_household_count, commitment_bp, gross_fee_cents):
    actual_bp = floor_div(int(basis) * 10000, int(video_household_count))
    shortfall_bp = max(0, int(commitment_bp) - actual_bp)
    if shortfall_bp <= PENETRATION_GRACE_BP:
        penalty = 0
    else:
        penalty = round_half_up(
            int(gross_fee_cents) * shortfall_bp * PENALTY_MULTIPLIER, 10000
        )
    return actual_bp, shortfall_bp, penalty


# --- calculation: reverse_compensation_split ------------------------------
def contract_year_index(period_start_utc, effective_start_utc):
    elapsed_months = (
        (period_start_utc.year - effective_start_utc.year) * 12
        + (period_start_utc.month - effective_start_utc.month)
    )
    return floor_div(elapsed_months, 12) + 1


def split_tier_bp(rate_per_sub_cents):
    rate = int(rate_per_sub_cents)
    if rate <= 200:
        return 4000
    if rate <= 300:
        return 5000
    return 5500


def reverse_compensation_split(
    rate_per_sub_cents,
    basis,
    excluded_dispute_terms,
    split_premium_bp,
    floor_per_sub_cents,
    video_household_count,
    commitment_bp,
):
    """Returns the six-step waterfall as a dict of stored settlement fields."""
    rate = int(rate_per_sub_cents)
    basis = int(basis)
    gross = rate * basis

    # STEP 2 -- each credit rounded on its own, then summed, in the order given.
    rights_credit = 0
    for term in excluded_dispute_terms:
        rights_credit += round_half_up(gross * RIGHTS_CREDIT_BP[term], 10000)

    # STEP 3
    creditable_base = gross - rights_credit

    # STEP 4 -- the tier keys on the PRE-CREDIT per-subscriber rate.
    split_bp = min(split_tier_bp(rate) + int(split_premium_bp), MAX_SPLIT_BP)

    # STEP 5 -- the greater of the share and the per-subscriber floor.
    reverse_comp = max(
        round_half_up(creditable_base * split_bp, 10000),
        int(floor_per_sub_cents) * basis,
    )

    # STEP 6 -- penalty, then the residual.
    actual_bp, shortfall_bp, penalty = penetration_penalty(
        basis, video_household_count, commitment_bp, gross
    )
    net_retained = creditable_base - reverse_comp - penalty

    return {
        "gross_fee_cents": gross,
        "rights_credit_cents": rights_credit,
        "reverse_comp_split_bp": split_bp,
        "reverse_comp_cents": reverse_comp,
        "actual_penetration_bp": actual_bp,
        "penetration_shortfall_bp": shortfall_bp,
        "penetration_penalty_cents": penalty,
        "net_retained_cents": net_retained,
    }
