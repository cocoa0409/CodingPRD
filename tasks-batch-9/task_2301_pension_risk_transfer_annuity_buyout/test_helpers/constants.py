"""Numeric constants and pure-Python recomputations of the PRD formulas.

Every constant here is a literal declared in the PRD. The helper functions
mirror the PRD's arithmetic so that tests can assert against an independently
derived figure instead of a magic number.

All monetary amounts are integer cents; all rates are integer basis points.
"""

from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

#: The logical clock's value at server startup.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"


def iso_instant(instant: str) -> str:
    """Render an ISO-8601 UTC instant with the three fractional digits the PRD requires."""
    moment = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def days_after(instant: str, days: int) -> str:
    """Add exact whole days to an ISO-8601 instant, keeping the `Z` suffix."""
    moment = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    moved = moment + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moved.microsecond // 1000)


# ---------------------------------------------------------------------------
# Participant liability factors
# ---------------------------------------------------------------------------

ACCOUNTING_FACTOR_BP = {
    "RETIREE_IN_PAY": 118000,
    "DEFERRED_VESTED": 95500,
}

SETTLEMENT_FACTOR_BP = {
    "RETIREE_IN_PAY": 126250,
    "DEFERRED_VESTED": 104500,
}

#: Load applied on top of the raw settlement basis when projecting a strategy.
SETTLEMENT_EXPENSE_LOAD_BP = 350

#: Uplift used to derive the plan's settlement-basis liability from its PBO.
SETTLEMENT_BASIS_UPLIFT_BP = 10700


# ---------------------------------------------------------------------------
# Benefit recomputation / audit
# ---------------------------------------------------------------------------

BENEFIT_ACCRUAL_RATE_BP = 150
MAX_CREDITED_SERVICE_MONTHS = 420
AUDIT_VARIANCE_TOLERANCE_CENTS = 500


# ---------------------------------------------------------------------------
# Lump sum present value and administrative fee
# ---------------------------------------------------------------------------

LS_FACTOR_BP = {
    "RETIREE_IN_PAY": 121000,
    "DEFERRED_VESTED": 100000,
}

ADMIN_FEE_TIER_1_MAX_CENTS = 2400000
ADMIN_FEE_TIER_2_MAX_CENTS = 12000000
ADMIN_FEE_TIER_1_BP = 0
ADMIN_FEE_TIER_2_BP = 75
ADMIN_FEE_TIER_3_BP = 40
ADMIN_FEE_CAP_CENTS = 500000


# ---------------------------------------------------------------------------
# Insurer rating and composite scoring
# ---------------------------------------------------------------------------

RATING_POINTS = {
    "AAA": 100,
    "AA_PLUS": 92,
    "AA": 85,
    "AA_MINUS": 78,
    "A_PLUS": 70,
    "A": 60,
    "BBB": 40,
}

#: Minimum rating points an insurer must carry to clear the safest-available floor.
SAFEST_AVAILABLE_MIN_RATING_POINTS = 78

W_RATING = {"SAFETY_WEIGHTED": 55, "PRICE_WEIGHTED": 25}
W_CAPITAL = {"SAFETY_WEIGHTED": 25, "PRICE_WEIGHTED": 15}
W_PRICE = {"SAFETY_WEIGHTED": 20, "PRICE_WEIGHTED": 60}


# ---------------------------------------------------------------------------
# Asset transfer crediting
# ---------------------------------------------------------------------------

IN_KIND_HAIRCUT_BP = 125
PER_LOT_CUSTODY_FEE_CENTS = 25000
CASH_WIRE_FEE_BP = 8
MIN_IN_KIND_LOT_COUNT = 1
MAX_IN_KIND_LOT_COUNT = 500


# ---------------------------------------------------------------------------
# Data confidence scoring
# ---------------------------------------------------------------------------

DATA_CONFIDENCE_MAX = 100
DEDUCT_ADDRESS_UNCONFIRMED = 40
DEDUCT_ADDRESS_UNLOCATABLE = 25
DEDUCT_MORTALITY_UNVERIFIED = 20
DEDUCT_AUDIT_OPEN = 15
DATA_CONFIDENCE_CLEAN_MIN = 80

#: The mortality states that still cost points.
MORTALITY_DEDUCTED_STATES = ("UNVERIFIED", "DEATH_DISPUTED")

#: The participant audit states that still cost points.
AUDIT_DEDUCTED_STATES = ("NOT_AUDITED", "AUDIT_OPEN", "CORRECTION_REQUIRED", "REOPENED")


# ---------------------------------------------------------------------------
# Periods and bounds expressed in the PRD prose
# ---------------------------------------------------------------------------

#: Quiet period, in whole days, required after a sibling window's closes_at.
QUIET_PERIOD_DAYS = 90

#: Minimum runway, in whole days, between the clock and closes_at when opening.
NOTICE_PERIOD_DAYS = 30

#: Revocation grace, in whole days, measured after elected_at.
REVOCATION_PERIOD_DAYS = 7

#: revision_count must be below this value for a further return-for-revision.
MAX_REVISION_ROUNDS = 2

#: revocation_count must be below this value for a further revocation.
MAX_REVOCATIONS = 1

#: An address search may be attempted at most this many times.
MAX_ADDRESS_SEARCH_ATTEMPTS = 3

#: Field length bounds.
MAX_LABEL_LENGTH = 120
MAX_NAME_LENGTH = 200
MAX_EXPERT_FIRM_NAME_LENGTH = 200
MAX_COMPLAINT_NARRATIVE_LENGTH = 1000
PLAN_EIN_LENGTH = 9


# ---------------------------------------------------------------------------
# Rounding primitives
# ---------------------------------------------------------------------------


def round_half_up(numerator: int, denominator: int) -> int:
    """Divide, rounding halves away from zero (round-half-up on magnitude)."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    sign = -1 if numerator < 0 else 1
    magnitude = abs(numerator)
    return sign * ((magnitude * 2 + denominator) // (2 * denominator))


def floor_div(numerator: int, denominator: int) -> int:
    """Truncate toward zero, as the PRD's point scores do."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    sign = -1 if numerator < 0 else 1
    return sign * (abs(numerator) // denominator)


def apply_bp(amount_cents: int, rate_bp: int) -> int:
    """Scale an amount by a basis-point rate with round-half-up."""
    return round_half_up(amount_cents * rate_bp, 10000)


# ---------------------------------------------------------------------------
# Derived figures
# ---------------------------------------------------------------------------


#: The number of monthly payments in a year; every liability factor applies to
#: the annualised benefit, not the monthly one.
MONTHS_PER_YEAR = 12


def annualise(monthly_benefit_cents: int) -> int:
    return monthly_benefit_cents * MONTHS_PER_YEAR


def accounting_liability(monthly_benefit_cents: int, cohort: str) -> int:
    """Per-participant accounting (PBO) liability."""
    return apply_bp(annualise(monthly_benefit_cents), ACCOUNTING_FACTOR_BP[cohort])


def settlement_liability(monthly_benefit_cents: int, cohort: str) -> int:
    """Per-participant settlement-basis liability."""
    return apply_bp(annualise(monthly_benefit_cents), SETTLEMENT_FACTOR_BP[cohort])


def projected_accounting_cost(population: "list") -> int:
    """Sum of per-participant accounting liabilities, each rounded before summing.

    `population` is a sequence of `(monthly_benefit_cents, cohort)` pairs.
    """
    return sum(accounting_liability(benefit, cohort) for benefit, cohort in population)


def projected_settlement_base(population: "list") -> int:
    """Sum of per-participant settlement liabilities, each rounded before summing."""
    return sum(settlement_liability(benefit, cohort) for benefit, cohort in population)


def projected_settlement_cost(population: "list") -> int:
    """The settlement base uplifted by the settlement expense load."""
    base = projected_settlement_base(population)
    return base + apply_bp(base, SETTLEMENT_EXPENSE_LOAD_BP)


def recomputed_monthly_benefit(
    final_average_monthly_earnings_cents: int, credited_service_months: int
) -> int:
    """The audit's independently recomputed monthly benefit."""
    capped_months = min(credited_service_months, MAX_CREDITED_SERVICE_MONTHS)
    return round_half_up(
        final_average_monthly_earnings_cents * BENEFIT_ACCRUAL_RATE_BP * capped_months,
        10000 * 12,
    )


def fame_for_zero_variance(
    stated_monthly_benefit_cents: int, credited_service_months: int
) -> int:
    """The FAME that makes the recomputed benefit equal the stated benefit.

    Only exact for stated benefits that divide cleanly; callers that need an
    exact zero variance should assert the recomputation afterwards.
    """
    capped_months = min(credited_service_months, MAX_CREDITED_SERVICE_MONTHS)
    return round_half_up(
        stated_monthly_benefit_cents * 10000 * 12,
        BENEFIT_ACCRUAL_RATE_BP * capped_months,
    )


def raw_lump_sum_pv(monthly_benefit_cents: int, cohort: str) -> int:
    """The pre-fee present value of a lump sum offer."""
    return apply_bp(annualise(monthly_benefit_cents), LS_FACTOR_BP[cohort])


def admin_fee_bp_for(raw_pv_cents: int) -> int:
    """The fee tier keyed on the pre-fee amount; both ceilings are inclusive."""
    if raw_pv_cents <= ADMIN_FEE_TIER_1_MAX_CENTS:
        return ADMIN_FEE_TIER_1_BP
    if raw_pv_cents <= ADMIN_FEE_TIER_2_MAX_CENTS:
        return ADMIN_FEE_TIER_2_BP
    return ADMIN_FEE_TIER_3_BP


def admin_fee_cents_for(raw_pv_cents: int) -> int:
    """The capped administrative fee charged against a lump sum."""
    fee = apply_bp(raw_pv_cents, admin_fee_bp_for(raw_pv_cents))
    return min(fee, ADMIN_FEE_CAP_CENTS)


def net_lump_sum_cents_for(raw_pv_cents: int) -> int:
    """The amount actually paid to the participant."""
    return raw_pv_cents - admin_fee_cents_for(raw_pv_cents)


def rating_component(rating_grade: str) -> int:
    """The rating term of an insurer's composite score, in points."""
    return RATING_POINTS[rating_grade]


def capital_component(capital_ratio_bp: int) -> int:
    """The capital term of an insurer's composite score, in points (capped at 100)."""
    return min(100, floor_div(capital_ratio_bp, 100))


def price_component(lowest_premium_cents: int, premium_cents: int) -> int:
    """The price term of a quote's composite score, in points."""
    return floor_div(lowest_premium_cents * 100, premium_cents)


def composite_score_bp(
    selection_basis: str,
    rating_grade: str,
    capital_ratio_bp: int,
    lowest_premium_cents: int,
    premium_cents: int,
) -> int:
    """A quote's composite score in basis points under the given basis."""
    return (
        rating_component(rating_grade) * W_RATING[selection_basis]
        + capital_component(capital_ratio_bp) * W_CAPITAL[selection_basis]
        + price_component(lowest_premium_cents, premium_cents) * W_PRICE[selection_basis]
    )


def in_kind_credited_value(gross_value_cents: int, lot_count: int) -> int:
    """Credited value of an in-kind delivery after haircut and custody fees."""
    return gross_value_cents - in_kind_transfer_expense(gross_value_cents, lot_count)


def in_kind_transfer_expense(gross_value_cents: int, lot_count: int) -> int:
    """Haircut plus per-lot custody fees on an in-kind delivery."""
    haircut = apply_bp(gross_value_cents, IN_KIND_HAIRCUT_BP)
    return haircut + PER_LOT_CUSTODY_FEE_CENTS * lot_count


def cash_transfer_expense(gross_value_cents: int) -> int:
    """The wire fee on a cash delivery."""
    return apply_bp(gross_value_cents, CASH_WIRE_FEE_BP)


def cash_credited_value(gross_value_cents: int) -> int:
    """Credited value of a cash delivery after the wire fee."""
    return gross_value_cents - cash_transfer_expense(gross_value_cents)


def data_confidence_for(
    address_status: str, mortality_status: str, benefit_audit_status: str
) -> int:
    """The participant's data confidence score after all deductions, floored at 0."""
    score = DATA_CONFIDENCE_MAX
    if address_status == "UNCONFIRMED":
        score -= DEDUCT_ADDRESS_UNCONFIRMED
    elif address_status == "UNLOCATABLE":
        score -= DEDUCT_ADDRESS_UNLOCATABLE
    if mortality_status in MORTALITY_DEDUCTED_STATES:
        score -= DEDUCT_MORTALITY_UNVERIFIED
    if benefit_audit_status in AUDIT_DEDUCTED_STATES:
        score -= DEDUCT_AUDIT_OPEN
    return max(0, score)


def data_status_for(data_confidence_score: int) -> str:
    """`CLEAN` at or above the inclusive threshold, `NEEDS_REVIEW` below it."""
    return "CLEAN" if data_confidence_score >= DATA_CONFIDENCE_CLEAN_MIN else "NEEDS_REVIEW"


def settlement_basis_liability(total_liability_cents: int) -> int:
    """The plan-level settlement-basis liability derived from the PBO."""
    return apply_bp(total_liability_cents, SETTLEMENT_BASIS_UPLIFT_BP)


def funded_status_bp(plan_assets_cents: int, liability_cents: int) -> int:
    """Assets over liability in basis points; 0 when the liability is 0."""
    if liability_cents == 0:
        return 0
    return round_half_up(plan_assets_cents * 10000, liability_cents)


def settlement_funded_status_bp(plan_assets_cents: int, total_liability_cents: int) -> int:
    """Assets over the uplifted settlement-basis liability, in basis points."""
    return funded_status_bp(
        plan_assets_cents, settlement_basis_liability(total_liability_cents)
    )


def unfunded_settlement_gap_cents(plan_assets_cents: int, total_liability_cents: int) -> int:
    """The shortfall of assets against the uplifted liability, floored at 0."""
    uplifted = settlement_basis_liability(total_liability_cents)
    return max(0, uplifted - plan_assets_cents)
