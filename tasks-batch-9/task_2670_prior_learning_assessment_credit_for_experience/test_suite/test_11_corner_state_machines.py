"""State-machine corners: initial states, refused transitions and side effects.

Each scenario drives one machine across one edge — or refuses one edge — and then
reads the neighbouring rows the edge is supposed to have touched, or left alone.
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
    ids_of,
)
from test_helpers.test_users import (
    COORDINATOR,
    OFFICER_REVIEWER,
    make_assessor_headers,
    make_student_headers,
)
from test_helpers.types import (
    Alignment,
    AssessmentStatus,
    AssignmentStatus,
    CourseLevel,
    CreditStatus,
    FeeStatus,
    PaymentMethod,
    PortfolioStatus,
    RecommendationStatus,
    RuleStatus,
    SelectionReason,
    SourceType,
)

CLOCK_EPOCH = "2026-08-01T00:00:00Z"


def _cs150_outcomes():
    """The two-outcome rubric shared by every scenario in this module."""
    return [
        f.outcome_payload("OC1", 8000, mastery_threshold_bp=7000),
        f.outcome_payload("OC2", 2000, mastery_threshold_bp=7000),
    ]


def _bscs(client):
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
        learning_outcomes=_cs150_outcomes(),
    )


@pytest.fixture
def submitted_portfolio_claim(client):
    """A submitted 6-credit PORTFOLIO claim carrying an unpaid 27000-cent invoice.

    The portfolio holds two artifacts, one PRIMARY on the 8000-weight outcome and
    one SUPPORTING on the 2000-weight one, so ``provisional_coverage_bp`` is 9000
    and the two submission floors are clear. Two artifacts also keep the artifact
    tier surcharge at zero, so the invoice is base 15000 plus 2500 per credit over
    six credits, discounted 1000 basis points down to 27000 cents.
    """
    program = _bscs(client)
    course = _cs150(client)
    student = fx.new_student(
        client,
        program["id"],
        student_number="S-1001",
        transfer_credits_accepted=0,
        institutional_credits_earned=60,
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
    outcomes = fx.outcomes_of(client, course["id"])
    portfolio = fx.new_portfolio(client, claim["id"], student["id"])
    fx.attach_artifact(
        client,
        portfolio["id"],
        student["id"],
        [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)],
    )
    fx.attach_artifact(
        client,
        portfolio["id"],
        student["id"],
        [f.mapping(outcomes[1]["id"], Alignment.SUPPORTING)],
    )
    fx.submit_portfolio(client, portfolio["id"], student["id"])
    fx.submit_claim(client, claim["id"], student["id"])
    return {
        "program": program,
        "course": course,
        "outcomes": outcomes,
        "student": student,
        "assessor": assessor,
        "claim": claim,
        "portfolio": portfolio,
        "invoice": fx.invoice_for_claim(client, claim["id"]),
    }


def _waive(client, invoice_id):
    return get_success_data(
        client.waive_invoice(
            invoice_id, {"waive_reason": "Institutional hardship waiver"}, headers=COORDINATOR
        )
    )


def test_seven_fresh_rows_land_on_their_declared_initial_states(
    client, submitted_portfolio_claim
):
    """No creation endpoint skips its machine's first state.

    PRD: "the claim comes into being in `assessment_status` `DRAFT`, `fee_status`
    `UNBILLED` and `credit_status` `NOT_POSTED` with no reservation, no invoice and
    no assessor." "A new portfolio begins in `status` `DRAFT` with `artifact_count`
    at 0, `revision_round` at 0, `submitted_at` null and both
    `provisional_coverage_bp` and `verified_coverage_bp` null." "Creating the
    assignment records `selection_reason` as `EXPLICIT` when the coordinator named
    the assessor and `AUTO_SELECTED` when the server chose." "The rule begins in
    `DRAFT` with `pinned_recommendation_version`, `reviewed_by_user_id`,
    `approved_by_user_id` and `suspend_reason` all null."

    Design: Corner/state_machines/entity_initial_states_on_creation
    """
    scenario = submitted_portfolio_claim
    assert_claim_dimensions(
        scenario["claim"],
        assessment_status=AssessmentStatus.DRAFT,
        fee_status=FeeStatus.UNBILLED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    assert_fields_equal(scenario["portfolio"], status=PortfolioStatus.DRAFT)

    # A waived invoice satisfies the fee gate at assignment exactly as a paid one.
    waived = _waive(client, scenario["invoice"]["id"])
    assert_invoice_money(waived, total_cents=27000)
    gated = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(gated, fee_status=FeeStatus.WAIVED)

    assignment = validate_success(
        client.create_assignment(
            scenario["claim"]["id"],
            {"assessor_id": scenario["assessor"]["id"]},
            headers=COORDINATOR,
        ),
        201,
    )
    assert_fields_equal(
        assignment,
        status=AssignmentStatus.ASSIGNED,
        selection_reason=SelectionReason.EXPLICIT,
        accepted_at=None,
        rubric_submitted_at=None,
    )
    assert assignment["status"] != AssignmentStatus.ACCEPTED

    assessor = get_success_data(
        client.get_assessor(scenario["assessor"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(assessor, active_assignment_count=1)

    recommendation = validate_success(
        client.create_recommendation(
            f.recommendation_payload(
                credential_code="AWSSAA",
                source_type=SourceType.INDUSTRY_CREDENTIAL,
                recommended_credits=3,
                recommended_level=CourseLevel.LOWER,
                effective_from="2026-01-01T00:00:00Z",
            ),
            headers=OFFICER_REVIEWER,
        ),
        201,
    )
    assert_fields_equal(
        recommendation,
        status=RecommendationStatus.DRAFT,
        terms_version=1,
        approved_rule_count=0,
    )

    rule = validate_success(
        client.create_rule(
            f.rule_payload(
                recommendation["id"],
                scenario["course"]["id"],
                awarded_credits=3,
                effective_from="2026-01-01T00:00:00Z",
            ),
            headers=OFFICER_REVIEWER,
        ),
        201,
    )
    assert_fields_equal(
        rule,
        status=RuleStatus.DRAFT,
        pinned_recommendation_version=None,
        reviewed_by_user_id=None,
        approved_by_user_id=None,
        suspend_reason=None,
    )


def test_submitting_an_already_submitted_claim_is_refused_as_not_draft(
    client, submitted_portfolio_claim
):
    """The refused submit reserves nothing twice and reprices nothing.

    PRD: "(a) The claim's `assessment_status` is a declared from-state of the
    requested assessment transition; failures are `ERR_CLAIM_NOT_DRAFT`,
    `ERR_CLAIM_NOT_SUBMITTED`, `ERR_CLAIM_NOT_UNDER_ASSESSMENT`,
    `ERR_CLAIM_NOT_SCORED`, `ERR_CLAIM_NOT_DENIED` and `ERR_CLAIM_NOT_AWARDED`, all
    409". "`credits_requested` is added to the student's `pla_credits_reserved`, and
    when the course's `level` is `UPPER` the same amount is added to
    `pla_upper_division_committed`".

    Design: Corner/state_machines/claim_submit_from_submitted_rejected_as_not_draft
    """
    scenario = submitted_portfolio_claim
    assert_ledger(scenario["student"], reserved=0)
    assert_invoice_money(scenario["invoice"], total_cents=27000, recompute_count=0)

    refused = client.submit_claim(
        scenario["claim"]["id"], headers=make_student_headers(scenario["student"]["id"])
    )
    validate_error(refused, ApiErrorId.ERR_CLAIM_NOT_DRAFT, 409)

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(
        claim,
        assessment_status=AssessmentStatus.SUBMITTED,
        fee_status=FeeStatus.INVOICED,
    )

    student = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, reserved=6)
    assert student["pla_credits_reserved"] != 12, (
        "the refused submit must not have taken a second reservation"
    )

    invoice = get_success_data(
        client.get_invoice(scenario["invoice"]["id"], headers=COORDINATOR)
    )
    assert_invoice_money(invoice, total_cents=27000, recompute_count=0)


def test_accepting_an_assignment_twice_is_refused_as_not_pending(
    client, submitted_portfolio_claim
):
    """The second acceptance neither re-stamps the timestamp nor re-counts the load.

    PRD: "An assessor accepts an assignment from `ASSIGNED`, which advances it to
    `ACCEPTED` and stamps `accepted_at` with the logical clock." "Accepting from any
    status other than `ASSIGNED` is `ERR_ASSIGNMENT_NOT_PENDING`, and the
    assignment's `version` increments on success."

    Design: Corner/state_machines/assignment_accept_twice_rejected_as_not_pending
    """
    scenario = submitted_portfolio_claim
    _waive(client, scenario["invoice"]["id"])
    assignment = fx.assign_assessor(client, scenario["claim"]["id"], scenario["assessor"]["id"])

    accepted = validate_success(
        client.accept_assignment(
            assignment["id"], headers=make_assessor_headers(scenario["assessor"]["id"])
        )
    )
    assert_fields_equal(accepted, status=AssignmentStatus.ACCEPTED)
    # The logical clock has never been moved, so acceptance is stamped at the epoch.
    assert_instant(accepted["accepted_at"], CLOCK_EPOCH, "accepted_at")

    refused = client.accept_assignment(
        assignment["id"], headers=make_assessor_headers(scenario["assessor"]["id"])
    )
    validate_error(refused, ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING, 409)

    after = get_success_data(client.get_assignment(assignment["id"], headers=COORDINATOR))
    assert_fields_equal(after, status=AssignmentStatus.ACCEPTED)
    assert_instant(after["accepted_at"], CLOCK_EPOCH, "accepted_at")
    assert after["accepted_at"] == accepted["accepted_at"], (
        "the refused acceptance must not re-stamp accepted_at"
    )

    assessor = get_success_data(
        client.get_assessor(scenario["assessor"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(assessor, active_assignment_count=1)
    assert assessor["active_assignment_count"] != 2

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.UNDER_ASSESSMENT)


@pytest.fixture
def draft_claim_only(client):
    """A 6-credit PORTFOLIO claim that has never been submitted."""
    program = _bscs(client)
    course = _cs150(client)
    student = fx.new_student(
        client,
        program["id"],
        student_number="S-1001",
        transfer_credits_accepted=0,
        institutional_credits_earned=60,
    )
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    return {"program": program, "course": course, "student": student, "claim": claim}


def test_awarding_a_draft_claim_is_refused_as_not_scored(client, draft_claim_only):
    """A current concurrency token does not buy passage past the from-state check.

    PRD: "The claim's `assessment_status` must be `SCORED` and its
    `assessor_recommendation` must be `PASS` — a `FAIL` claim cannot be awarded."
    "On success `assessment_status` becomes `AWARDED` and `credits_awarded` is
    recorded on the claim."

    Design: Corner/state_machines/award_of_a_draft_claim_rejected_as_not_scored
    """
    student_before = get_success_data(
        client.get_student(draft_claim_only["student"]["id"], headers=COORDINATOR)
    )
    version_before = student_before["version"]

    refused = client.award_claim(
        draft_claim_only["claim"]["id"],
        {"expected_student_version": version_before, "credits_awarded": 6},
        headers=COORDINATOR,
    )
    validate_error(refused, ApiErrorId.ERR_CLAIM_NOT_SCORED, 409)

    claim = get_success_data(
        client.get_claim(draft_claim_only["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.DRAFT)
    assert_fields_equal(claim, credits_awarded=None)

    student_after = get_success_data(
        client.get_student(draft_claim_only["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student_after, reserved=0, awarded=0, posted=0)
    assert student_after["version"] == version_before, (
        "the rejected award must not have bumped the student's version"
    )


def test_declining_an_assignment_revokes_it_and_spawns_a_replacement(
    client, submitted_portfolio_claim
):
    """One decline produces a second assignment nobody asked for.

    PRD: "It sets `status` to `DECLINED`, records the free-text `decline_reason`,
    decrements the assessor's `active_assignment_count` by one and increments that
    assessor's `version`. It then fires the **replacement cascade**: the selector
    runs again over the eligible pool with every assessor ever assigned to this
    claim excluded, and the winner receives a new assignment with `selection_reason`
    `AUTO_REPLACEMENT` and their `active_assignment_count` incremented by one."

    Design: Corner/state_machines/assignment_decline_revokes_and_spawns_auto_replacement
    """
    scenario = submitted_portfolio_claim
    _waive(client, scenario["invoice"]["id"])
    understudy = fx.new_assessor(
        client,
        employee_number="E-9002",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    first = fx.assign_assessor(client, scenario["claim"]["id"], scenario["assessor"]["id"])

    declined = validate_success(
        client.decline_assignment(
            first["id"],
            {"decline_reason": "Outside my subject area"},
            headers=make_assessor_headers(scenario["assessor"]["id"]),
        )
    )
    assert_fields_equal(
        declined,
        status=AssignmentStatus.DECLINED,
        decline_reason="Outside my subject area",
    )

    decliner = get_success_data(
        client.get_assessor(scenario["assessor"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(decliner, active_assignment_count=0)

    rows, _meta = validate_paginated(
        client.list_assignments({"claim_id": scenario["claim"]["id"]}, headers=COORDINATOR)
    )
    assert len(ids_of(rows)) == 2, "the decline must leave the original plus a replacement"
    replacements = [row for row in rows if row["id"] != first["id"]]
    assert len(replacements) == 1
    replacement = replacements[0]
    assert_fields_equal(
        replacement,
        assessor_id=understudy["id"],
        status=AssignmentStatus.ASSIGNED,
        selection_reason=SelectionReason.AUTO_REPLACEMENT,
    )

    stand_in = get_success_data(client.get_assessor(understudy["id"], headers=COORDINATOR))
    assert_fields_equal(stand_in, active_assignment_count=1)

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.UNDER_ASSESSMENT)
    assert_fields_equal(claim, hold_reason=None)


def test_the_fee_dimension_reaches_paid_while_the_assessment_dimension_stands_still(
    client, submitted_portfolio_claim
):
    """Two payments move one dimension twice and the other two not at all.

    PRD: "A claim carries three independent status dimensions on one row:
    `assessment_status`, `fee_status` and `credit_status`. Each advances on its own
    triggers." "a payment that leaves net cash short of `total_cents` minus
    `waived_cents` yields `PARTIALLY_PAID`, whether the invoice was `INVOICED` or
    already `PARTIALLY_PAID`; a payment that brings net cash exactly to
    `total_cents` minus `waived_cents` yields `PAID`".

    Design: Corner/state_machines/claim_fee_dimension_reaches_paid_while_assessment_stays_submitted
    """
    scenario = submitted_portfolio_claim
    student_headers = make_student_headers(scenario["student"]["id"])
    # PORTFOLIO base 15000 plus 2500 per credit over 6 credits, two artifacts so no
    # tier surcharge; 30000 clears the 25000-cent discount boundary at 1000 bp.
    assert_invoice_money(
        scenario["invoice"],
        subtotal_cents=30000,
        discount_bp=1000,
        discount_cents=3000,
        total_cents=27000,
    )

    midway = validate_success(
        client.pay_invoice(
            scenario["invoice"]["id"],
            f.payment_payload(20000, PaymentMethod.CARD),
            headers=student_headers,
        )
    )
    assert_invoice_money(midway, paid_cents=20000, balance_due_cents=7000)
    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(
        claim,
        assessment_status=AssessmentStatus.SUBMITTED,
        fee_status=FeeStatus.PARTIALLY_PAID,
        credit_status=CreditStatus.NOT_POSTED,
    )

    settled = validate_success(
        client.pay_invoice(
            scenario["invoice"]["id"],
            f.payment_payload(7000, PaymentMethod.CARD),
            headers=student_headers,
        )
    )
    assert_invoice_money(settled, paid_cents=27000, balance_due_cents=0)
    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(
        claim,
        assessment_status=AssessmentStatus.SUBMITTED,
        fee_status=FeeStatus.PAID,
        credit_status=CreditStatus.NOT_POSTED,
    )

    student = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, fee_paid_net_cents=27000)


def test_a_withdrawn_claim_refuses_all_three_advancing_doors(client, draft_claim_only):
    """Terminality is checked before any more specific from-state rule.

    PRD: "The claim's `assessment_status` is none of `AWARDED`, `DENIED_FINAL`,
    `WITHDRAWN`. Failure: `ERR_CLAIM_ALREADY_TERMINAL` (409). Applies to submitting a
    claim, withdrawing a claim, requesting a revision, denying a claim, creating an
    assessor assignment for a claim, and filing an appeal." "The claim's assessment
    dimension has exactly three terminal states — `AWARDED`, `DENIED_FINAL` and
    `WITHDRAWN` — and any attempt to advance a claim sitting in one of them is
    refused with `ERR_CLAIM_ALREADY_TERMINAL` before any more specific from-state
    check is consulted."

    Design: Corner/state_machines/withdrawn_claim_is_terminal_and_cannot_be_resubmitted
    """
    claim_id = draft_claim_only["claim"]["id"]
    student_id = draft_claim_only["student"]["id"]
    student_headers = make_student_headers(student_id)
    portfolio = fx.new_portfolio(client, claim_id, student_id)

    withdrawn = validate_success(
        client.withdraw_claim(
            claim_id,
            {"withdraw_reason": "Student enrolled in the course instead"},
            headers=student_headers,
        )
    )
    assert_claim_dimensions(withdrawn, assessment_status=AssessmentStatus.WITHDRAWN)

    validate_error(
        client.submit_claim(claim_id, headers=student_headers),
        ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL,
        409,
    )
    validate_error(
        client.withdraw_claim(
            claim_id, {"withdraw_reason": "Second attempt"}, headers=student_headers
        ),
        ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL,
        409,
    )
    validate_error(
        client.request_revision(
            claim_id, {"revision_note": "Please add evidence"}, headers=COORDINATOR
        ),
        ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL,
        409,
    )

    claim = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_claim_dimensions(
        claim,
        assessment_status=AssessmentStatus.WITHDRAWN,
        fee_status=FeeStatus.UNBILLED,
    )
    assert_fields_equal(claim, revision_round=0)

    voided = get_success_data(client.get_portfolio(portfolio["id"], headers=COORDINATOR))
    assert_fields_equal(voided, status=PortfolioStatus.VOIDED)

    student = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(student, reserved=0)


def test_publishing_a_recommendation_leaves_the_terms_version_alone(client):
    """The generic counter moves and the pin-governing counter does not.

    PRD: "It moves `status` from `DRAFT` to `PUBLISHED` and requires that
    `effective_to` is either null or strictly later than `effective_from`;
    publication increments the recommendation's `version` but deliberately leaves
    `terms_version` untouched." "Amending a recommendation is the only operation that
    moves `terms_version`".

    Design: Corner/state_machines/recommendation_publish_moves_draft_to_published
    """
    drafted = validate_success(
        client.create_recommendation(
            f.recommendation_payload(
                credential_code="AWSSAA",
                source_type=SourceType.INDUSTRY_CREDENTIAL,
                recommended_credits=3,
                recommended_level=CourseLevel.LOWER,
                effective_from="2026-01-01T00:00:00Z",
            ),
            headers=OFFICER_REVIEWER,
        ),
        201,
    )
    assert_fields_equal(
        drafted, status=RecommendationStatus.DRAFT, version=1, terms_version=1
    )

    published = validate_success(
        client.publish_recommendation(drafted["id"], headers=OFFICER_REVIEWER)
    )
    assert_fields_equal(
        published,
        status=RecommendationStatus.PUBLISHED,
        version=2,
        terms_version=1,
        approved_rule_count=0,
        retire_reason=None,
    )
