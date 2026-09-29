"""Compensations that restore a ledger exactly yet do not undo everything.

A transcript reversal is an exact arithmetic inverse of a posting and still
releases only one of two parked claims. An appeal remand refunds a fixed 6000
cents and still leaves the invoice 600 cents short.
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
    assert_hold_reason,
    assert_instant,
    assert_invoice_money,
    assert_ledger,
    assert_line_absent,
)
from test_helpers.test_users import (
    COORDINATOR,
    REGISTRAR,
    make_reviewer_headers,
    make_student_headers,
)
from test_helpers.types import (
    Alignment,
    AppealStatus,
    AssessmentStatus,
    CourseLevel,
    CreditStatus,
    FeeStatus,
    HoldReason,
    InvoiceLineKind,
    PaymentMethod,
    Recommendation,
    SelectionReason,
    SourceType,
)


def _one_outcome_course(client, course_code, credits, level):
    return fx.new_course(
        client,
        course_code=course_code,
        department_code="CS",
        credits=credits,
        level=level,
        learning_outcomes=[f.outcome_payload("OC1", 10000, mastery_threshold_bp=7000)],
    )


def _submitted_portfolio_claim(client, student_id, course, credits_requested):
    """A PORTFOLIO claim carried as far as its own capacity allows.

    One PRIMARY artifact on the single 10000-weight outcome puts provisional
    coverage at 10000 basis points, well clear of the submission floor.
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
    submitted = fx.submit_claim(client, claim["id"], student_id)
    return {"claim": submitted, "portfolio": portfolio, "outcomes": outcomes}


@pytest.fixture
def posted_upper_claim_with_two_parked_siblings(client):
    """Six posted upper-division credits, one UPPER_DIVISION_CAP hold, one PLA_CAP hold.

    The programme ceiling is 12 credits and the upper-division sub-cap is 6, so the
    single posted claim exhausts the sub-cap outright while leaving 6 credits of
    reserved-inclusive headroom — enough for the 3-credit upper claim if the
    sub-cap ever frees, never enough for the 9-credit lower one.
    """
    program = fx.new_program(
        client,
        program_code="BSCSREV",
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=12,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
        allowed_source_types=[SourceType.PORTFOLIO],
    )
    cs400 = _one_outcome_course(client, "CS400", 6, CourseLevel.UPPER)
    cs410 = _one_outcome_course(client, "CS410", 3, CourseLevel.UPPER)
    cs150 = _one_outcome_course(client, "CS150", 9, CourseLevel.LOWER)
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=0, institutional_credits_earned=60
    )
    assessor = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=3,
        max_concurrent_assignments=3,
    )
    first = _submitted_portfolio_claim(client, student["id"], cs400, 6)
    invoice = fx.invoice_for_claim(client, first["claim"]["id"])
    get_success_data(
        client.waive_invoice(
            invoice["id"], {"waive_reason": "Employer-sponsored cohort"}, headers=COORDINATOR
        )
    )
    fx.scored_claim(
        client, first["claim"]["id"], assessor["id"], first["outcomes"], [4], Recommendation.PASS
    )
    fx.award_claim(client, first["claim"]["id"], student["id"], credits_awarded=6)
    posted = fx.post_transcript(client, first["claim"]["id"], posted_term="2026FA")
    upper_parked = _submitted_portfolio_claim(client, student["id"], cs410, 3)
    lower_parked = _submitted_portfolio_claim(client, student["id"], cs150, 9)
    return {
        "program": program,
        "student": student,
        "posted": posted,
        "upper_parked": upper_parked["claim"],
        "lower_parked": lower_parked["claim"],
    }


def test_reversal_restores_the_ledger_exactly_and_frees_only_the_upper_division_hold(
    client, posted_upper_claim_with_two_parked_siblings
):
    """The credit moves back one shelf and exactly one parked sibling comes free.

    PRD: "It sets `credit_status` to `REVERSED` and `posted_credits` to 0, subtracts
    the reversed credits from `pla_credits_posted` and returns them to
    `pla_credits_awarded`, and subtracts the upper-division portion from
    `pla_upper_division_committed`." "The reversal runs the cap unblock waterfall of
    §3.8 over the student's `CAP_BLOCKED` claims, but since reserved-inclusive
    headroom is unchanged, only claims blocked with `hold_reason`
    `UPPER_DIVISION_CAP` can actually come free there".

    Design: Difficulty/compensating_invariant/transcript_reversal_restores_ledger_exactly_and_unblocks_only_the_upper_division_hold
    """
    scenario = posted_upper_claim_with_two_parked_siblings
    assert_fields_equal(scenario["program"], effective_pla_cap_credits=12)
    before = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(
        before, reserved=0, awarded=0, posted=6, upper_division_committed=6
    )
    assert_claim_dimensions(
        scenario["upper_parked"], assessment_status=AssessmentStatus.CAP_BLOCKED
    )
    assert_hold_reason(scenario["upper_parked"], HoldReason.UPPER_DIVISION_CAP)
    assert_claim_dimensions(
        scenario["lower_parked"], assessment_status=AssessmentStatus.CAP_BLOCKED
    )
    assert_hold_reason(scenario["lower_parked"], HoldReason.PLA_CAP)

    reversed_claim = validate_success(
        client.reverse_transcript(
            scenario["posted"]["id"],
            {"reversal_reason": "Registrar found the term coding was wrong"},
            headers=REGISTRAR,
        )
    )
    assert_claim_dimensions(
        reversed_claim,
        assessment_status=AssessmentStatus.AWARDED,
        credit_status=CreditStatus.REVERSED,
    )
    assert_fields_equal(reversed_claim, posted_credits=0, credits_awarded=6)

    after = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    # The reversal subtracts the reversed claim's own 6 upper credits, and then the
    # waterfall re-reserves the freed 3-credit `UPPER` sibling, which S3.3 counts:
    # `pla_upper_division_committed` "aggregates ... the credits requested ... for
    # claims in `SUBMITTED`". The waterfall's own upper-division headroom test would
    # be inert within a pass if the re-reservation did not land on this counter, and
    # the cap-blocking cascade it mirrors takes `credits_requested` out of
    # `pla_upper_division_committed` when the course is `UPPER`.
    assert_ledger(after, posted=0, awarded=6, upper_division_committed=3)

    freed = get_success_data(
        client.get_claim(scenario["upper_parked"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(freed, assessment_status=AssessmentStatus.SUBMITTED)
    assert_hold_reason(freed, None)
    assert_ledger(after, reserved=3)


def test_the_pla_cap_hold_survives_the_reversal_and_the_re_posting(
    client, posted_upper_claim_with_two_parked_siblings
):
    """Nine credits never fit, and the re-posting now meets the sub-cap it vacated.

    PRD: "claims blocked with `hold_reason` `PLA_CAP` remain blocked." "A claim in
    `REVERSED` whose `assessment_status` is still `AWARDED` may be posted again, with
    the residency and posted-only capacity checks re-run from scratch and
    `posted_term` overwritten by the new value." "The posted-only capacity variant is
    the cap gate here, not the reserved-inclusive one, and a breach of it is
    `ERR_PLA_CAP_EXCEEDED`; for an `UPPER`-level course the upper-division sub-cap is
    re-checked too, with `ERR_UPPER_DIVISION_CAP_EXCEEDED`." "**Upper-division
    sub-cap.** For an `UPPER`-level course, `credits_awarded` is at most
    `pla_upper_division_max_credits` minus the student's
    `pla_upper_division_committed`. Failure: `ERR_UPPER_DIVISION_CAP_EXCEEDED` (409).
    Applies to awarding a claim and posting to the transcript."

    Design: Difficulty/compensating_invariant/transcript_reversal_restores_ledger_exactly_and_unblocks_only_the_upper_division_hold
    """
    scenario = posted_upper_claim_with_two_parked_siblings
    validate_success(
        client.reverse_transcript(
            scenario["posted"]["id"],
            {"reversal_reason": "Registrar found the term coding was wrong"},
            headers=REGISTRAR,
        )
    )

    # The waterfall re-reserved 3, so remaining is 12 - (3 + 6 + 0) == 3 < 9.
    still_parked = get_success_data(
        client.get_claim(scenario["lower_parked"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(still_parked, assessment_status=AssessmentStatus.CAP_BLOCKED)
    assert_hold_reason(still_parked, HoldReason.PLA_CAP)

    # Re-posting is permitted in principle, but rung 38's sub-cap "applies to awarding
    # a claim and posting to the transcript", and the waterfall has just handed 3 of
    # the programme's 6 upper-division credits to the freed sibling. Six no longer fit.
    refused = client.post_transcript(
        scenario["posted"]["id"], {"posted_term": "2027SP"}, headers=REGISTRAR
    )
    validate_error(refused, ApiErrorId.ERR_UPPER_DIVISION_CAP_EXCEEDED, 409)

    # A refusal is not a write: the credit dimension still reads as the reversal left it.
    held = get_success_data(
        client.get_claim(scenario["posted"]["id"], headers=REGISTRAR)
    )
    assert_claim_dimensions(
        held,
        assessment_status=AssessmentStatus.AWARDED,
        credit_status=CreditStatus.REVERSED,
    )
    assert_fields_equal(held, posted_credits=0, credits_awarded=6)

    student = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, reserved=3, awarded=6, posted=0, upper_division_committed=3)

    unchanged = get_success_data(
        client.get_claim(scenario["upper_parked"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(unchanged, assessment_status=AssessmentStatus.SUBMITTED)
    assert_hold_reason(unchanged, None)


@pytest.fixture
def paid_appeal_under_review(client):
    """A denied 6-credit portfolio claim under appeal, its invoice settled at 32400.

    The base invoice is 30000 of subtotal at the 1000 basis point tier, so 27000 is
    paid in full before assessment. Filing the appeal adds the 6000-cent line, which
    re-selects the tier from 36000 and lifts the total to 32400; the student tops up
    the 5400 difference so the reviewer-assignment fee gate opens.
    """
    program = fx.new_program(
        client,
        program_code="BSCSAPL",
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
    student_headers = make_student_headers(student["id"])
    scorer = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
        appeal_panel_member=False,
    )
    reviewer = fx.new_assessor(
        client,
        employee_number="E-9002",
        department_code="CS",
        credential_rank=3,
        max_concurrent_assignments=3,
        appeal_panel_member=True,
    )
    # A third in-department assessor guarantees the replacement pool is not empty
    # once the prior scorer is excluded.
    fx.new_assessor(
        client,
        employee_number="E-9003",
        department_code="CS",
        credential_rank=1,
        max_concurrent_assignments=3,
        appeal_panel_member=False,
    )
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    portfolio = fx.new_portfolio(client, claim["id"], student["id"])
    for outcome in outcomes:
        fx.attach_artifact(
            client, portfolio["id"], student["id"], [f.mapping(outcome["id"], Alignment.PRIMARY)]
        )
    fx.submit_portfolio(client, portfolio["id"], student["id"])
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.pay_invoice(
            invoice["id"], f.payment_payload(27000, PaymentMethod.CARD), headers=student_headers
        )
    )
    fx.scored_claim(
        client, claim["id"], scorer["id"], outcomes, [2, 2], Recommendation.FAIL
    )
    denied = get_success_data(
        client.deny_claim(
            claim["id"],
            {"denial_reason": "Coverage 5000 bp is below the 7000 bp threshold"},
            headers=COORDINATOR,
        )
    )
    appeal = get_success_data(
        client.create_appeal(
            {
                "claim_id": claim["id"],
                "grounds": "The assessor never opened the test report artifact",
            },
            headers=student_headers,
        )
    )
    get_success_data(
        client.pay_invoice(
            invoice["id"], f.payment_payload(5400, PaymentMethod.CARD), headers=student_headers
        )
    )
    get_success_data(
        client.assign_appeal_reviewer(
            appeal["id"], {"reviewer_assessor_id": reviewer["id"]}, headers=COORDINATOR
        )
    )
    return {
        "student": student,
        "claim": claim,
        "invoice": invoice,
        "appeal": appeal,
        "denied": denied,
        "scorer": scorer,
        "reviewer": reviewer,
    }


def test_the_remand_refunds_the_fixed_filing_fee_and_leaves_a_600_cent_residue(
    client, paid_appeal_under_review
):
    """Removing the appeal line removes the discount it earned, so 600 stays due.

    PRD: "exactly 6000 cents is refunded — `refunded_cents` rises by 6000, with no
    basis-point arithmetic applied to that figure." "when it falls short the
    `fee_status` stays `PARTIALLY_PAID` with the residue — precisely the discount the
    appeal line had earned — exposed in `balance_due_cents`. That positive residue is
    **not** swept to zero; only a negative balance is swept".

    Design: Difficulty/compensating_invariant/appeal_remand_fixed_refund_leaves_a_600_cent_discount_residue
    """
    scenario = paid_appeal_under_review
    assert_instant(
        scenario["denied"]["appeal_deadline_at"], "2026-08-15T00:00:00Z", "appeal_deadline_at"
    )
    before = get_success_data(client.get_invoice(scenario["invoice"]["id"], headers=COORDINATOR))
    # 15000 base plus 15000 per-credit plus the 6000 appeal line, tier 1000 bp.
    assert_invoice_money(
        before,
        subtotal_cents=36000,
        discount_bp=1000,
        discount_cents=3600,
        total_cents=32400,
        paid_cents=32400,
        refunded_cents=0,
        balance_due_cents=0,
    )
    claim_before = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(
        claim_before,
        assessment_status=AssessmentStatus.APPEAL_PENDING,
        fee_status=FeeStatus.PAID,
    )
    assert_fields_equal(claim_before, appeal_count=1)

    decided = validate_success(
        client.decide_appeal(
            scenario["appeal"]["id"],
            {"decision": AppealStatus.REMANDED, "decision_note": "Reassess with the full set"},
            headers=make_reviewer_headers(scenario["reviewer"]["id"]),
        )
    )
    assert_fields_equal(decided, status=AppealStatus.REMANDED)
    assert_instant(decided["decided_at"], "2026-08-01T00:00:00Z", "decided_at")

    after = get_success_data(client.get_invoice(scenario["invoice"]["id"], headers=COORDINATOR))
    assert_line_absent(after, InvoiceLineKind.APPEAL_FILING_FEE)
    assert_invoice_money(
        after,
        subtotal_cents=30000,
        discount_bp=1000,
        discount_cents=3000,
        total_cents=27000,
        paid_cents=32400,
        refunded_cents=6000,
        balance_due_cents=600,
        recompute_count=before["recompute_count"] + 1,
    )
    assert after["balance_due_cents"] == 3600 - 3000, (
        "the residue is exactly the discount the appeal line had earned"
    )
    claim_after = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim_after, fee_status=FeeStatus.PARTIALLY_PAID)

    student = get_success_data(client.get_student(scenario["student"]["id"], headers=COORDINATOR))
    assert_ledger(student, fee_paid_net_cents=26400)


def test_the_remand_reopens_the_assessment_and_the_residue_can_still_be_settled(
    client, paid_appeal_under_review
):
    """The claim returns to assessment behind a fresh assessor, and 600 clears it.

    PRD: "The claim's `assessment_status` returns to `UNDER_ASSESSMENT` and four
    fields are cleared to null: `assessor_recommendation`, `verified_coverage_bp`,
    `denial_reason` and `appeal_deadline_at`." "A replacement assignment is created
    through the selector, excluding every assessor ever assigned to this claim, with
    `selection_reason` `AUTO_REPLACEMENT`".

    Design: Difficulty/compensating_invariant/appeal_remand_fixed_refund_leaves_a_600_cent_discount_residue
    """
    scenario = paid_appeal_under_review
    validate_success(
        client.decide_appeal(
            scenario["appeal"]["id"],
            {"decision": AppealStatus.REMANDED, "decision_note": "Reassess with the full set"},
            headers=make_reviewer_headers(scenario["reviewer"]["id"]),
        )
    )

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.UNDER_ASSESSMENT)
    for field in (
        "assessor_recommendation",
        "verified_coverage_bp",
        "denial_reason",
        "appeal_deadline_at",
    ):
        assert claim[field] is None, "%s must be cleared by the remand, got %r" % (
            field,
            claim[field],
        )
    assert_hold_reason(claim, None)

    student = get_success_data(client.get_student(scenario["student"]["id"], headers=COORDINATOR))
    assert_ledger(student, reserved=6)

    response = client.list_assignments({"claim_id": scenario["claim"]["id"]}, headers=COORDINATOR)
    rows, _meta = validate_paginated(response)
    replacements = [
        row for row in rows if row["selection_reason"] == SelectionReason.AUTO_REPLACEMENT
    ]
    assert len(replacements) == 1, "the remand creates exactly one replacement assignment"
    assert replacements[0]["assessor_id"] != scenario["scorer"]["id"], (
        "the prior scorer is permanently excluded from this claim"
    )

    settled = get_success_data(
        client.pay_invoice(
            scenario["invoice"]["id"],
            f.payment_payload(600, PaymentMethod.CARD),
            headers=make_student_headers(scenario["student"]["id"]),
        )
    )
    assert_invoice_money(settled, balance_due_cents=0)
    reread = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(reread, fee_status=FeeStatus.PAID)
