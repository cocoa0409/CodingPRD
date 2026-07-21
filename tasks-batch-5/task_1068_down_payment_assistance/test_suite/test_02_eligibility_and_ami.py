"""AMI eligibility boundary, income-over-limit, income-limit prerequisite, and
the tiered minimum-contribution assistance calculation.

Difficulty instances covered (>=2 tests each):
  boundary_precision_check / ami_income_ceiling_inclusive_boundary
  combinatorial_formula / assistance_tiered_min_cap_mode_a
Corner instances covered (>=1 test each):
  validations / income_over_limit_on_eligible_review
  validations / submit_without_income_limit_returns_error
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.test_users import make_applicant_headers, make_case_manager_headers


def _build_under_review(api, *, annual_income_cents, reviewer_id="cm_reviewer"):
    """Program + income limit (hh 4, ami100 10,000,000) + applicant + property +
    application submitted and moved to UNDER_REVIEW. Returns (application, ids)."""
    program = fx.new_program(api)
    fx.new_income_limit(api, program["id"], household_size=4, ami_100_income_cents=10_000_000)
    applicant = fx.new_applicant(api, household_size=4, annual_income_cents=annual_income_cents)
    prop = fx.new_property(api, purchase_price_cents=30_000_000)
    application = fx.new_application(
        api, applicant["id"], program["id"], prop["id"],
        first_mortgage_amount_cents=24_000_000, buyer_contribution_cents=500_000,
    )
    fx.submit(api, application["id"], applicant["id"])
    fx.review(api, application["id"], "START", reviewer_id)
    return application, applicant


# --- boundary_precision_check / ami_income_ceiling_inclusive_boundary --------
def test_income_below_ceiling_is_eligible(api):
    """PRD 3.1: "the income ceiling is `ami_100_income_cents` multiplied by the
    program's `ami_limit_pct`, divided by 100, then floored to whole cents, and
    the applicant qualifies when their `annual_income_cents` is less than or
    equal to that ceiling."

    Design: Difficulty/boundary_precision_check/ami_income_ceiling_inclusive_boundary
    """
    # Ceiling = floor(10,000,000 * 80 / 100) = 8,000,000; income 7,999,999 (X-1).
    application, _ = _build_under_review(api, annual_income_cents=7_999_999)
    data = validate_success(
        api.review_application(application["id"], {"decision": "ELIGIBLE"}, make_case_manager_headers("cm_reviewer")),
        200,
    )
    assert data["status"] == "ELIGIBLE"


def test_income_exactly_at_ceiling_is_eligible(api):
    """PRD 3.1: "The boundary is inclusive — income exactly equal to the ceiling
    passes."
    PRD 3.1: "The **reporting figure** `ami_pct` is the applicant's
    `annual_income_cents` divided by that row's `ami_100_income_cents`,
    multiplied by 100, and rounded half-up to two decimal places".

    Design: Difficulty/boundary_precision_check/ami_income_ceiling_inclusive_boundary
    """
    # Income exactly 8,000,000 == ceiling; ami_pct == 80.00.
    application, _ = _build_under_review(api, annual_income_cents=8_000_000)
    data = validate_success(
        api.review_application(application["id"], {"decision": "ELIGIBLE"}, make_case_manager_headers("cm_reviewer")),
        200,
    )
    assert data["status"] == "ELIGIBLE"
    assert data["ami_pct"] == 80.00, f"expected ami_pct 80.00, got {data['ami_pct']}"


def test_income_one_cent_over_ceiling_rejected(api):
    """PRD 3.2: "a decision of `ELIGIBLE` moves an `UNDER_REVIEW` application to
    `ELIGIBLE`, but only if the eligibility test of Section 3.1 passes — the
    applicant's `annual_income_cents` must be at or below the floored income
    ceiling; otherwise the decision is rejected with `ERR_INCOME_OVER_LIMIT`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/ami_income_ceiling_inclusive_boundary
    """
    # Income 8,000,001 (X+1) just above the 8,000,000 ceiling.
    application, _ = _build_under_review(api, annual_income_cents=8_000_001)
    resp = api.review_application(application["id"], {"decision": "ELIGIBLE"}, make_case_manager_headers("cm_reviewer"))
    validate_error(resp, ApiErrorId.ERR_INCOME_OVER_LIMIT.value)


# --- Corner / income_over_limit_on_eligible_review --------------------------
def test_income_over_limit_on_eligible_review(api):
    """PRD 3.2: "a decision of `ELIGIBLE` moves an `UNDER_REVIEW` application to
    `ELIGIBLE`, but only if the eligibility test of Section 3.1 passes — the
    applicant's `annual_income_cents` must be at or below the floored income
    ceiling; otherwise the decision is rejected with `ERR_INCOME_OVER_LIMIT`
    (HTTP 422)."

    Design: Corner/validations/income_over_limit_on_eligible_review
    """
    application, _ = _build_under_review(api, annual_income_cents=8_000_001)
    resp = api.review_application(application["id"], {"decision": "ELIGIBLE"}, make_case_manager_headers("cm_reviewer"))
    validate_error(resp, ApiErrorId.ERR_INCOME_OVER_LIMIT.value)


# --- Corner / submit_without_income_limit_returns_error ---------------------
def test_submit_without_income_limit_returns_error(api):
    """PRD 3.2: "Submission requires the program to be `OPEN` ... and requires
    that an income-limit row already exists for the application's program and
    the applicant's household size; if none exists, the submission is rejected
    with `ERR_INCOME_LIMIT_UNDEFINED` (HTTP 422)."

    Design: Corner/validations/submit_without_income_limit_returns_error
    """
    program = fx.new_program(api)  # no income-limit rows defined
    applicant = fx.new_applicant(api, household_size=4, annual_income_cents=8_000_000)
    prop = fx.new_property(api, purchase_price_cents=30_000_000)
    application = fx.new_application(
        api, applicant["id"], program["id"], prop["id"],
        first_mortgage_amount_cents=24_000_000, buyer_contribution_cents=500_000,
    )
    resp = api.submit_application(application["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INCOME_LIMIT_UNDEFINED.value)


# --- combinatorial_formula / assistance_tiered_min_cap_mode_a ---------------
def _submit_mid_ami_application(api):
    """60% AMI (tier 1%), basis 20,000,000, first mortgage 15,000,000,
    stated contribution 100,000. Returns the SUBMITTED application."""
    program = fx.new_program(api, ami_limit_pct=80, max_assistance_cents=5_000_000)
    fx.new_income_limit(api, program["id"], household_size=4, ami_100_income_cents=10_000_000)
    applicant = fx.new_applicant(api, household_size=4, annual_income_cents=6_000_000)
    prop = fx.new_property(api, purchase_price_cents=20_000_000)
    application = fx.new_application(
        api, applicant["id"], program["id"], prop["id"],
        first_mortgage_amount_cents=15_000_000, buyer_contribution_cents=100_000,
    )
    return validate_success(
        api.submit_application(application["id"], make_applicant_headers(applicant["id"])), 200
    )


def test_assistance_tiered_ami_pct_and_status(api):
    """PRD 3.2: "On success the system computes the reporting `ami_pct` and the
    provisional `estimated_assistance_cents` (the provisional assistance
    calculation of Section 3.4) from the application's estimated inputs."
    PRD 3.1: "The **reporting figure** `ami_pct` is the applicant's
    `annual_income_cents` divided by that row's `ami_100_income_cents`,
    multiplied by 100, and rounded half-up to two decimal places".

    Design: Difficulty/combinatorial_formula/assistance_tiered_min_cap_mode_a
    """
    data = _submit_mid_ami_application(api)
    assert data["status"] == "SUBMITTED"
    assert data["ami_pct"] == 60.00, f"expected ami_pct 60.00, got {data['ami_pct']}"


def test_assistance_tiered_min_contribution_and_cap(api):
    """PRD 3.4: "First, a minimum-contribution tier is selected from the
    reporting `ami_pct`: at or below 50.00 the tier percentage is 0; above 50.00
    and at or below 65.00 it is 1 percent; above 65.00 and at or below 80.00 it
    is 3 percent. The required buyer contribution is the greater of the buyer's
    stated contribution and the tier percentage of the basis rounded up to the
    next whole cent (the tier percentage of the basis, divided by 100, taking
    the ceiling). The funding gap is then the basis minus the first-mortgage
    amount minus that required buyer contribution. The assistance is the funding
    gap floored at zero (never negative) and then capped at the program's
    `max_assistance_cents` — that is, the smaller of `max_assistance_cents` and
    the non-negative funding gap."

    Design: Difficulty/combinatorial_formula/assistance_tiered_min_cap_mode_a
    """
    # tier 1%: required = max(100000, ceil(20,000,000*1/100)=200000) = 200000;
    # gap = 20,000,000 - 15,000,000 - 200,000 = 4,800,000 (< 5,000,000 cap).
    data = _submit_mid_ami_application(api)
    assert data["estimated_assistance_cents"] == 4_800_000, (
        f"expected 4,800,000, got {data['estimated_assistance_cents']}"
    )
