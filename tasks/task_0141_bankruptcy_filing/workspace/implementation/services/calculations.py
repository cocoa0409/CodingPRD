"""Calculation engine for bankruptcy-filing operations.

Implements the four calculations from SCAFFOLD §1.3:
  - means_test (threshold)
  - trustee_payment_waterfall (waterfall_allocation)
  - schedule_completeness (aggregation)
  - total_unsecured_pool (aggregation)
  - discharge_exemption_partition (aggregation; encoded directly in case_engine)

All monetary arithmetic uses integer cents. Rounding is half-up via
utils.round_half_up_int wherever division produces a fractional cent.
"""

from config import (
    REQUIRED_SCHEDULES,
    STATE_MEDIAN_TABLE,
    DEFAULT_STATE_MEDIAN_1,
    DEFAULT_STATE_MEDIAN_2,
    ADMIN_FEE_RATE_NUMERATOR,
    ADMIN_FEE_RATE_DENOMINATOR,
)
from db import store
from utils import round_half_up_int


# --------------------------------------------------------------------------
# schedule_completeness — sorted list of letters not yet covered by an
# unsuperseded snapshot for the case.
# --------------------------------------------------------------------------
def compute_schedule_completeness(case_id: str) -> list[str]:
    present = set()
    for sched in store.schedules.values():
        if sched["case_id"] != case_id:
            continue
        if sched.get("superseded_by_id") is not None:
            continue
        present.add(sched["schedule_type"])
    missing = [letter for letter in REQUIRED_SCHEDULES if letter not in present]
    return missing  # REQUIRED_SCHEDULES already sorted A..J


def latest_schedule(case_id: str, schedule_type: str) -> dict | None:
    """Return the most-recent unsuperseded schedule of a given type for a case."""
    for sched in store.schedules.values():
        if (
            sched["case_id"] == case_id
            and sched["schedule_type"] == schedule_type
            and sched.get("superseded_by_id") is None
        ):
            return sched
    return None


# --------------------------------------------------------------------------
# total_unsecured_pool — sum of allowed GENERAL_UNSECURED claims for a case.
# --------------------------------------------------------------------------
def compute_total_unsecured_pool(case_id: str) -> int:
    total = 0
    for claim in store.claims.values():
        if (
            claim["case_id"] == case_id
            and claim["claim_class"] == "GENERAL_UNSECURED"
            and claim["status"] == "ALLOWED"
        ):
            total += claim["amount_cents"]
    return total


# --------------------------------------------------------------------------
# means_test — average last 6 months of Schedule I (round half-up only on the
# division step), build a MeansTestResult.
# --------------------------------------------------------------------------
def _state_median_lookup(state_code: str, household_size: int) -> int:
    key = (state_code, household_size)
    if key in STATE_MEDIAN_TABLE:
        return STATE_MEDIAN_TABLE[key]
    # Documented fallback: single-person vs two-person; multi-person households
    # not enumerated also use these defaults (two-person fallback for >=2).
    if household_size == 1:
        return DEFAULT_STATE_MEDIAN_1
    return DEFAULT_STATE_MEDIAN_2


def run_means_test(case_id: str) -> dict:
    """Execute the means-test calculation and return the result dict.

    Caller is responsible for persisting the result and updating
    Case.means_test_result_id.
    """
    case = store.cases[case_id]
    debtor = store.debtors[case["debtor_id"]]

    schedule_i = latest_schedule(case_id, "I")
    schedule_j = latest_schedule(case_id, "J")

    income_lines = schedule_i["line_items"] if schedule_i else []
    expense_lines = schedule_j["line_items"] if schedule_j else []

    # "Most recent 6 months of income line items" — take the last six entries.
    last_six = income_lines[-6:] if len(income_lines) >= 1 else []
    raw_six_month_sum_cents = sum(int(line.get("amount_cents", 0)) for line in last_six)

    # Round half-up on the division step. If there are fewer than 6 entries we
    # still divide by 6 per the formula (it averages over a fixed 6-month window).
    current_monthly_income_cents = round_half_up_int(raw_six_month_sum_cents, 6)
    cmi_annualized_cents = current_monthly_income_cents * 12

    state_median_annual_cents = _state_median_lookup(debtor["state_code"], debtor["household_size"])
    presumption_of_abuse = cmi_annualized_cents > state_median_annual_cents  # strict >

    allowed_monthly_expenses_cents = sum(int(line.get("amount_cents", 0)) for line in expense_lines)
    disposable_monthly_income_cents = max(
        0, current_monthly_income_cents - allowed_monthly_expenses_cents
    )
    required_plan_months = 60 if presumption_of_abuse else 36
    minimum_plan_total_cents = disposable_monthly_income_cents * required_plan_months

    return {
        "current_monthly_income_cents": current_monthly_income_cents,
        "cmi_annualized_cents": cmi_annualized_cents,
        "state_median_annual_cents": state_median_annual_cents,
        "presumption_of_abuse": presumption_of_abuse,
        "allowed_monthly_expenses_cents": allowed_monthly_expenses_cents,
        "disposable_monthly_income_cents": disposable_monthly_income_cents,
        "required_plan_months": required_plan_months,
        "minimum_plan_total_cents": minimum_plan_total_cents,
    }


# --------------------------------------------------------------------------
# trustee_payment_waterfall — allocate paid_to_date_cents across four buckets.
# --------------------------------------------------------------------------
def run_trustee_payment_waterfall(case_id: str, plan: dict) -> dict:
    """Return a breakdown of the waterfall allocation.

    The result is informational; the discharge cascade in case_engine consumes
    it to satisfy the invariant assertion that the parts sum to paid_to_date.
    """
    pool_cents = plan["paid_to_date_cents"]

    # Step 1: 10% admin fee, rounded half-up at this step.
    admin_fee_cents = round_half_up_int(pool_cents * ADMIN_FEE_RATE_NUMERATOR, ADMIN_FEE_RATE_DENOMINATOR)
    pool_cents -= admin_fee_cents

    allowed_claims_for_case = [
        c for c in store.claims.values() if c["case_id"] == case_id and c["status"] == "ALLOWED"
    ]
    # Priority bucket (Claim.id asc).
    priority_claims = sorted(
        [c for c in allowed_claims_for_case if c["claim_class"] == "PRIORITY"],
        key=lambda c: c["id"],
    )
    priority_takes: dict[str, int] = {}
    for claim in priority_claims:
        take = min(pool_cents, claim["amount_cents"])
        priority_takes[claim["id"]] = take
        pool_cents -= take

    # Secured arrears bucket (Claim.id asc).
    secured_claims = sorted(
        [c for c in allowed_claims_for_case if c["claim_class"] == "SECURED"],
        key=lambda c: c["id"],
    )
    secured_takes: dict[str, int] = {}
    for claim in secured_claims:
        take = min(pool_cents, claim["amount_cents"])
        secured_takes[claim["id"]] = take
        pool_cents -= take

    # General-unsecured pro-rata, Claim.id asc, residual to smallest Claim.id.
    unsecured_claims = sorted(
        [c for c in allowed_claims_for_case if c["claim_class"] == "GENERAL_UNSECURED"],
        key=lambda c: c["id"],
    )
    unsecured_shares: dict[str, int] = {}
    if unsecured_claims and pool_cents > 0:
        remaining = pool_cents
        total_unsecured = sum(c["amount_cents"] for c in unsecured_claims)
        if total_unsecured > 0:
            shares: list[int] = []
            for claim in unsecured_claims:
                share = round_half_up_int(remaining * claim["amount_cents"], total_unsecured)
                shares.append(share)
            residual = remaining - sum(shares)
            if residual != 0:
                shares[0] += residual  # smallest Claim.id (already sorted asc).
            for claim, share in zip(unsecured_claims, shares):
                unsecured_shares[claim["id"]] = share
        else:
            for claim in unsecured_claims:
                unsecured_shares[claim["id"]] = 0
    else:
        for claim in unsecured_claims:
            unsecured_shares[claim["id"]] = 0

    # Invariant assertion (parts must equal the original paid_to_date).
    total_priority = sum(priority_takes.values())
    total_secured = sum(secured_takes.values())
    total_unsecured = sum(unsecured_shares.values())
    assert admin_fee_cents + total_priority + total_secured + total_unsecured == plan["paid_to_date_cents"], (
        "waterfall invariant violation: parts do not sum to paid_to_date_cents"
    )

    return {
        "admin_fee_cents": admin_fee_cents,
        "priority_takes": priority_takes,
        "secured_takes": secured_takes,
        "unsecured_shares": unsecured_shares,
    }
