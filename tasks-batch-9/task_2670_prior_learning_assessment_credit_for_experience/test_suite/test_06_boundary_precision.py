"""Values that land exactly on a boundary, and their one-unit-off twins.

Each scenario pairs a figure sitting precisely on an inclusive threshold with a
neighbour one basis point or one cent away, so an exclusive comparison or a
truncating division flips exactly one of the pair.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_claim_dimensions,
    assert_fields_equal,
    assert_invoice_money,
    assert_line,
)
from test_helpers.constants import DEFAULT_PASS_THRESHOLD_BP
from test_helpers.test_users import COORDINATOR, make_assessor_headers, make_student_headers
from test_helpers.types import (
    Alignment,
    AssessmentStatus,
    AssignmentStatus,
    CourseLevel,
    FeeStatus,
    InvoiceLineKind,
    PortfolioStatus,
    PriorityTier,
    Recommendation,
    SourceType,
)


def _portfolio_program(client, program_code):
    return fx.new_program(
        client,
        program_code=program_code,
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
        allowed_source_types=[SourceType.PORTFOLIO],
    )


def _single_outcome_course(client, course_code, credits):
    return fx.new_course(
        client,
        course_code=course_code,
        department_code="CS",
        credits=credits,
        level=CourseLevel.LOWER,
        learning_outcomes=[f.outcome_payload("OC1", 10000, mastery_threshold_bp=7000)],
    )


def _waived_portfolio_claim(client, student_id, course, credits_requested):
    """A submitted PORTFOLIO claim with one PRIMARY artifact and a waived invoice.

    The waiver clears the fee gate without any payment arithmetic, so the scenario
    turns only on the rubric.
    """
    claim = fx.new_claim(
        client,
        student_id,
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=credits_requested,
    )
    portfolio = fx.new_portfolio(client, claim["id"], student_id)
    outcomes = fx.outcomes_of(client, course["id"])
    fx.attach_artifact(
        client, portfolio["id"], student_id, [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    fx.submit_portfolio(client, portfolio["id"], student_id)
    fx.submit_claim(client, claim["id"], student_id)
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.waive_invoice(
            invoice["id"], {"waive_reason": "Institutional pilot cohort"}, headers=COORDINATOR
        )
    )
    return {"claim": claim, "portfolio": portfolio, "outcomes": outcomes}


@pytest.fixture
def twin_courses_scored_identically(client):
    """Two courses with the same rubric and different weights, both fully scored.

    CS150 weights 8000/2000 and CS151 weights 7996/2004. Both assignments receive
    OC1 at 3 of 4 and OC2 at 2 of 4, so the only difference between the two
    verified figures is the weighting.
    """
    program = _portfolio_program(client, "BSCS")
    course_a = fx.new_course(
        client,
        course_code="CS150",
        department_code="CS",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=[
            f.outcome_payload("OC1", 8000, mastery_threshold_bp=7000),
            f.outcome_payload("OC2", 2000, mastery_threshold_bp=7000),
        ],
    )
    course_b = fx.new_course(
        client,
        course_code="CS151",
        department_code="CS",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=[
            f.outcome_payload("OC1", 7996, mastery_threshold_bp=7000),
            f.outcome_payload("OC2", 2004, mastery_threshold_bp=7000),
        ],
    )
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=0, institutional_credits_earned=60
    )
    assessor = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    built = {}
    for key, course in (("a", course_a), ("b", course_b)):
        parts = _waived_portfolio_claim(client, student["id"], course, 6)
        assignment = fx.assign_assessor(client, parts["claim"]["id"], assessor["id"])
        fx.accept_assignment(client, assignment["id"], assessor["id"])
        scores = fx.score_all_outcomes(
            client, assignment["id"], assessor["id"], parts["outcomes"], [3, 2]
        )
        built[key] = {
            "claim": parts["claim"],
            "portfolio": parts["portfolio"],
            "assignment": assignment,
            "scores": scores,
        }
    built["assessor"] = assessor
    built["program"] = program
    return built


def test_verified_coverage_landing_exactly_on_the_pass_threshold_passes(
    client, twin_courses_scored_identically
):
    """Weights 8000/2000 over a 3-and-2 rubric make exactly 7000, which passes.

    PRD: "`score_ratio_bp` is `points_awarded` multiplied by 10000, divided by 4,
    rounded half up — so 0 points is 0, 1 point is 2500, 2 points is 5000, 3 points
    is 7500 and 4 points is 10000." "The computed recommendation is `PASS` when
    `verified_coverage_bp` is at least the effective threshold and `FAIL` otherwise;
    the comparison is inclusive, so coverage landing exactly on the threshold
    passes."

    Design: Difficulty/boundary_precision_check/verified_coverage_exactly_at_pass_threshold_passes_while_6999_twin_fails
    """
    side = twin_courses_scored_identically["a"]
    assert len(side["scores"]) == 2, "one rubric score per learning outcome"
    by_points = {score["points_awarded"]: score for score in side["scores"]}
    assert_fields_equal(
        by_points[3], points_possible=4, score_ratio_bp=7500, outcome_met=True
    )
    assert_fields_equal(
        by_points[2], points_possible=4, score_ratio_bp=5000, outcome_met=False
    )

    completed = validate_success(
        client.complete_assignment(
            side["assignment"]["id"],
            {"recommendation": Recommendation.PASS},
            headers=make_assessor_headers(twin_courses_scored_identically["assessor"]["id"]),
        )
    )
    # (8000 * 7500 + 2000 * 5000) / 10000 == 7000, exactly the default threshold.
    assert_fields_equal(
        completed,
        status=AssignmentStatus.SCORING_COMPLETE,
        verified_coverage_bp=DEFAULT_PASS_THRESHOLD_BP,
        recommendation=Recommendation.PASS,
    )

    claim = get_success_data(client.get_claim(side["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.SCORED)
    assert_fields_equal(
        claim, verified_coverage_bp=7000, assessor_recommendation=Recommendation.PASS
    )

    portfolio = get_success_data(
        client.get_portfolio(side["portfolio"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(
        portfolio, status=PortfolioStatus.LOCKED, verified_coverage_bp=7000
    )


def test_the_one_basis_point_short_twin_is_refused_a_pass(
    client, twin_courses_scored_identically
):
    """Weights 7996/2004 over the same rubric make 6999, which is a FAIL.

    PRD: "Those products are summed exactly, as integers, and only then divided by
    10000 and rounded half up to yield `verified_coverage_bp`." "the submitted
    `recommendation` agrees with the recommendation the server computes for itself,
    or the request is `ERR_RECOMMENDATION_INCONSISTENT`."

    Design: Difficulty/boundary_precision_check/verified_coverage_exactly_at_pass_threshold_passes_while_6999_twin_fails
    """
    twin = twin_courses_scored_identically["b"]
    assessor_headers = make_assessor_headers(
        twin_courses_scored_identically["assessor"]["id"]
    )

    refused = client.complete_assignment(
        twin["assignment"]["id"], {"recommendation": Recommendation.PASS}, headers=assessor_headers
    )
    validate_error(refused, ApiErrorId.ERR_RECOMMENDATION_INCONSISTENT, 422)

    held = get_success_data(
        client.get_assignment(twin["assignment"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(held, status=AssignmentStatus.ACCEPTED)
    still_open = get_success_data(client.get_claim(twin["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(still_open, assessment_status=AssessmentStatus.UNDER_ASSESSMENT)

    # (7996 * 7500 + 2004 * 5000) / 10000 == 6999, one basis point short.
    completed = validate_success(
        client.complete_assignment(
            twin["assignment"]["id"],
            {"recommendation": Recommendation.FAIL},
            headers=assessor_headers,
        )
    )
    assert_fields_equal(
        completed, verified_coverage_bp=6999, recommendation=Recommendation.FAIL
    )
    assert DEFAULT_PASS_THRESHOLD_BP - completed["verified_coverage_bp"] == 1

    claim = get_success_data(client.get_claim(twin["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.SCORED)
    assert_fields_equal(
        claim, verified_coverage_bp=6999, assessor_recommendation=Recommendation.FAIL
    )


@pytest.fixture
def three_invoices_around_the_discount_boundary(client):
    """Three portfolio claims priced at 22500, 25000 and 28125 cents of subtotal.

    Each portfolio holds exactly one artifact, so the artifact tier surcharge is 0
    on all three and the subtotal is driven only by credits and the rush flag.
    """
    program = _portfolio_program(client, "BSCSFEE")
    below = _single_outcome_course(client, "CS203", 3)
    at_boundary = _single_outcome_course(client, "CS204", 4)
    rushed = _single_outcome_course(client, "CS205", 3)
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=0, institutional_credits_earned=60
    )

    def build(course, credits_requested, rush_requested):
        claim = fx.new_claim(
            client,
            student["id"],
            course["id"],
            source_type=SourceType.PORTFOLIO,
            credits_requested=credits_requested,
            rush_requested=rush_requested,
        )
        portfolio = fx.new_portfolio(client, claim["id"], student["id"])
        outcomes = fx.outcomes_of(client, course["id"])
        fx.attach_artifact(
            client,
            portfolio["id"],
            student["id"],
            [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)],
        )
        fx.submit_portfolio(client, portfolio["id"], student["id"])
        return claim

    claim_below = build(below, 3, False)
    fx.submit_claim(client, claim_below["id"], student["id"])
    claim_at = build(at_boundary, 4, False)
    fx.submit_claim(client, claim_at["id"], student["id"])
    claim_rushed = build(rushed, 3, True)
    return {
        "student": student,
        "below": claim_below,
        "at_boundary": claim_at,
        "rushed": claim_rushed,
    }


def test_the_discount_tier_boundary_is_inclusive_at_25000_cents(
    client, three_invoices_around_the_discount_boundary
):
    """A subtotal of exactly 25000 earns the higher tier, 22500 the lower one.

    PRD: "A subtotal of at least 25000 cents earns `discount_bp` of 1000; a subtotal
    of at least 10000 but below 25000 earns 500; anything below 10000 earns 0."

    Design: Difficulty/boundary_precision_check/discount_tier_boundary_at_exactly_25000_cents_and_half_cent_round_half_up
    """
    scenario = three_invoices_around_the_discount_boundary

    # PORTFOLIO base 15000 plus 2500 per credit over 3 credits.
    lower = fx.invoice_for_claim(client, scenario["below"]["id"])
    assert_invoice_money(
        lower,
        subtotal_cents=22500,
        discount_bp=500,
        discount_cents=1125,
        total_cents=21375,
        balance_due_cents=21375,
    )
    assert lower["aid_eligible"] is False

    # One more credit lifts the subtotal onto the boundary exactly.
    upper = fx.invoice_for_claim(client, scenario["at_boundary"]["id"])
    assert_invoice_money(
        upper,
        subtotal_cents=25000,
        discount_bp=1000,
        discount_cents=2500,
        total_cents=22500,
        balance_due_cents=22500,
    )
    assert upper["aid_eligible"] is False
    assert upper["total_cents"] - lower["total_cents"] == 1125, (
        "the larger tier discount must not invert the ordering at this boundary"
    )

    for claim_key in ("below", "at_boundary"):
        claim = get_success_data(
            client.get_claim(scenario[claim_key]["id"], headers=COORDINATOR)
        )
        assert_claim_dimensions(claim, fee_status=FeeStatus.INVOICED)


def test_a_half_cent_discount_rounds_half_up_to_the_larger_cent(
    client, three_invoices_around_the_discount_boundary
):
    """28125 cents at 1000 basis points is 2812.5, which resolves to 2813.

    PRD: "each line is rounded half up to whole cents before any summation, and the
    rounded lines are then added". ""Round half up" means that a value exactly
    halfway between two representable results resolves to the larger magnitude in
    the positive direction".

    Design: Difficulty/boundary_precision_check/discount_tier_boundary_at_exactly_25000_cents_and_half_cent_round_half_up
    """
    scenario = three_invoices_around_the_discount_boundary
    submitted = validate_success(
        client.submit_claim(
            scenario["rushed"]["id"], headers=make_student_headers(scenario["student"]["id"])
        )
    )
    assert_fields_equal(submitted, priority_tier=PriorityTier.EXPEDITED)

    response = client.list_invoices({"claim_id": scenario["rushed"]["id"]}, headers=COORDINATOR)
    rows, _meta = validate_paginated(response)
    assert len(rows) == 1, "exactly one invoice per claim"
    invoice = rows[0]

    # Rush is 2500 basis points of base plus per-credit: (15000 + 7500) * 2500 / 10000.
    assert_line(invoice, InvoiceLineKind.RUSH_SURCHARGE, 5625)
    assert_invoice_money(
        invoice,
        subtotal_cents=28125,
        discount_bp=1000,
        discount_cents=2813,
        total_cents=25312,
        balance_due_cents=25312,
    )
    assert invoice["aid_eligible"] is False

    claim = get_success_data(
        client.get_claim(scenario["rushed"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(claim, fee_status=FeeStatus.INVOICED)
