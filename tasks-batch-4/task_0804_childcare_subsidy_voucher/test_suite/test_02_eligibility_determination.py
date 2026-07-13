"""Eligibility determination and the sliding-fee copay (PRD §3.2).

Depth coverage for the provisional/verified dual-variant copay and the income
boundary; breadth coverage for continuity-of-care, activity minimum, the missing
income-standard error, and finalize idempotency.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    publish_income_standard, create_family_with_activity, create_family,
    add_activity, open_determination, finalize_determination,
    create_approved_determination, api_client, TEST_USERS,
)

CW = TEST_USERS["caseworker_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / copay_provisional_vs_verified_across_determinations
# ---------------------------------------------------------------------------
def test_initial_determination_uses_gross_only_provisional_copay(api):
    """PRD §3.2: "When `determination_type` is `INITIAL`, the household's countable
    income is its gross income alone — `countable_income_cents` is set to
    `monthly_gross_income_cents` — and income eligibility is tested against the
    `entry_monthly_limit_cents`."
    PRD §3.2: "The `monthly_copay_cents` is then the household's
    `countable_income_cents` multiplied by that percentage, divided by 100, rounded
    half up to a whole cent."

    Design: Difficulty/dual_variant_calc/copay_provisional_vs_verified_across_determinations
    """
    publish_income_standard(entry_monthly_limit_cents=400_000,
                            exit_monthly_limit_cents=500_000)
    family = create_family_with_activity(gross=250_000, self_emp=100_000)
    det = create_approved_determination(family["id"], "INITIAL")
    assert det["countable_income_cents"] == 250_000
    assert det["monthly_copay_cents"] == 12_500
    assert det["result"] == "APPROVED"


def test_redetermination_uses_gross_plus_self_employment_verified_copay(api):
    """PRD §3.2: "When `determination_type` is `REDETERMINATION`, the countable income
    is the household's gross income plus its self-employment income —
    `countable_income_cents` is set to the sum of `monthly_gross_income_cents` and
    `monthly_self_employment_income_cents` — and income eligibility is tested against
    the more generous `exit_monthly_limit_cents`."
    PRD §3.2: "the applicable percentage is the first band whose ceiling the ratio does
    not exceed: a ratio at or below 0.50 draws 2 percent; above that but at or below
    0.75 draws 5 percent; above that but at or below 1.00 draws 8 percent; above that
    but at or below 1.25 draws 10 percent."

    Design: Difficulty/dual_variant_calc/copay_provisional_vs_verified_across_determinations
    """
    publish_income_standard(entry_monthly_limit_cents=400_000,
                            exit_monthly_limit_cents=500_000)
    family = create_family_with_activity(gross=250_000, self_emp=100_000)
    det = create_approved_determination(family["id"], "REDETERMINATION")
    assert det["countable_income_cents"] == 350_000
    assert det["monthly_copay_cents"] == 28_000
    assert det["result"] == "APPROVED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / income_eligibility_threshold_on_finalize
# ---------------------------------------------------------------------------
def test_income_exactly_at_entry_limit_is_eligible(api):
    """PRD §3.2: "`income_eligible` is true when `countable_income_cents` is less than
    or equal to the applicable limit."

    Design: Difficulty/boundary_precision_check/income_eligibility_threshold_on_finalize
    """
    publish_income_standard(entry_monthly_limit_cents=400_000)
    family = create_family_with_activity(gross=400_000, self_emp=0)
    det = create_approved_determination(family["id"], "INITIAL")
    assert det["income_eligible"] is True
    assert det["result"] == "APPROVED"


def test_income_one_cent_over_entry_limit_is_denied(api):
    """PRD §3.2: "`income_eligible` is true when `countable_income_cents` is less than
    or equal to the applicable limit."
    PRD §3.2: "If either test fails, the determination is finalized to `DENIED`: its
    `result` becomes `DENIED`, its `monthly_copay_cents` stays 0, the household
    `status` is set to `INELIGIBLE`, and cascade B fires"

    Design: Difficulty/boundary_precision_check/income_eligibility_threshold_on_finalize
    """
    publish_income_standard(entry_monthly_limit_cents=400_000)
    family = create_family_with_activity(gross=400_001, self_emp=0)
    det = create_approved_determination(family["id"], "INITIAL")
    assert det["income_eligible"] is False
    assert det["result"] == "DENIED"


# ---------------------------------------------------------------------------
# Corner: calculations / redetermination_continuity_above_entry_below_exit_eligible
# ---------------------------------------------------------------------------
def test_redetermination_income_between_entry_and_exit_is_eligible(api):
    """PRD §3.2: "income eligibility is tested against the more generous
    `exit_monthly_limit_cents`."
    PRD §3.2: "The copay percentage is chosen from a fixed band table keyed on the
    ratio of the household's `countable_income_cents` to the `entry_monthly_limit_cents`
    — note the denominator is always the entry limit, even in the redetermination
    variant."

    Design: Corner/calculations/redetermination_continuity_above_entry_below_exit_eligible
    """
    publish_income_standard(entry_monthly_limit_cents=400_000,
                            exit_monthly_limit_cents=500_000)
    family = create_family_with_activity(gross=450_000, self_emp=0,
                                         applicant_name="Cont Fam")
    det = create_approved_determination(family["id"], "REDETERMINATION")
    assert det["income_eligible"] is True
    assert det["result"] == "APPROVED"
    assert det["monthly_copay_cents"] == 45_000


# ---------------------------------------------------------------------------
# Corner: calculations / activity_hours_below_minimum_denies_determination
# ---------------------------------------------------------------------------
def test_activity_hours_below_minimum_denies_even_when_income_eligible(api):
    """PRD §3.2: "`activity_eligible` is true when the household's summed `weekly_hours`
    across all its parent activities is at least the minimum weekly activity threshold
    of 20 hours."
    PRD §3.2: "If either test fails, the determination is finalized to `DENIED`: its
    `result` becomes `DENIED`, its `monthly_copay_cents` stays 0, the household
    `status` is set to `INELIGIBLE`, and cascade B fires"

    Design: Corner/calculations/activity_hours_below_minimum_denies_determination
    """
    publish_income_standard(entry_monthly_limit_cents=400_000)
    family = create_family(gross=250_000, self_emp=0, applicant_name="LowHrs Fam")
    add_activity(family["id"], activity_type="JOB_SEARCH", weekly_hours=10)
    det = open_determination(family["id"], "INITIAL")
    finalized = finalize_determination(det["id"])
    assert finalized["activity_eligible"] is False
    assert finalized["income_eligible"] is True
    assert finalized["result"] == "DENIED"


# ---------------------------------------------------------------------------
# Corner: validations / no_income_standard_on_finalize_returns_422
# ---------------------------------------------------------------------------
def test_finalize_without_income_standard_returns_422(api):
    """PRD §3.2: "Finalization first requires that an `IncomeStandard` exist for the
    household's `household_size` and `state_code`; if none does, the request is
    rejected with `ERR_NO_INCOME_STANDARD`."

    Design: Corner/validations/no_income_standard_on_finalize_returns_422
    """
    family = create_family_with_activity(gross=250_000, self_emp=0,
                                         applicant_name="NoStd Fam")
    det = open_determination(family["id"], "INITIAL")
    resp = api.finalize_determination(det["id"], CW)
    validate_error(resp, ApiErrorId.ERR_NO_INCOME_STANDARD)


# ---------------------------------------------------------------------------
# Corner: state_machines / determination_finalize_twice_returns_409
# ---------------------------------------------------------------------------
def test_finalize_already_approved_determination_returns_409(api):
    """PRD §2.9: "For any transition endpoint, the target resource must be in a state
    from which the transition is defined; otherwise the request is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/determination_finalize_twice_returns_409
    """
    publish_income_standard(entry_monthly_limit_cents=400_000)
    family = create_family_with_activity(gross=250_000, self_emp=0)
    det = create_approved_determination(family["id"], "INITIAL")
    resp = api.finalize_determination(det["id"], CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
