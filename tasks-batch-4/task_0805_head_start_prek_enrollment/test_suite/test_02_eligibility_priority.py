"""Eligibility determination and priority scoring (PRD §3.3).

Depth coverage for the provisional/verified priority dual variant, the
combinatorial priority formula (MAX + tiered + cap), and the exact-100%-FPL income
boundary; breadth coverage for the standalone age-out-of-band submit rejection.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_program, create_cohort, create_family, create_application,
)

ES = TEST_USERS["enrollment_specialist_headers"]


def _draft_application(family_overrides, app_overrides, program_overrides=None,
                       cohort_overrides=None):
    program = create_program(**(program_overrides or {}))
    cohort = create_cohort(program["id"], **(cohort_overrides or {}))
    family = create_family(**family_overrides)
    app = create_application(program["id"], cohort["id"], family["id"], **app_overrides)
    return app


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / priority_points_provisional_vs_verified
# ---------------------------------------------------------------------------
def test_submit_computes_provisional_priority_points(api):
    """PRD §3.3: "The income component is tiered on `income_ratio`: 25 points when the
    ratio is at most 0.50, otherwise 18 points when it is at most 0.75, otherwise 10
    points when it is at most 1.00, otherwise 0 points."
    PRD §3.3: "The categorical component is the larger of two quantities: 40 points if
    the household is homeless (otherwise 0), and the points for the declared categorical
    program — 35 for `FOSTER`, 30 for `TANF`, 30 for `SSI`, 20 for `SNAP`, and 0 for
    `NONE`."
    PRD §3.3: "An age-priority component adds 10 points when the program's `program_type`
    is `HEAD_START` and the target cohort's `age_band` is `PRESCHOOL_4`."

    Design: Difficulty/dual_variant_calc/priority_points_provisional_vs_verified
    """
    app = _draft_application(
        family_overrides={"household_size": 3, "annual_income_cents": 800000,
                          "categorical_eligibility": "TANF", "homeless_status": False},
        app_overrides={"child_dob": "2022-01-10"})
    data = validate_success(api.submit_application(app["id"], ES))
    assert data["priority_points"] == 65, f"expected provisional 65, got {data['priority_points']}"


def test_verify_recomputes_verified_priority_points_and_eligible(api):
    """PRD §3.3: "The specialist supplies `verified_income_cents`, which the system
    records and then uses to recompute `income_ratio` and `eligibility_category` and to
    recompute `priority_points` using the verified variant."
    PRD §3.3: "Because the verified income can differ from the declared income, the
    tiered income band can shift and the verified score can differ from the provisional
    one, and the category can cross the 100%-of-FPL boundary."
    PRD §3.3: "When the recomputed `eligibility_category` is anything other than
    `OVER_INCOME`, the application advances from `SUBMITTED` to `ELIGIBLE`."

    Design: Difficulty/dual_variant_calc/priority_points_provisional_vs_verified
    """
    app = _draft_application(
        family_overrides={"household_size": 3, "annual_income_cents": 800000,
                          "categorical_eligibility": "TANF", "homeless_status": False},
        app_overrides={"child_dob": "2022-01-10"})
    validate_success(api.submit_application(app["id"], ES))
    data = validate_success(
        api.verify_eligibility(app["id"], {"verified_income_cents": 1600000}, ES))
    assert data["priority_points"] == 58, f"expected verified 58, got {data['priority_points']}"
    assert data["status"] == "ELIGIBLE"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / priority_points_max_and_tiered_and_cap
# ---------------------------------------------------------------------------
def test_priority_points_capped_at_ninety(api):
    """PRD §3.3: "The `priority_points` score is a weighted sum capped at a maximum of
    90 points."
    PRD §3.3: "The raw total is the sum of these five components, and `priority_points`
    is that raw total or 90, whichever is smaller."

    Design: Difficulty/combinatorial_formula/priority_points_max_and_tiered_and_cap
    """
    app = _draft_application(
        family_overrides={"household_size": 5, "annual_income_cents": 1000000,
                          "categorical_eligibility": "FOSTER", "homeless_status": True},
        app_overrides={"child_dob": "2022-03-05", "child_has_iep": True})
    data = validate_success(api.submit_application(app["id"], ES))
    assert data["priority_points"] == 90, f"expected capped 90, got {data['priority_points']}"


def test_homeless_takes_top_eligibility_precedence(api):
    """PRD §3.3: "The `eligibility_category` is then decided by strict precedence: if
    `homeless_status` is true the category is `HOMELESS`; otherwise if
    `categorical_eligibility` is anything other than `NONE` the category is `CATEGORICAL`;
    otherwise if `income_ratio` is at most 1.00 the category is `INCOME`; otherwise it is
    `OVER_INCOME`."

    Design: Difficulty/combinatorial_formula/priority_points_max_and_tiered_and_cap
    """
    app = _draft_application(
        family_overrides={"household_size": 5, "annual_income_cents": 1000000,
                          "categorical_eligibility": "FOSTER", "homeless_status": True},
        app_overrides={"child_dob": "2022-03-05", "child_has_iep": True})
    data = validate_success(api.submit_application(app["id"], ES))
    assert data["eligibility_category"] == "HOMELESS"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / income_ratio_exactly_100pct_fpl_is_income_eligible
# ---------------------------------------------------------------------------
def test_income_at_exactly_fpl_yields_ratio_one(api):
    """PRD §3.3: "The FPL threshold for a household is a base of 1,508,000 cents (fifteen
    thousand eighty dollars) plus 536,000 cents (five thousand three hundred sixty
    dollars) for each additional household member beyond the first — that is, the base
    plus the increment multiplied by one less than `household_size`."
    PRD §3.3: "The `income_ratio` is that income divided by the household's FPL threshold,
    rounded half-up to four decimals."

    Design: Difficulty/boundary_precision_check/income_ratio_exactly_100pct_fpl_is_income_eligible
    """
    app = _draft_application(
        family_overrides={"household_size": 4, "annual_income_cents": 3116000,
                          "categorical_eligibility": "NONE", "homeless_status": False},
        app_overrides={"child_dob": "2022-02-20"})
    data = validate_success(api.submit_application(app["id"], ES))
    assert data["income_ratio"] == 1.0, f"expected income_ratio 1.0, got {data['income_ratio']}"


def test_income_at_exactly_fpl_is_income_eligible(api):
    """PRD §3.3: "otherwise if `income_ratio` is at most 1.00 the category is `INCOME`;
    otherwise it is `OVER_INCOME`."

    Design: Difficulty/boundary_precision_check/income_ratio_exactly_100pct_fpl_is_income_eligible
    """
    app = _draft_application(
        family_overrides={"household_size": 4, "annual_income_cents": 3116000,
                          "categorical_eligibility": "NONE", "homeless_status": False},
        app_overrides={"child_dob": "2022-02-20"})
    data = validate_success(api.submit_application(app["id"], ES))
    assert data["eligibility_category"] == "INCOME"


# ---------------------------------------------------------------------------
# Corner: validations / submit_age_out_of_band_alone_returns_error
# ---------------------------------------------------------------------------
def test_submit_age_out_of_band_returns_error(api):
    """PRD §3.3: "Second, the child's computed `age_months_at_cutoff` must fall inside
    the target cohort's inclusive age band — that is, at least `min_age_months` and at
    most `max_age_months` — otherwise the submission is rejected with
    `ERR_AGE_OUT_OF_BAND`."

    Design: Corner/validations/submit_age_out_of_band_alone_returns_error
    """
    app = _draft_application(
        family_overrides={"categorical_eligibility": "TANF"},
        app_overrides={"child_first_name": "Ol", "child_dob": "2020-01-10"},
        cohort_overrides={"min_age_months": 48, "max_age_months": 60})
    resp = api.submit_application(app["id"], ES)
    validate_error(resp, ApiErrorId.ERR_AGE_OUT_OF_BAND)
