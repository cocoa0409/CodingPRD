"""Cascades that travel through rows nobody named in the request.

A recommendation retirement walks down four entity types, and a withdrawal walks
sideways between sibling claims through the shared credit ledger.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_claim_dimensions,
    assert_fields_equal,
    assert_hold_reason,
    assert_invoice_money,
    assert_ledger,
)
from test_helpers.test_users import COORDINATOR, OFFICER_APPROVER, make_student_headers
from test_helpers.types import (
    Alignment,
    AssessmentStatus,
    AssignmentStatus,
    CourseLevel,
    FeeStatus,
    HoldReason,
    PaymentMethod,
    PortfolioStatus,
    RecommendationStatus,
    RevokeReason,
    RuleStatus,
    SourceType,
    SuspendReason,
)


def _outcome_pair():
    return [
        f.outcome_payload("OC1", 8000, mastery_threshold_bp=7000),
        f.outcome_payload("OC2", 2000, mastery_threshold_bp=7000),
    ]


@pytest.fixture
def exam_claim_under_assessment(client):
    """A paid exam claim under assessment, pinned to an APPROVED crosswalk rule."""
    program = fx.new_program(
        client,
        program_code="BSCS",
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
    )
    course = fx.new_course(
        client,
        course_code="CS150",
        department_code="CS",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=_outcome_pair(),
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
    recommendation = fx.published_recommendation(
        client,
        credential_code="CLEP-CS",
        source_type=SourceType.CREDIT_BY_EXAM,
        recommended_credits=6,
        recommended_level=CourseLevel.LOWER,
        effective_from="2026-01-01T00:00:00Z",
    )
    rule = fx.approved_rule(
        client,
        recommendation["id"],
        course["id"],
        awarded_credits=6,
        effective_from="2026-01-01T00:00:00Z",
    )
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.CREDIT_BY_EXAM,
        credits_requested=6,
        articulation_rule_id=rule["id"],
        attempt_date="2026-06-15T00:00:00Z",
    )
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.pay_invoice(
            invoice["id"],
            f.payment_payload(19000, PaymentMethod.CARD),
            headers=make_student_headers(student["id"]),
        )
    )
    assignment = fx.assign_assessor(client, claim["id"], assessor["id"])
    fx.accept_assignment(client, assignment["id"], assessor["id"])
    return {
        "student": student,
        "assessor": assessor,
        "recommendation": recommendation,
        "rule": rule,
        "claim": claim,
        "invoice": invoice,
        "assignment": assignment,
    }


def test_retiring_a_recommendation_suspends_its_rule_and_parks_the_claim(
    client, exam_claim_under_assessment
):
    """Hops one and two: the rule is suspended and the claim is held.

    PRD: "**Hop one:** every crosswalk rule of this recommendation whose `status`
    is `APPROVED` moves to `SUSPENDED` with `suspend_reason` set to
    `RECOMMENDATION_RETIRED`, and `approved_rule_count` falls to 0." "**Hop two,
    caused by hop one:** every claim pinned to a just-suspended rule whose
    `assessment_status` is `SUBMITTED` or `UNDER_ASSESSMENT` moves to
    `REVISION_REQUESTED` with `hold_reason` `ARTICULATION_SUSPENDED`, again without
    incrementing `revision_round`".

    Design: Difficulty/transitive_cascade/recommendation_retire_four_hop_cascade_to_invoice_and_student_ledger
    """
    invoice = get_success_data(
        client.get_invoice(exam_claim_under_assessment["invoice"]["id"], headers=COORDINATOR)
    )
    # A CREDIT_BY_EXAM base of 5000 plus 2500 per credit over 6 credits.
    assert_invoice_money(
        invoice,
        subtotal_cents=20000,
        discount_bp=500,
        discount_cents=1000,
        total_cents=19000,
        paid_cents=19000,
        balance_due_cents=0,
    )

    retired = validate_success(
        client.retire_recommendation(
            exam_claim_under_assessment["recommendation"]["id"],
            {"retire_reason": "Superseded by the 2027 national guide"},
            headers=OFFICER_APPROVER,
        )
    )
    assert_fields_equal(
        retired, status=RecommendationStatus.RETIRED, approved_rule_count=0
    )

    rule = get_success_data(
        client.get_rule(exam_claim_under_assessment["rule"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(
        rule, status=RuleStatus.SUSPENDED, suspend_reason=SuspendReason.RECOMMENDATION_RETIRED
    )

    claim = get_success_data(
        client.get_claim(exam_claim_under_assessment["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.REVISION_REQUESTED)
    assert_hold_reason(claim, HoldReason.ARTICULATION_SUSPENDED)
    assert_fields_equal(claim, revision_round=0)

    student = get_success_data(
        client.get_student(exam_claim_under_assessment["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, reserved=6)


def test_retirement_cascade_reaches_the_assessor_counter_and_the_cash_position(
    client, exam_claim_under_assessment
):
    """Hops three and four: the workload counter and the student's net cash.

    PRD: "**Hop three, caused by hop two:** each such claim's assignments in
    `ASSIGNED` or `ACCEPTED` move to `REVOKED` with `revoke_reason`
    `REVISION_REQUESTED`, decrementing each affected assessor's
    `active_assignment_count`, **and** each such claim's invoice whose `fee_status`
    is `INVOICED`, `PARTIALLY_PAID` or `PAID` is waived at the institution's expense
    — every cent of net paid cash is refunded, the whole `total_cents` is moved into
    `waived_cents`, `balance_due_cents` lands on 0, and `fee_status` becomes
    `WAIVED`." "**Hop four, caused by hop three:** each affected student's
    `fee_paid_net_cents` is recomputed from the refunded invoices".

    Design: Difficulty/transitive_cascade/recommendation_retire_four_hop_cascade_to_invoice_and_student_ledger
    """
    before = get_success_data(
        client.get_student(exam_claim_under_assessment["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(before, fee_paid_net_cents=19000)

    validate_success(
        client.retire_recommendation(
            exam_claim_under_assessment["recommendation"]["id"],
            {"retire_reason": "Superseded by the 2027 national guide"},
            headers=OFFICER_APPROVER,
        )
    )

    assignment = get_success_data(
        client.get_assignment(
            exam_claim_under_assessment["assignment"]["id"], headers=COORDINATOR
        )
    )
    assert_fields_equal(
        assignment,
        status=AssignmentStatus.REVOKED,
        revoke_reason=RevokeReason.REVISION_REQUESTED,
    )

    assessor = get_success_data(
        client.get_assessor(exam_claim_under_assessment["assessor"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(assessor, active_assignment_count=0)

    claim = get_success_data(
        client.get_claim(exam_claim_under_assessment["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(claim, fee_status=FeeStatus.WAIVED)

    invoice = get_success_data(
        client.get_invoice(exam_claim_under_assessment["invoice"]["id"], headers=COORDINATOR)
    )
    assert_invoice_money(
        invoice, refunded_cents=19000, waived_cents=19000, balance_due_cents=0
    )

    after = get_success_data(
        client.get_student(exam_claim_under_assessment["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(after, fee_paid_net_cents=0)


def _lower_cs_course(client, course_code, credits):
    return fx.new_course(
        client,
        course_code=course_code,
        department_code="CS",
        credits=credits,
        level=CourseLevel.LOWER,
        learning_outcomes=_outcome_pair(),
    )


def _portfolio_claim_on(client, student_id, course, credits_requested):
    """A PORTFOLIO claim whose portfolio holds one PRIMARY artifact on OC1.

    One PRIMARY mapping on the 8000-weight outcome carries provisional coverage of
    8000 basis points, clearing the 5000-point submission floor with a single
    artifact.
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
    return {
        "claim": get_success_data(client.get_claim(claim["id"], headers=COORDINATOR)),
        "portfolio": get_success_data(client.get_portfolio(portfolio["id"], headers=COORDINATOR)),
    }


@pytest.fixture
def one_reserving_claim_and_two_blocked(client):
    """A cap of 8 credits holding one 6-credit reservation and two parked claims.

    The 9-credit claim is created before the 6-credit one, so the waterfall's
    ``created_at`` ascending then ``claim_number`` ascending order reaches the
    oversized candidate first.
    """
    program = fx.new_program(
        client,
        program_code="BSCSCAP8",
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=8,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
        allowed_source_types=[SourceType.PORTFOLIO],
    )
    cs150 = _lower_cs_course(client, "CS150", 6)
    cs300 = _lower_cs_course(client, "CS300", 9)
    cs210 = _lower_cs_course(client, "CS210", 6)
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=0, institutional_credits_earned=60
    )
    claim_a = _portfolio_claim_on(client, student["id"], cs150, 6)
    claim_b = _portfolio_claim_on(client, student["id"], cs300, 9)
    claim_d = _portfolio_claim_on(client, student["id"], cs210, 6)
    return {
        "program": program,
        "student": student,
        "a": claim_a,
        "b": claim_b,
        "d": claim_d,
    }


def test_withdrawal_from_submitted_voids_the_portfolio_and_waives_an_unpaid_invoice(
    client, one_reserving_claim_and_two_blocked
):
    """The only reserving claim exits, releasing its 6 credits at zero retention.

    PRD: "In every case `assessment_status` becomes `WITHDRAWN`, the claim's
    portfolio when present moves to `VOIDED`, and the claim's `version`
    increments." "From `SUBMITTED`, `credits_requested` is subtracted from
    `pla_credits_reserved` (and from `pla_upper_division_committed` when the course
    is `UPPER`), the student's `version` increments, and the invoice is settled at a
    retention rate of zero basis points: all net cash is refunded, any remaining
    balance is absorbed into `waived_cents`, and `fee_status` becomes `REFUNDED` —
    or `WAIVED` when nothing had been paid at all."

    Design: Difficulty/transitive_cascade/withdraw_cascade_waterfall_skips_oversized_then_unblocks_smaller_claim
    """
    scenario = one_reserving_claim_and_two_blocked
    assert_fields_equal(scenario["program"], effective_pla_cap_credits=8)
    assert scenario["a"]["claim"]["claim_number"] == 1
    assert scenario["b"]["claim"]["claim_number"] == 2
    assert scenario["d"]["claim"]["claim_number"] == 3

    claim_a_id = scenario["a"]["claim"]["id"]
    invoice = fx.invoice_for_claim(client, claim_a_id)
    # PORTFOLIO base 15000 plus 2500 per credit over 6 credits, one artifact so no
    # tier surcharge, subtotal 30000 earning the 1000 basis point discount.
    assert_invoice_money(
        invoice, subtotal_cents=30000, total_cents=27000, paid_cents=0, balance_due_cents=27000
    )

    withdrawn = validate_success(
        client.withdraw_claim(
            claim_a_id,
            {"withdraw_reason": "Employer sponsorship fell through"},
            headers=make_student_headers(scenario["student"]["id"]),
        )
    )
    assert_claim_dimensions(
        withdrawn, assessment_status=AssessmentStatus.WITHDRAWN, fee_status=FeeStatus.WAIVED
    )

    portfolio = get_success_data(
        client.get_portfolio(scenario["a"]["portfolio"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(portfolio, status=PortfolioStatus.VOIDED)

    settled = get_success_data(client.get_invoice(invoice["id"], headers=COORDINATOR))
    assert_invoice_money(
        settled, refunded_cents=0, waived_cents=27000, balance_due_cents=0
    )

    student = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, fee_paid_net_cents=0)


def test_unblock_waterfall_skips_the_oversized_claim_and_continues(
    client, one_reserving_claim_and_two_blocked
):
    """Nine credits does not fit into eight, and the walk moves on rather than halting.

    PRD: "When either fails, the candidate stays in `CAP_BLOCKED` and **the walk
    continues to the next candidate rather than stopping.** This skip-and-continue
    behaviour is the rule and it matters: a single pass, first-fit by creation
    order, is what the system does, and a claim skipped for being too large is not
    revisited later in the same pass even if nothing else consumes the headroom it
    was denied."

    Design: Difficulty/transitive_cascade/withdraw_cascade_waterfall_skips_oversized_then_unblocks_smaller_claim
    """
    scenario = one_reserving_claim_and_two_blocked
    for parked in ("b", "d"):
        assert_claim_dimensions(
            scenario[parked]["claim"], assessment_status=AssessmentStatus.CAP_BLOCKED
        )
        assert_hold_reason(scenario[parked]["claim"], HoldReason.PLA_CAP)

    validate_success(
        client.withdraw_claim(
            scenario["a"]["claim"]["id"],
            {"withdraw_reason": "Employer sponsorship fell through"},
            headers=make_student_headers(scenario["student"]["id"]),
        )
    )

    oversized = get_success_data(
        client.get_claim(scenario["b"]["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(oversized, assessment_status=AssessmentStatus.CAP_BLOCKED)
    assert_hold_reason(oversized, HoldReason.PLA_CAP)

    smaller = get_success_data(
        client.get_claim(scenario["d"]["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(smaller, assessment_status=AssessmentStatus.SUBMITTED)
    assert_hold_reason(smaller, None)

    student = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, reserved=6, awarded=0, posted=0)
