"""The two capacity variants and the two coverage variants.

Each pair of figures is computed from the same stored row by two different
rules, and the whole point of the pair is that the two answers diverge.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_audit,
    assert_claim_dimensions,
    assert_fields_equal,
    assert_ledger,
)
from test_helpers.test_users import COORDINATOR, REGISTRAR, make_assessor_headers
from test_helpers.types import (
    Alignment,
    AssessmentStatus,
    AuditStatus,
    CourseLevel,
    PortfolioStatus,
    Recommendation,
    SourceType,
)


def _bscs_program(client):
    """Programme BSCS: ceiling 30 credits, upper-division sub-cap 6."""
    return fx.new_program(
        client,
        program_code="BSCS",
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
    )


def _cs150(client):
    """Course CS150: 6 credits, LOWER, OC1 weighted 8000 and OC2 weighted 2000."""
    return fx.new_course(
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


@pytest.fixture
def reserved_but_unposted(client):
    """One 6-credit portfolio claim reserved, nothing awarded and nothing posted."""
    program = _bscs_program(client)
    course = _cs150(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=5, institutional_credits_earned=0
    )
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    portfolio = fx.new_portfolio(client, claim["id"], student["id"])
    fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[1]["id"], Alignment.SUPPORTING)]
    )
    fx.submit_portfolio(client, portfolio["id"], student["id"])
    fx.submit_claim(client, claim["id"], student["id"])
    return {
        "program": program,
        "course": course,
        "outcomes": outcomes,
        "student": student,
        "claim": claim,
        "portfolio": portfolio,
    }


def test_graduation_audit_reports_both_capacity_variants_diverging_by_the_reservation(
    client, reserved_but_unposted
):
    """One audit read carries both remaining-capacity figures at once.

    PRD: "It treats as already consumed the sum of `pla_credits_reserved`,
    `pla_credits_awarded` and `pla_credits_posted`, and reports the effective cap
    minus that sum." The other variant "ignores reserved and awarded-but-unposted
    credit entirely and reports the effective cap minus `pla_credits_posted`
    alone", and "Both numbers are surfaced side by side on the graduation audit,
    as `pla_cap_remaining_posted_only` and `pla_cap_remaining_reserved_inclusive`,
    so the divergence is directly observable."

    Design: Difficulty/dual_variant_calc/pla_capacity_reserved_inclusive_vs_posted_only_divergence
    """
    student_id = reserved_but_unposted["student"]["id"]

    student = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(student, reserved=6, awarded=0, posted=0)

    audit = validate_success(client.get_graduation_audit(student_id, headers=REGISTRAR))

    # The programme ceiling is min(30, floor(120 * 2500 / 10000)) = 30 and the
    # student's residency headroom is 120 - 30 - 5 = 85, so the effective cap is 30.
    assert_audit(
        audit,
        effective_pla_cap_credits=30,
        pla_credits_reserved=6,
        pla_credits_awarded=0,
        pla_credits_posted=0,
        pla_cap_remaining_reserved_inclusive=24,
        pla_cap_remaining_posted_only=30,
    )
    assert (
        audit["pla_cap_remaining_posted_only"]
        - audit["pla_cap_remaining_reserved_inclusive"]
        == 6
    ), "the two variants must diverge by exactly the live reservation of 6 credits"


def test_graduation_audit_counts_posted_credit_only_and_reports_residency_deficient(
    client, reserved_but_unposted
):
    """Reserved credit contributes nothing to the audit's applied-credit total.

    PRD: "It counts **posted credit only**: claims whose `credit_status` is
    `POSTED`." The audit "reports `total_credits_applied` as
    `institutional_credits_earned` plus `transfer_credits_accepted` plus
    `pla_credits_posted`", `residency_satisfied` requires that "the student's
    `institutional_credits_earned` must be at least the programme's
    `residency_min_credits`", and "When `residency_satisfied` is false the status
    is `RESIDENCY_DEFICIENT`, and no other condition is consulted."

    Design: Difficulty/dual_variant_calc/pla_capacity_reserved_inclusive_vs_posted_only_divergence
    """
    student_id = reserved_but_unposted["student"]["id"]

    audit = validate_success(client.get_graduation_audit(student_id, headers=REGISTRAR))

    assert_audit(
        audit,
        student_id=student_id,
        program_id=reserved_but_unposted["program"]["id"],
        institutional_credits_earned=0,
        transfer_credits_accepted=5,
        total_credits_applied=5,
        upper_division_pla_posted=0,
        upper_division_remaining=6,
        residency_satisfied=False,
        audit_status=AuditStatus.RESIDENCY_DEFICIENT,
    )


@pytest.fixture
def waived_portfolio_claim(client):
    """A submitted portfolio claim on CS150 whose invoice has been waived.

    The portfolio maps OC1 as PRIMARY and OC2 as SUPPORTING, which is the mapping
    pair whose self-reported coverage and assessor-verified coverage diverge.
    """
    program = _bscs_program(client)
    course = _cs150(client)
    outcomes = fx.outcomes_of(client, course["id"])
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
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    portfolio = fx.new_portfolio(client, claim["id"], student["id"])
    fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[1]["id"], Alignment.SUPPORTING)]
    )
    submitted_portfolio = fx.submit_portfolio(client, portfolio["id"], student["id"])
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.waive_invoice(invoice["id"], {"waive_reason": "HARDSHIP"}, headers=COORDINATOR)
    )
    return {
        "outcomes": outcomes,
        "student": student,
        "assessor": assessor,
        "claim": claim,
        "portfolio": submitted_portfolio,
    }


def test_self_reported_coverage_gives_primary_full_credit_and_supporting_half(
    client, waived_portfolio_claim
):
    """OC1 PRIMARY plus OC2 SUPPORTING self-reports 9000 basis points.

    PRD: "Each outcome earns a credit figure: 10000 basis points when any artifact
    of the portfolio maps that outcome with `alignment` `PRIMARY`; otherwise 5000
    basis points when any artifact maps it with `alignment` `SUPPORTING`;
    otherwise 0." On submission "`provisional_coverage_bp` is recomputed and
    frozen, and that same value is copied onto the parent claim's
    `provisional_coverage_bp`."

    Design: Difficulty/dual_variant_calc/coverage_provisional_self_reported_vs_assessor_verified_divergence
    """
    # 8000 * 10000 + 2000 * 5000 = 90000000, divided by 10000 is 9000.
    assert_fields_equal(waived_portfolio_claim["portfolio"], provisional_coverage_bp=9000)

    claim = get_success_data(
        client.get_claim(waived_portfolio_claim["claim"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(claim, provisional_coverage_bp=9000, verified_coverage_bp=None)


def test_assessor_verified_coverage_replaces_the_self_reported_credit_figures(
    client, waived_portfolio_claim
):
    """The same weights against rubric ratios 7500 and 5000 verify at 7000.

    PRD: "the outcome's contribution is its `weight_bp` multiplied by the
    `score_ratio_bp` of that outcome's rubric score on **this** assignment", and
    "`score_ratio_bp` is `points_awarded` multiplied by 10000, divided by 4,
    rounded half up". "The claim's `verified_coverage_bp` is copied from the
    assignment", and "The claim's portfolio, when present, advances `SUBMITTED →
    LOCKED` with `verified_coverage_bp` copied over from the completing
    assignment".

    Design: Difficulty/dual_variant_calc/coverage_provisional_self_reported_vs_assessor_verified_divergence
    """
    outcomes = waived_portfolio_claim["outcomes"]
    claim_id = waived_portfolio_claim["claim"]["id"]
    assessor_id = waived_portfolio_claim["assessor"]["id"]

    assignment = fx.assign_assessor(client, claim_id, assessor_id)
    fx.accept_assignment(client, assignment["id"], assessor_id)
    scores = fx.score_all_outcomes(client, assignment["id"], assessor_id, outcomes, [3, 2])

    # 3 of 4 is 7500 basis points, which clears the 7000 mastery threshold; 2 of 4
    # is 5000 basis points, which does not.
    assert_fields_equal(scores[0], points_possible=4, score_ratio_bp=7500, outcome_met=True)
    assert_fields_equal(scores[1], points_possible=4, score_ratio_bp=5000, outcome_met=False)

    completed = validate_success(
        client.complete_assignment(
            assignment["id"],
            {"recommendation": Recommendation.PASS},
            headers=make_assessor_headers(assessor_id),
        )
    )
    # 8000 * 7500 + 2000 * 5000 = 70000000, divided by 10000 is 7000.
    assert_fields_equal(completed, verified_coverage_bp=7000, recommendation=Recommendation.PASS)

    claim = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_fields_equal(
        claim,
        provisional_coverage_bp=9000,
        verified_coverage_bp=7000,
        assessor_recommendation=Recommendation.PASS,
    )
    assert claim["provisional_coverage_bp"] - claim["verified_coverage_bp"] == 2000, (
        "the self-reported and verified variants must diverge by 2000 basis points"
    )
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.SCORED)

    portfolio = get_success_data(
        client.get_portfolio(waived_portfolio_claim["portfolio"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(portfolio, status=PortfolioStatus.LOCKED, verified_coverage_bp=7000)
