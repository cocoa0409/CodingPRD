"""States that are re-entered rather than passed through once.

A portfolio re-enters ``SUBMITTED`` twice under a budget counted on the claim, and
a remanded appeal drives a claim backwards past the state it was scored in.
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
    assert_instant,
    assert_invoice_money,
    assert_ledger,
)
from test_helpers.test_users import (
    COORDINATOR,
    make_assessor_headers,
    make_reviewer_headers,
    make_student_headers,
)
from test_helpers.types import (
    Alignment,
    AppealStatus,
    ArtifactType,
    AssessmentStatus,
    AssignmentStatus,
    CourseLevel,
    FeeStatus,
    PaymentMethod,
    PortfolioStatus,
    Recommendation,
    SelectionReason,
    SourceType,
)


def _bscs_program(client):
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


def _cs_assessor(client, employee_number, appeal_panel_member=False):
    return fx.new_assessor(
        client,
        employee_number=employee_number,
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
        appeal_panel_member=appeal_panel_member,
    )


def _pay(client, invoice_id, student_id, amount_cents):
    return get_success_data(
        client.pay_invoice(
            invoice_id,
            f.payment_payload(amount_cents, PaymentMethod.CARD),
            headers=make_student_headers(student_id),
        )
    )


@pytest.fixture
def two_revision_cycles(client):
    """A claim walked twice around ``SUBMITTED -> REVISION_REQUESTED -> SUBMITTED``.

    Each cycle needs an assessor assignment first, because a revision may only be
    requested from ``UNDER_ASSESSMENT``, and each cycle uses a different assessor
    because per-claim exclusion is permanent. The claim ends in
    ``UNDER_ASSESSMENT`` with ``revision_round`` at 2 and four artifacts attached.
    """
    program = _bscs_program(client)
    course = _cs150(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=0, institutional_credits_earned=60
    )
    assessors = [_cs_assessor(client, "E-900%d" % (i + 1)) for i in range(3)]
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
    invoice = fx.invoice_for_claim(client, claim["id"])
    _pay(client, invoice["id"], student["id"], invoice["balance_due_cents"])

    snapshots = {}
    for round_index, extra_title in ((0, "Attestation 1"), (1, "Attestation 2")):
        assignment = fx.assign_assessor(client, claim["id"], assessors[round_index]["id"])
        get_success_data(
            client.request_revision(
                claim["id"], {"revision_note": "More evidence please"}, headers=COORDINATOR
            )
        )
        snapshots["claim_after_revision_%d" % (round_index + 1)] = get_success_data(
            client.get_claim(claim["id"], headers=COORDINATOR)
        )
        snapshots["portfolio_after_revision_%d" % (round_index + 1)] = get_success_data(
            client.get_portfolio(portfolio["id"], headers=COORDINATOR)
        )
        snapshots["assignment_after_revision_%d" % (round_index + 1)] = get_success_data(
            client.get_assignment(assignment["id"], headers=COORDINATOR)
        )
        fx.attach_artifact(
            client,
            portfolio["id"],
            student["id"],
            [f.mapping(outcomes[round_index]["id"], Alignment.SUPPORTING)],
            artifact_type=ArtifactType.EMPLOYER_LETTER,
            title=extra_title,
        )
        snapshots["portfolio_after_resubmit_%d" % (round_index + 1)] = fx.submit_portfolio(
            client, portfolio["id"], student["id"]
        )
        snapshots["claim_after_resubmit_%d" % (round_index + 1)] = fx.submit_claim(
            client, claim["id"], student["id"]
        )

    # The fourth artifact lifted the invoice into the artifact-surcharge tier, so
    # the balance must be settled again before a third assignment is permitted.
    current = get_success_data(client.get_invoice(invoice["id"], headers=COORDINATOR))
    if current["balance_due_cents"]:
        _pay(client, invoice["id"], student["id"], current["balance_due_cents"])
    fx.assign_assessor(client, claim["id"], assessors[2]["id"])

    return {
        "student": student,
        "claim": claim,
        "portfolio": portfolio,
        "invoice": invoice,
        "assessors": assessors,
        "snapshots": snapshots,
    }


def test_portfolio_reenters_submitted_twice_without_doubling_the_reservation(
    client, two_revision_cycles
):
    """Two full revision cycles, one reservation, two invoice recomputes.

    PRD: "the portfolio moves `SUBMITTED → REVISION_REQUESTED`, its
    `revision_round` increments by one, and its artifacts become mutable again; the
    student then resubmits, which returns it to `SUBMITTED` under the same two
    floors". "Re-submission does **not** re-increment `pla_credits_reserved`,
    because the reservation persisted unbroken through the `REVISION_REQUESTED`
    hold." "The existing invoice is recomputed rather than recreated — the artifact
    tier and rush lines may well have changed since the first pricing — and
    `recompute_count` increments by one."

    Design: Difficulty/non_linear_state_machine/portfolio_revision_cycle_reenters_submitted_twice_then_limit_blocks
    """
    snapshots = two_revision_cycles["snapshots"]

    assert_claim_dimensions(
        snapshots["claim_after_revision_1"],
        assessment_status=AssessmentStatus.REVISION_REQUESTED,
    )
    assert_fields_equal(snapshots["claim_after_revision_1"], revision_round=1)
    assert_fields_equal(
        snapshots["portfolio_after_revision_1"],
        status=PortfolioStatus.REVISION_REQUESTED,
        revision_round=1,
    )
    assert_fields_equal(
        snapshots["portfolio_after_resubmit_1"],
        status=PortfolioStatus.SUBMITTED,
        artifact_count=3,
        revision_round=1,
    )
    assert_claim_dimensions(
        snapshots["claim_after_resubmit_1"], assessment_status=AssessmentStatus.SUBMITTED
    )

    assert_fields_equal(snapshots["claim_after_revision_2"], revision_round=2)
    assert_fields_equal(
        snapshots["portfolio_after_revision_2"],
        status=PortfolioStatus.REVISION_REQUESTED,
        revision_round=2,
    )
    assert_fields_equal(
        snapshots["portfolio_after_resubmit_2"],
        status=PortfolioStatus.SUBMITTED,
        artifact_count=4,
        revision_round=2,
    )
    assert_claim_dimensions(
        snapshots["claim_after_resubmit_2"], assessment_status=AssessmentStatus.SUBMITTED
    )

    student = get_success_data(
        client.get_student(two_revision_cycles["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, reserved=6)

    invoice = get_success_data(
        client.get_invoice(two_revision_cycles["invoice"]["id"], headers=COORDINATOR)
    )
    assert_invoice_money(invoice, recompute_count=2)


def test_third_revision_request_is_refused_by_the_two_round_budget(
    client, two_revision_cycles
):
    """The same state that twice accepted a revision now refuses one.

    PRD: "The revision budget is two: `revision_round` must be below 2, since one
    more round is being consumed, and a third request is refused with
    `ERR_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/portfolio_revision_cycle_reenters_submitted_twice_then_limit_blocks
    """
    claim_id = two_revision_cycles["claim"]["id"]

    before = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_fields_equal(before, revision_round=2)
    assert_claim_dimensions(before, assessment_status=AssessmentStatus.UNDER_ASSESSMENT)

    response = client.request_revision(
        claim_id, {"revision_note": "One more pass please"}, headers=COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED, expected_status=409)

    after = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_fields_equal(after, revision_round=2)
    assert_claim_dimensions(after, assessment_status=AssessmentStatus.UNDER_ASSESSMENT)

    portfolio = get_success_data(
        client.get_portfolio(two_revision_cycles["portfolio"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(
        portfolio, status=PortfolioStatus.SUBMITTED, artifact_count=4, revision_round=2
    )

    student = get_success_data(
        client.get_student(two_revision_cycles["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, reserved=6)


@pytest.fixture
def appeal_under_review(client):
    """A denied portfolio claim whose appeal is settled and awaiting a decision.

    E-9001 scored the claim FAIL, so it is the only prior scorer; E-9003 is the
    appeal-panel member reviewing it, and E-9002 has never touched the claim.
    """
    program = _bscs_program(client)
    course = _cs150(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=0, institutional_credits_earned=60
    )
    first = _cs_assessor(client, "E-9001")
    second = _cs_assessor(client, "E-9002")
    reviewer = _cs_assessor(client, "E-9003", appeal_panel_member=True)

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
    invoice = fx.invoice_for_claim(client, claim["id"])
    _pay(client, invoice["id"], student["id"], 27000)

    first_assignment = fx.assign_assessor(client, claim["id"], first["id"])
    fx.accept_assignment(client, first_assignment["id"], first["id"])
    fx.score_all_outcomes(client, first_assignment["id"], first["id"], outcomes, [2, 2])
    fx.complete_assignment(
        client, first_assignment["id"], first["id"], recommendation=Recommendation.FAIL
    )
    denied = get_success_data(
        client.deny_claim(
            claim["id"], {"denial_reason": "Insufficient outcome mastery"}, headers=COORDINATOR
        )
    )
    appeal = get_success_data(
        client.create_appeal(
            {"claim_id": claim["id"], "grounds": "Rubric misread the attestation"},
            headers=make_student_headers(student["id"]),
        )
    )
    _pay(client, invoice["id"], student["id"], 5400)
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
        "first_assignment": first_assignment,
        "first": first,
        "second": second,
        "reviewer": reviewer,
        "denied_claim": denied,
    }


def test_remanded_appeal_drives_the_claim_back_to_under_assessment(
    client, appeal_under_review
):
    """A remand moves the claim backwards, not forward to SCORED.

    PRD: "**Remanding** sends the claim back for a fresh assessment. The appeal's
    `status` becomes `REMANDED`." "The claim's `assessment_status` returns to
    `UNDER_ASSESSMENT` and four fields are cleared to null:
    `assessor_recommendation`, `verified_coverage_bp`, `denial_reason` and
    `appeal_deadline_at`. `credits_requested` is added back into
    `pla_credits_reserved` and the student's `version` increments." Denial had set
    `appeal_deadline_at` to "the logical clock advanced by 336 hours".

    Design: Difficulty/non_linear_state_machine/appeal_remand_returns_claim_to_under_assessment_not_scored
    """
    claim_id = appeal_under_review["claim"]["id"]
    reviewer_id = appeal_under_review["reviewer"]["id"]

    assert_instant(
        appeal_under_review["denied_claim"]["appeal_deadline_at"],
        "2026-08-15T00:00:00Z",
        "appeal_deadline_at",
    )

    decided = validate_success(
        client.decide_appeal(
            appeal_under_review["appeal"]["id"],
            {"decision": "REMANDED", "decision_note": "Re-assess with a second reader"},
            headers=make_reviewer_headers(reviewer_id),
        )
    )
    assert_fields_equal(decided, status=AppealStatus.REMANDED)
    assert_instant(decided["decided_at"], "2026-08-01T00:00:00Z", "decided_at")

    claim = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.UNDER_ASSESSMENT)
    assert_fields_equal(
        claim,
        assessor_recommendation=None,
        verified_coverage_bp=None,
        denial_reason=None,
        appeal_deadline_at=None,
        appeal_count=1,
    )

    student = get_success_data(
        client.get_student(appeal_under_review["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, reserved=6, awarded=0, posted=0)

    invoice = get_success_data(
        client.get_invoice(appeal_under_review["invoice"]["id"], headers=COORDINATOR)
    )
    assert_invoice_money(
        invoice,
        total_cents=27000,
        paid_cents=32400,
        refunded_cents=6000,
        balance_due_cents=600,
    )


def test_remand_replacement_assignment_excludes_the_prior_scorer(
    client, appeal_under_review
):
    """The fresh assignment goes to E-9002; E-9001's scoring record survives.

    PRD: "A replacement assignment is created through the selector, excluding every
    assessor ever assigned to this claim, with `selection_reason`
    `AUTO_REPLACEMENT`". Filing "snapshots `prior_scorer_assessor_ids` — the
    identifiers of every assessor who scored this claim". The selector's ordering is
    "by `active_assignment_count` ascending, then `credential_rank` descending, then
    `created_at` ascending, then `employee_number` ascending".

    Design: Difficulty/non_linear_state_machine/appeal_remand_returns_claim_to_under_assessment_not_scored
    """
    claim_id = appeal_under_review["claim"]["id"]
    first_id = appeal_under_review["first"]["id"]

    appeal = get_success_data(
        client.get_appeal(appeal_under_review["appeal"]["id"], headers=COORDINATOR)
    )
    assert appeal["prior_scorer_assessor_ids"] == [first_id], (
        "only the assessor who scored the claim belongs in the snapshot"
    )

    validate_success(
        client.decide_appeal(
            appeal_under_review["appeal"]["id"],
            {"decision": "REMANDED", "decision_note": "Re-assess with a second reader"},
            headers=make_reviewer_headers(appeal_under_review["reviewer"]["id"]),
        )
    )

    rows, _meta = validate_paginated(
        client.list_assignments({"claim_id": claim_id}, headers=COORDINATOR)
    )
    replacements = [row for row in rows if row["selection_reason"] == SelectionReason.AUTO_REPLACEMENT]
    assert len(replacements) == 1, "a remand must synthesise exactly one replacement"
    assert_fields_equal(
        replacements[0],
        assessor_id=appeal_under_review["second"]["id"],
        status=AssignmentStatus.ASSIGNED,
    )

    original = get_success_data(
        client.get_assignment(appeal_under_review["first_assignment"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(original, status=AssignmentStatus.SCORING_COMPLETE)
