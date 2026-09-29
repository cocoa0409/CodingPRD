"""Blocks whose cause lives on a row the request never names.

In both scenarios every field of the entity being written is in order; the
refusal comes from a second or third aggregate reached by reference.
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
    assert_ledger,
)
from test_helpers.test_users import COORDINATOR, REGISTRAR, make_student_headers
from test_helpers.types import (
    Alignment,
    AssessmentStatus,
    AssessorStatus,
    AssignmentStatus,
    CourseLevel,
    CreditStatus,
    FeeStatus,
    PaymentMethod,
    ProgramStatus,
    Recommendation,
    SourceType,
)


@pytest.fixture
def partially_paid_claim_and_an_idle_assessor(client):
    """A clean SUBMITTED claim, an idle eligible assessor, and 500 cents outstanding.

    The invoice totals 22500 and 22000 has been paid, so the only obstacle to the
    assignment is a `PARTIALLY_PAID` fee status on a different aggregate.
    """
    program = fx.new_program(
        client,
        program_code="BSCSGATE",
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
        allowed_source_types=[SourceType.PORTFOLIO],
    )
    course = fx.new_course(
        client,
        course_code="CS204",
        department_code="CS",
        credits=4,
        level=CourseLevel.LOWER,
        learning_outcomes=[f.outcome_payload("OC1", 10000, mastery_threshold_bp=7000)],
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
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=4,
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
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.pay_invoice(
            invoice["id"],
            f.payment_payload(22000, PaymentMethod.CARD),
            headers=make_student_headers(student["id"]),
        )
    )
    return {
        "student": student,
        "assessor": assessor,
        "claim": claim,
        "invoice": invoice,
    }


def test_five_hundred_cents_outstanding_on_the_invoice_blocks_the_assignment(
    client, partially_paid_claim_and_an_idle_assessor
):
    """Nothing on the claim or the assessor objects; the invoice does.

    PRD: "**Assessment fee settled.** The claim's invoice `fee_status` is `PAID` or
    `WAIVED` before an assessor may be assigned. Failure:
    `ERR_ASSESSMENT_FEE_UNPAID` (402). Applies to creating an assessor assignment."

    Design: Difficulty/cross_entity_state_dependency/assessor_assignment_gated_by_fee_status_on_a_separate_invoice_aggregate
    """
    scenario = partially_paid_claim_and_an_idle_assessor
    invoice = get_success_data(
        client.get_invoice(scenario["invoice"]["id"], headers=COORDINATOR)
    )
    # PORTFOLIO base 15000 plus 2500 per credit over 4 credits, discounted 1000 bp.
    assert_invoice_money(
        invoice,
        subtotal_cents=25000,
        discount_bp=1000,
        total_cents=22500,
        paid_cents=22000,
        balance_due_cents=500,
    )

    claim_before = get_success_data(
        client.get_claim(scenario["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(
        claim_before,
        assessment_status=AssessmentStatus.SUBMITTED,
        fee_status=FeeStatus.PARTIALLY_PAID,
    )
    assessor_before = get_success_data(
        client.get_assessor(scenario["assessor"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(
        assessor_before, status=AssessorStatus.ACTIVE, active_assignment_count=0
    )

    response = client.create_assignment(
        scenario["claim"]["id"], {"assessor_id": scenario["assessor"]["id"]}, headers=COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_FEE_UNPAID, 402)

    listing = client.list_assignments({"claim_id": scenario["claim"]["id"]}, headers=COORDINATOR)
    rows, _meta = validate_paginated(listing)
    assert rows == [], "a refused assignment must not create a row, got %d" % len(rows)

    assessor_after = get_success_data(
        client.get_assessor(scenario["assessor"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(assessor_after, active_assignment_count=0)
    claim_after = get_success_data(
        client.get_claim(scenario["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(claim_after, assessment_status=AssessmentStatus.SUBMITTED)


def test_settling_the_remainder_lets_the_identical_assignment_through(
    client, partially_paid_claim_and_an_idle_assessor
):
    """Paying the last 500 cents changes nothing else and unblocks the gate.

    PRD: "The claim's invoice `fee_status` is `PAID` or `WAIVED` before an assessor
    may be assigned." "Resource creation returns HTTP 201, every other successful
    operation returns HTTP 200, and the one deletion returns HTTP 204 with no body."

    Design: Difficulty/cross_entity_state_dependency/assessor_assignment_gated_by_fee_status_on_a_separate_invoice_aggregate
    """
    scenario = partially_paid_claim_and_an_idle_assessor
    settled = get_success_data(
        client.pay_invoice(
            scenario["invoice"]["id"],
            f.payment_payload(500, PaymentMethod.CARD),
            headers=make_student_headers(scenario["student"]["id"]),
        )
    )
    assert_invoice_money(settled, paid_cents=22500, balance_due_cents=0)
    paid_claim = get_success_data(
        client.get_claim(scenario["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(paid_claim, fee_status=FeeStatus.PAID)

    assignment = validate_success(
        client.create_assignment(
            scenario["claim"]["id"],
            {"assessor_id": scenario["assessor"]["id"]},
            headers=COORDINATOR,
        ),
        expected_status=201,
    )
    assert_fields_equal(assignment, status=AssignmentStatus.ASSIGNED)

    assessor = get_success_data(
        client.get_assessor(scenario["assessor"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(assessor, active_assignment_count=1)


@pytest.fixture
def awarded_claim_under_a_deactivated_programme(client):
    """An AWARDED claim whose student's programme was deactivated after the award.

    The claim row carries no `program_id` at all, so the blocking fact is two
    references away: claim to student to programme.
    """
    program = fx.new_program(
        client,
        program_code="BSCSFLIP",
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
        allowed_source_types=[SourceType.PORTFOLIO],
    )
    course = fx.new_course(
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
        client,
        portfolio["id"],
        student["id"],
        [f.mapping(outcome["id"], Alignment.PRIMARY) for outcome in outcomes],
    )
    fx.submit_portfolio(client, portfolio["id"], student["id"])
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.waive_invoice(
            invoice["id"], {"waive_reason": "Veteran fee waiver"}, headers=COORDINATOR
        )
    )
    fx.scored_claim(
        client, claim["id"], assessor["id"], outcomes, [4, 4], Recommendation.PASS
    )
    awarded = fx.award_claim(client, claim["id"], student["id"], credits_awarded=6)
    deactivated = get_success_data(
        client.patch_program(
            program["id"], {"status": ProgramStatus.INACTIVE}, headers=COORDINATOR
        )
    )
    return {
        "program": deactivated,
        "student": student,
        "claim": awarded,
    }


def test_transcript_posting_is_blocked_by_the_programme_two_references_away(
    client, awarded_claim_under_a_deactivated_programme
):
    """The claim and the ledger both permit the posting; the programme does not.

    PRD: "**Enrolment and programme status.** The student's `enrollment_status` is
    `MATRICULATED` and the programme's `status` is `ACTIVE`. Failures:
    `ERR_STUDENT_NOT_MATRICULATED` and `ERR_PROGRAM_INACTIVE`, both 409. Applies to
    claim creation, claim submission, awarding and transcript posting." "An
    `INACTIVE` programme blocks both award and transcript posting for its students."

    Design: Difficulty/cross_entity_state_dependency/transcript_posting_blocked_two_hops_away_by_program_status_flip
    """
    scenario = awarded_claim_under_a_deactivated_programme
    assert_claim_dimensions(
        scenario["claim"],
        assessment_status=AssessmentStatus.AWARDED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    assert_fields_equal(
        scenario["claim"], credits_awarded=6, verified_coverage_bp=10000
    )
    assert_fields_equal(scenario["program"], status=ProgramStatus.INACTIVE)

    before = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    # Both later rungs would pass: 6 posted credits sit inside a posted-only
    # headroom of 30 and inside the non-residency allowance of 120 - 30.
    assert_ledger(before, reserved=0, awarded=6, posted=0)

    response = client.post_transcript(
        scenario["claim"]["id"], {"posted_term": "2026FA"}, headers=REGISTRAR
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_INACTIVE, 409)

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, credit_status=CreditStatus.NOT_POSTED)
    assert claim["posted_term"] is None, "posted_term must stay null after a refusal"
    assert claim["posted_credits"] is None, "posted_credits must stay null after a refusal"

    after = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(after, awarded=6, posted=0)


def test_reactivating_the_programme_lets_the_same_posting_through(
    client, awarded_claim_under_a_deactivated_programme
):
    """The credit moves from awarded to posted once the programme is ACTIVE again.

    PRD: "Any of `pla_max_credits`, `pla_max_pct_bp`, `pla_upper_division_max_credits`,
    `residency_min_credits`, `total_credits_required`, `pla_pass_threshold_bp`,
    `allowed_source_types` and `status` may be revised, each independently optional".

    Design: Difficulty/cross_entity_state_dependency/transcript_posting_blocked_two_hops_away_by_program_status_flip
    """
    scenario = awarded_claim_under_a_deactivated_programme
    reactivated = get_success_data(
        client.patch_program(
            scenario["program"]["id"], {"status": ProgramStatus.ACTIVE}, headers=COORDINATOR
        )
    )
    assert_fields_equal(reactivated, status=ProgramStatus.ACTIVE)

    posted = fx.post_transcript(client, scenario["claim"]["id"], posted_term="2026FA")
    assert_claim_dimensions(posted, credit_status=CreditStatus.POSTED)
    assert_fields_equal(posted, posted_term="2026FA", posted_credits=6)

    student = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, reserved=0, awarded=0, posted=6)
