"""Calculation tests: provisional/final award divergence, rubric weighting and
aggregation rounding, eligibility GPA source, ledger reconciliation, GPA boundaries.

All expected values are PRD-derived literals copied from the design indices.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    make_applicant_headers,
    award_payload,
    disburse_payload,
    create_renewal_review_payload,
    fixtures,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================
def test_provisional_and_final_award_diverge_on_same_applicant(api):
    """PRD §3.6: "The applicant's `requested_amount_cents` is multiplied by the
    selected multiplier and the product is rounded half up to whole cents; that
    rounded raw amount is then capped at the fund criteria's `max_award_cents`,
    taking the smaller of the two."
    PRD §3.7: "The award's already-committed `provisional_award_cents` is multiplied
    by the selected factor, the product is rounded half up to whole cents, and the
    rounded raw amount is then capped at the fund criteria's `max_award_cents`,
    taking the smaller of the two; the result becomes `final_award_cents`."
    PRD §3.7: "a `verified_gpa` of at least 3.00 but below 3.50 selects the mid
    factor of 0.90"

    Design: Difficulty/dual_variant_calc/award_provisional_vs_final_diverge_on_same_applicant
    """
    ctx = fixtures.setup_committed_award_with_stewardship(
        acknowledge=True,
        endowment_cents=5_000_000, min_gpa=3.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.20,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    award = ctx["award"]
    assert award["provisional_award_cents"] == 1_000_000
    assert award["final_award_cents"] is None, "final is null until disburse"

    disb = validate_success(
        api.disburse_award(award["id"], disburse_payload("INST1"), OFFICER), 201
    )
    award_after = validate_success(api.get_award(award["id"], ADMIN))
    assert award_after["provisional_award_cents"] == 1_000_000
    assert award_after["final_award_cents"] == 900_000
    assert disb["amount_cents"] == 900_000
    assert award_after["provisional_award_cents"] != award_after["final_award_cents"]


def test_eligibility_uses_verified_gpa_not_self_reported(api):
    """PRD §3.3: "Critically, the GPA test uses the registrar-verified GPA from the
    transcript (`verified_gpa`), never the applicant's `self_reported_gpa`."
    PRD §3.3: "The GPA criterion passes when the transcript's `verified_gpa` is at
    least the criteria's `min_gpa` (an inclusive comparison at the boundary)."
    PRD §3.3: "The read-only `eligibility_matched` flag is set to true exactly when
    `eligibility_failures` is empty, and false otherwise."

    Design: Difficulty/dual_variant_calc/eligibility_uses_verified_gpa_not_self_reported
    """
    fund = fixtures.create_open_fund(
        endowment_cents=2_000_000, min_gpa=3.50, max_award_cents=500_000,
    )
    applicant = fixtures.create_applicant(
        self_reported_gpa=3.90, residency_state="NY", field_of_study="Math",
    )
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=400_000, verified_gpa=3.20,
    )
    headers = make_applicant_headers(applicant["id"])
    submitted = validate_success(api.submit_application(app["id"], headers))
    assert submitted["eligibility_matched"] is False
    assert submitted["eligibility_failures"] == ["GPA"]
    assert submitted["status"] == "SUBMITTED"


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
def test_provisional_award_tier_multiply_then_cap_binds(api):
    """PRD §3.6: "a `rubric_total` of at least 75 but below 90 selects the mid
    multiplier of 0.80"
    PRD §3.6: "The applicant's `requested_amount_cents` is multiplied by the selected
    multiplier and the product is rounded half up to whole cents; that rounded raw
    amount is then capped at the fund criteria's `max_award_cents`, taking the
    smaller of the two."

    Design: Difficulty/combinatorial_formula/provisional_award_nonlinear_tier_times_request_capped
    """
    ctx = fixtures.setup_awarding_scored_application(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=700_000, verified_gpa=3.00,
        scores=[(80, 80, 80), (80, 80, 80)],
    )
    app = ctx["application"]
    assert app["rubric_total"] == 80.0
    award = validate_success(
        api.award_application(app["id"], award_payload(ctx["fund_version"]), ADMIN), 201
    )
    # raw = 700000 * 0.80 = 560000, capped to max_award_cents 500000.
    assert award["provisional_award_cents"] == 500_000


def test_rubric_total_sum_then_divide_then_round_once(api):
    """PRD §3.5: "On success the system computes the application's `rubric_total` as
    the mean of `weighted_value` over the rubric scores in `SUBMITTED` status: the
    submitted weighted values are summed, that sum is divided by the count of
    submitted scores, and the quotient is rounded half up to two decimal places — a
    single rounding applied only at the very end, after the division."

    Design: Difficulty/combinatorial_formula/rubric_total_sum_then_divide_then_round_once
    """
    # weighted_values: (95,90,85)->91.50 twice, (80,80,80)->80.00 once.
    # sum 263.00 / 3 = 87.6667 -> 87.67 (single final round).
    ctx = fixtures.setup_under_review_application(
        endowment_cents=9_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=500_000, verified_gpa=3.20,
        scores=[(95, 90, 85), (95, 90, 85), (80, 80, 80)],
    )
    app = ctx["application"]
    members = ctx["members"]
    from test_helpers import create_rubric_score_payload, make_committee_member_headers
    score_specs = [(95, 90, 85), (95, 90, 85), (80, 80, 80)]
    for (academic, need, essay), member in zip(score_specs, members):
        mh = make_committee_member_headers(member["id"])
        sp = create_rubric_score_payload(
            app["id"], member["id"],
            academic_score=academic, need_score=need, essay_score=essay,
        )
        score = validate_success(api.create_rubric_score(sp, mh), 201)
        validate_success(api.submit_rubric_score(score["id"], mh))
    scored = validate_success(api.finalize_scoring_application(app["id"], ADMIN))
    assert scored["rubric_total"] == 87.67
    assert scored["status"] == "SCORED"


# ===========================================================================
# Queue A — boundary_precision_check
# ===========================================================================
def test_eligibility_gpa_at_exact_min_is_inclusive(api):
    """PRD §3.3: "The GPA criterion passes when the transcript's `verified_gpa` is at
    least the criteria's `min_gpa` (an inclusive comparison at the boundary)."
    PRD §2.8: "All GPA threshold comparisons in this system are inclusive at the
    boundary: an applicant whose GPA exactly equals the relevant floor satisfies
    that floor."

    Design: Difficulty/boundary_precision_check/eligibility_gpa_at_exact_min_is_inclusive
    """
    fund = fixtures.create_open_fund(
        endowment_cents=1_000_000, min_gpa=3.00, max_award_cents=500_000,
    )
    applicant = fixtures.create_applicant(self_reported_gpa=3.00, residency_state="CA")
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=300_000, verified_gpa=3.00,
    )
    headers = make_applicant_headers(applicant["id"])
    submitted = validate_success(api.submit_application(app["id"], headers))
    assert submitted["eligibility_matched"] is True
    assert submitted["eligibility_failures"] == []


def test_finalize_scoring_blocked_when_quorum_count_below_two(api):
    """PRD §3.5: "It requires that the application is currently `UNDER_REVIEW`
    (otherwise `ERR_APPLICATION_STATE_INVALID`) and that the count of rubric scores
    in `SUBMITTED` status meets the scoring quorum of at least two submitted scores
    (otherwise `ERR_QUORUM_NOT_MET`)."

    Design: Difficulty/boundary_precision_check/finalize_scoring_blocked_when_quorum_count_below_two
    """
    ctx = fixtures.setup_under_review_application(
        endowment_cents=2_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=300_000, verified_gpa=3.00,
        scores=[(90, 90, 90), (90, 90, 90)],
    )
    app = ctx["application"]
    members = ctx["members"]
    # Submit only ONE score (one below SCORING_QUORUM=2).
    from test_helpers import create_rubric_score_payload, make_committee_member_headers
    m0 = members[0]
    mh = make_committee_member_headers(m0["id"])
    sp = create_rubric_score_payload(app["id"], m0["id"], academic_score=90, need_score=90, essay_score=90)
    score = validate_success(api.create_rubric_score(sp, mh), 201)
    validate_success(api.submit_rubric_score(score["id"], mh))

    from test_helpers import validate_error, ApiErrorId
    validate_error(
        api.finalize_scoring_application(app["id"], ADMIN),
        ApiErrorId.ERR_QUORUM_NOT_MET,
    )
    after = validate_success(api.get_application(app["id"], ADMIN))
    assert after["status"] == "UNDER_REVIEW"


# ===========================================================================
# Queue B — calculations / cross-cutting
# ===========================================================================
def test_rubric_weighted_value_correct_result(api):
    """PRD §3.4: "the `academic_score` is weighted at one half, the `need_score` at
    three tenths, and the `essay_score` at two tenths (these three weights sum to
    one), and the weighted sum is rounded half up to two decimal places."

    Design: Corner/calculations/rubric_weighted_value_correct_result
    """
    ctx = fixtures.setup_under_review_application(
        endowment_cents=2_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=100_000, verified_gpa=3.00,
        scores=[(90, 80, 70)],
        num_members=1,
    )
    app = ctx["application"]
    member = ctx["members"][0]
    from test_helpers import create_rubric_score_payload, make_committee_member_headers
    mh = make_committee_member_headers(member["id"])
    sp = create_rubric_score_payload(app["id"], member["id"], academic_score=90, need_score=80, essay_score=70)
    score = validate_success(api.create_rubric_score(sp, mh), 201)
    submitted = validate_success(api.submit_rubric_score(score["id"], mh))
    # 90*0.5 + 80*0.3 + 70*0.2 = 45 + 24 + 14 = 83.0
    assert submitted["weighted_value"] == 83.0


def test_available_cents_reconciled_after_award(api):
    """PRD §2.7: "The `available_cents` field equals the fund's `endowment_cents`
    minus its `committed_cents`."
    PRD §3.6: "As a cascade, the fund's `committed_cents` is increased by the award's
    `provisional_award_cents`, `available_cents` is recomputed, and the fund's
    `version` is incremented by one"

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_available_after_award
    """
    ctx = fixtures.setup_awarding_scored_application(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=500_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    app = ctx["application"]
    # rubric_total 91.5 -> tier_high 1.00 -> provisional 500000.
    award = validate_success(
        api.award_application(app["id"], award_payload(ctx["fund_version"]), ADMIN), 201
    )
    assert award["provisional_award_cents"] == 500_000
    fund = validate_success(api.get_fund(ctx["fund"]["id"], ADMIN))
    assert fund["committed_cents"] == 500_000
    assert fund["available_cents"] == 4_500_000


def test_renewal_floor_at_exact_boundary_meets_floor(api):
    """PRD §3.8: "the system computes its read-only `meets_floor` flag, which is true
    exactly when the `reported_gpa` is at least the award's frozen
    `renewal_gpa_floor` (an inclusive comparison at the boundary) and false
    otherwise."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_renewal_floor_at_exact_boundary
    """
    ctx = fixtures.setup_active_award(
        endowment_cents=9_000_000, min_gpa=3.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    award_id = ctx["award"]["id"]
    review = validate_success(
        api.create_renewal_review(create_renewal_review_payload(award_id, reported_gpa=3.00), ADMIN),
        201,
    )
    assert review["meets_floor"] is True
    award_after = validate_success(api.get_award(award_id, ADMIN))
    assert award_after["status"] == "RENEWAL_PENDING"
