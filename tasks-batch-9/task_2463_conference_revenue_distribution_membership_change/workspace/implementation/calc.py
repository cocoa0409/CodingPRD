"""The eleven calculations of PRD section 3, expressed in exact integer maths.

All money is an integer number of cents and all rates are integer basis points
(one hundredth of one percent).  No floating point and no Decimal appears
anywhere: every quotient is taken with explicit floor or ceiling division so the
rounding discipline the PRD states is reproduced byte for byte.
"""

# ---------------------------------------------------------------------------
# Pinned constants (every one of these is a literal in PRD section 3)
# ---------------------------------------------------------------------------

RESERVE_TARGET_BPS = 1500
POSTURE_FROZEN_BPS = 2500
POSTURE_RESTRICTED_BPS = 6000
FULL_BPS = 10000

RESERVE_SWEEP_OPEN_BPS = 500
RESERVE_SWEEP_RESTRICTED_BPS = 1500

BASE_WEIGHT_BPS = 10000
MEDIA_APPEARANCE_WEIGHT_BPS = 1500
POSTSEASON_BERTH_WEIGHT_BPS = 2500

PROVISIONAL_WITHHOLDING_BPS = 1000
GOVERNANCE_SERVICE_FEE_CENTS = 1250000
GOR_OFFSET_CAP_BPS = 5000

ROLLING_WINDOW_YEARS = 6

ALLOWABLE_EXPENSE_CAP_CENTS = 8000000
TRAVEL_RATE_CENTS_PER_MILE = 95
TRAVEL_ALLOWANCE_CAP_CENTS = 2500000
HIGH_PAYOUT_THRESHOLD_CENTS = 10000000
HIGH_PAYOUT_BAND_BPS = 6000
LOW_PAYOUT_BAND_BPS = 8500

NOTICE_LONG_DAYS = 730
NOTICE_MEDIUM_DAYS = 365
NOTICE_MULTIPLIER_LONG_BPS = 10000
NOTICE_MULTIPLIER_MEDIUM_BPS = 20000
NOTICE_MULTIPLIER_SHORT_BPS = 30000

SURCHARGE_BAND_1_CEILING_CENTS = 100000000
SURCHARGE_BAND_2_CEILING_CENTS = 300000000
SURCHARGE_BAND_1_BPS = 200
SURCHARGE_BAND_2_BPS = 350
SURCHARGE_BAND_3_BPS = 500

QUORUM_WEIGHT_BPS = 6000
ADMIT_APPROVAL_BPS = 7500
WITHDRAW_APPROVAL_BPS = 6000
BUDGET_APPROVAL_BPS = 6670

COMPLIANCE_BASE_SCORE = 100
RIVALRY_PENALTY = 15
TRAVEL_PARTNER_PENALTY = 8
HOME_IMBALANCE_PENALTY = 5
TRAVEL_PAIR_WINDOW_DAYS = 3
HOST_MINIMUM_SCORE = 90

REST_BUFFER_DAYS = 6

HOST_SHARE_BPS = 2000

AMEND_LIMIT = 2

CHARTER_PHASE_YEAR = 4


# ---------------------------------------------------------------------------
# Rounding primitives
# ---------------------------------------------------------------------------


def floor_div(numerator, denominator):
    """Floor division that also floors correctly for negative numerators."""
    return numerator // denominator


def ceil_div(numerator, denominator):
    """Ceiling division; for a negative numerator this rounds toward zero."""
    return -((-numerator) // denominator)


def apply_rate_floor(amount, rate_bps):
    return floor_div(amount * rate_bps, FULL_BPS)


def apply_rate_ceil(amount, rate_bps):
    return ceil_div(amount * rate_bps, FULL_BPS)


# ---------------------------------------------------------------------------
# 1. reserve_posture_derivation
# ---------------------------------------------------------------------------


def reserve_posture(approved_operating_expense_cents, reserve_balance_cents):
    """Returns (reserve_target_cents, reserve_posture, funded_ratio_bps)."""
    target = apply_rate_ceil(approved_operating_expense_cents, RESERVE_TARGET_BPS)
    if target == 0:
        return 0, "OPEN", FULL_BPS
    scaled = reserve_balance_cents * FULL_BPS
    if scaled < target * POSTURE_FROZEN_BPS:
        posture = "FROZEN"
    elif scaled < target * POSTURE_RESTRICTED_BPS:
        posture = "RESERVE_RESTRICTED"
    else:
        posture = "OPEN"
    funded_ratio_bps = floor_div(reserve_balance_cents * FULL_BPS, target)
    return target, posture, funded_ratio_bps


# ---------------------------------------------------------------------------
# 2. member_phase_schedule
# ---------------------------------------------------------------------------

_ZERO_DISTRIBUTION_STATUSES = ("PETITIONED", "ADMISSION_DENIED", "DEPARTED")
_FULL_DISTRIBUTION_STATUSES = ("FULL_SHARE", "WITHDRAWAL_NOTICED")
_ZERO_VOTING_STATUSES = (
    "PETITIONED",
    "ADMISSION_DENIED",
    "WITHDRAWAL_NOTICED",
    "DEPARTED",
)


def phase_schedule(status, phase_year, phase_schedule_years):
    """Returns (distribution_phase_bps, voting_weight_bps)."""
    if status in _ZERO_DISTRIBUTION_STATUSES:
        distribution_bps = 0
    elif status in _FULL_DISTRIBUTION_STATUSES:
        distribution_bps = FULL_BPS
    else:
        distribution_bps = min(
            FULL_BPS,
            floor_div(FULL_BPS * phase_year, phase_schedule_years + 1),
        )

    if status in _ZERO_VOTING_STATUSES:
        voting_bps = 0
    elif status == "FULL_SHARE":
        voting_bps = FULL_BPS
    else:
        voting_bps = distribution_bps

    return distribution_bps, voting_bps


# ---------------------------------------------------------------------------
# 3. distribution_share_allocation
# ---------------------------------------------------------------------------


def net_pool_cents(gross_revenue_cents, expense_cents):
    """Net pool; may be negative when expenses exceed gross revenue."""
    return gross_revenue_cents - expense_cents


def reserve_sweep_bps(reserve_posture_value):
    if reserve_posture_value == "RESERVE_RESTRICTED":
        return RESERVE_SWEEP_RESTRICTED_BPS
    return RESERVE_SWEEP_OPEN_BPS


def reserve_draw_cents(net_pool, posture, reserve_target, reserve_balance):
    shortfall = max(0, reserve_target - reserve_balance)
    sweep = apply_rate_ceil(net_pool, reserve_sweep_bps(posture))
    return min(sweep, shortfall)


def raw_weight_bps(allocation_method, unit_count, media_appearances, postseason_berths):
    if allocation_method == "EQUAL_SHARE":
        return BASE_WEIGHT_BPS
    if allocation_method == "UNIT_BASED":
        return BASE_WEIGHT_BPS * unit_count
    # APPEARANCE_PERFORMANCE_WEIGHTED
    return (
        BASE_WEIGHT_BPS
        + MEDIA_APPEARANCE_WEIGHT_BPS * media_appearances
        + POSTSEASON_BERTH_WEIGHT_BPS * postseason_berths
    )


def phased_weight_bps(raw_bps, distribution_phase_bps):
    return floor_div(raw_bps * distribution_phase_bps, FULL_BPS)


def allocate_shares(distributable, entries):
    """Waterfall allocation with a pinned remainder deal.

    ``entries`` is the ordered list of (key, weight_bps) tuples already sorted
    by weight_bps DESC then Member.created_at ASC.  Returns a dict keyed by the
    entry key holding (gross_share_cents, remainder_cent_awarded); every cent of
    ``distributable`` is conserved.
    """
    total_weight = sum(weight for _key, weight in entries)
    result = {}
    if total_weight <= 0:
        return result, total_weight

    allocated = 0
    for key, weight in entries:
        share = floor_div(distributable * weight, total_weight)
        result[key] = [share, 0]
        allocated += share

    remainder = distributable - allocated
    if remainder > 0 and entries:
        index = 0
        while remainder > 0:
            key = entries[index % len(entries)][0]
            result[key][0] += 1
            result[key][1] += 1
            remainder -= 1
            index += 1
    return result, total_weight


# ---------------------------------------------------------------------------
# 4. distribution_line_offsets
# ---------------------------------------------------------------------------


def withheld_cents(gross_share, variant):
    if variant == "PROVISIONAL":
        return apply_rate_ceil(gross_share, PROVISIONAL_WITHHOLDING_BPS)
    return 0


def gor_offset_cents(
    member_status,
    grant_of_rights_through_fiscal_year,
    pool_fiscal_year,
    exit_settlement_total_cents,
    exit_settlement_paid_cents,
    available_cents,
):
    if member_status != "WITHDRAWAL_NOTICED":
        return 0
    if grant_of_rights_through_fiscal_year is None:
        return 0
    if grant_of_rights_through_fiscal_year < pool_fiscal_year:
        return 0
    outstanding = exit_settlement_total_cents - exit_settlement_paid_cents
    if outstanding <= 0:
        return 0
    cap = apply_rate_floor(exit_settlement_total_cents, GOR_OFFSET_CAP_BPS)
    return min(cap, outstanding, max(0, available_cents))


# ---------------------------------------------------------------------------
# 5. postseason_unit_valuation
# ---------------------------------------------------------------------------


def valuation_window(member_status, current_fiscal_year):
    """Returns (variant, window_start_fiscal_year, window_end_fiscal_year)."""
    if member_status == "WITHDRAWAL_NOTICED":
        return "CURRENT_YEAR_ONLY", current_fiscal_year, current_fiscal_year
    return (
        "ROLLING_SIX_YEAR",
        current_fiscal_year - (ROLLING_WINDOW_YEARS - 1),
        current_fiscal_year,
    )


def valuation_cents(unit_count, unit_value_cents):
    return unit_count * unit_value_cents


# ---------------------------------------------------------------------------
# 6. bowl_expense_reimbursement
# ---------------------------------------------------------------------------


def bowl_reimbursement(payout_cents, submitted_expense_cents, travel_miles):
    allowable = min(submitted_expense_cents, ALLOWABLE_EXPENSE_CAP_CENTS)
    travel_allowance = min(
        travel_miles * TRAVEL_RATE_CENTS_PER_MILE, TRAVEL_ALLOWANCE_CAP_CENTS
    )
    band_bps = (
        HIGH_PAYOUT_BAND_BPS
        if payout_cents >= HIGH_PAYOUT_THRESHOLD_CENTS
        else LOW_PAYOUT_BAND_BPS
    )
    ceiling = apply_rate_ceil(payout_cents, band_bps)
    reimbursed = min(allowable + travel_allowance, ceiling)
    residual = payout_cents - reimbursed
    return {
        "allowable_expense_cents": allowable,
        "travel_allowance_cents": travel_allowance,
        "reimbursement_ceiling_cents": ceiling,
        "reimbursed_cents": reimbursed,
        "residual_to_pool_cents": residual,
    }


# ---------------------------------------------------------------------------
# 7. exit_settlement_assessment
# ---------------------------------------------------------------------------


def notice_multiplier_bps(notice_days):
    if notice_days >= NOTICE_LONG_DAYS:
        return NOTICE_MULTIPLIER_LONG_BPS
    if notice_days >= NOTICE_MEDIUM_DAYS:
        return NOTICE_MULTIPLIER_MEDIUM_BPS
    return NOTICE_MULTIPLIER_SHORT_BPS


def surcharge_bracket_bps(base_assessment_cents):
    if base_assessment_cents < SURCHARGE_BAND_1_CEILING_CENTS:
        return SURCHARGE_BAND_1_BPS
    if base_assessment_cents < SURCHARGE_BAND_2_CEILING_CENTS:
        return SURCHARGE_BAND_2_BPS
    return SURCHARGE_BAND_3_BPS


def exit_settlement(notice_days, last_full_annual_distribution_cents):
    """The six pinned steps of PRD section 3.8."""
    multiplier = notice_multiplier_bps(notice_days)
    base = apply_rate_ceil(last_full_annual_distribution_cents, multiplier)
    bracket = surcharge_bracket_bps(base)
    surcharge = apply_rate_ceil(base, bracket)
    return {
        "notice_multiplier_bps": multiplier,
        "base_assessment_cents": base,
        "surcharge_bracket_bps": bracket,
        "surcharge_cents": surcharge,
        "exit_settlement_total_cents": base + surcharge,
    }


# ---------------------------------------------------------------------------
# 8. vote_tally
# ---------------------------------------------------------------------------


def tally(eligible_weight_bps, ballots, quorum_bps, required_approval_bps):
    """``ballots`` is the list of counted (CAST) ballots."""
    cast_weight = 0
    for_weight = 0
    against_weight = 0
    for ballot in ballots:
        cast_weight += ballot["weight_bps"]
        if ballot["choice"] == "FOR":
            for_weight += ballot["weight_bps"]
        elif ballot["choice"] == "AGAINST":
            against_weight += ballot["weight_bps"]

    decisive = for_weight + against_weight
    approval_ratio_bps = 0 if decisive == 0 else floor_div(for_weight * FULL_BPS, decisive)
    quorum_met = cast_weight * FULL_BPS >= eligible_weight_bps * quorum_bps
    approved = quorum_met and approval_ratio_bps >= required_approval_bps
    return {
        "eligible_weight_bps": eligible_weight_bps,
        "cast_weight_bps": cast_weight,
        "for_weight_bps": for_weight,
        "against_weight_bps": against_weight,
        "approval_ratio_bps": approval_ratio_bps,
        "quorum_met": quorum_met,
        "outcome": "APPROVED" if approved else "REJECTED",
    }


def required_approval_for_action(action_type):
    return ADMIT_APPROVAL_BPS if action_type == "ADMIT" else WITHDRAW_APPROVAL_BPS


# ---------------------------------------------------------------------------
# 10. championship_event_settlement
# ---------------------------------------------------------------------------


def championship_split(ticket_revenue_cents, sponsorship_revenue_cents, expense_cents):
    net = ticket_revenue_cents + sponsorship_revenue_cents - expense_cents
    host_share = apply_rate_ceil(net, HOST_SHARE_BPS) if net > 0 else 0
    return net, host_share, net - host_share
