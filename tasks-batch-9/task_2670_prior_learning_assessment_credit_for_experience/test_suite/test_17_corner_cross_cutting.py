"""The two cross-cutting layers: the ledger version gate, and immediate reads.

The award desk presents a version of a row it does not itself own, and every
derived field in this system is settled inside the request that causes it. Both
claims are checked against the same scored claim wherever the scenarios allow.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_audit,
    assert_claim_dimensions,
    assert_fields_equal,
    assert_instant,
    assert_invoice_money,
    assert_ledger,
)
from test_helpers.test_users import COORDINATOR, REGISTRAR, make_student_headers
from test_helpers.types import (
    Alignment,
    AssessmentStatus,
    AuditStatus,
    CourseLevel,
    CreditStatus,
    FeeStatus,
    PortfolioStatus,
    PriorityTier,
    Recommendation,
    SourceType,
)


def _cs150_outcomes():
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


def _student(client, program_id):
    return fx.new_student(
        client,
        program_id,
        student_number="S-1001",
        transfer_credits_accepted=0,
        institutional_credits_earned=60,
    )


def _portfolio_claim(client, student_id, course, outcomes, second_alignment):
    """A 6-credit PORTFOLIO claim whose portfolio is SUBMITTED with two artifacts."""
    claim = fx.new_claim(
        client,
        student_id,
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    portfolio = fx.new_portfolio(client, claim["id"], student_id)
    fx.attach_artifact(
        client, portfolio["id"], student_id, [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    fx.attach_artifact(
        client, portfolio["id"], student_id, [f.mapping(outcomes[1]["id"], second_alignment)]
    )
    submitted = fx.submit_portfolio(client, portfolio["id"], student_id)
    return claim, submitted


@pytest.fixture
def a_scored_claim_awaiting_the_award_desk(client):
    """A SCORED claim at verified coverage 10000 with its invoice already waived.

    Both outcomes are mapped PRIMARY and both score 4 of 4, so the assessment is
    unambiguous and nothing but the concurrency token stands between the coordinator
    and the award.
    """
    fx.set_clock(client, fx.CLOCK_EPOCH)
    program = _bscs(client)
    course = _cs150(client)
    student = _student(client, program["id"])
    assessor = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    outcomes = fx.outcomes_of(client, course["id"])
    claim, _portfolio = _portfolio_claim(
        client, student["id"], course, outcomes, Alignment.PRIMARY
    )
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.waive_invoice(
            invoice["id"], {"waive_reason": "Pilot cohort waiver"}, headers=COORDINATOR
        )
    )
    assignment = fx.assign_assessor(client, claim["id"], assessor["id"])
    fx.accept_assignment(client, assignment["id"], assessor["id"])
    fx.score_all_outcomes(client, assignment["id"], assessor["id"], outcomes, [4, 4])
    fx.complete_assignment(client, assignment["id"], assessor["id"], Recommendation.PASS)
    return {
        "program": program,
        "course": course,
        "student": student,
        "claim": claim,
        "invoice": invoice,
    }


def test_a_ledger_bump_between_the_read_and_the_award_refuses_the_award(
    client, a_scored_claim_awaiting_the_award_desk
):
    """A registrar's unrelated PATCH invalidates the coordinator's token.

    PRD: "Awarding a claim requires `expected_student_version` in the request body. It
    is a mandatory field, not an optional hint. Its value must equal the current
    `version` of the claim's `Student` row." "When `expected_student_version` does not
    match, the award is refused with `ERR_STALE_STUDENT_VERSION` and HTTP 412, and the
    coordinator must re-read the student before retrying." "`version`, an integer that
    starts at 1 on creation and increments by one on every mutation of that row"

    Design: Corner/cross_cutting_complexity_layers/stale_expected_student_version_at_award_is_refused_then_a_refreshed_read_succeeds
    """
    scenario = a_scored_claim_awaiting_the_award_desk
    student_id = scenario["student"]["id"]
    claim_id = scenario["claim"]["id"]

    observed = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(observed, reserved=6, awarded=0, posted=0)

    bumped = validate_success(
        client.patch_student(student_id, {"institutional_credits_earned": 66}, headers=REGISTRAR)
    )
    assert bumped["version"] == observed["version"] + 1, "the PATCH advanced the student row"

    stale = client.award_claim(
        claim_id,
        {"expected_student_version": observed["version"], "credits_awarded": 6},
        headers=COORDINATOR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_STUDENT_VERSION, 412)

    # A 412 is not a write: neither dimension of the claim nor the ledger moved.
    held = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_claim_dimensions(
        held,
        assessment_status=AssessmentStatus.SCORED,
        fee_status=FeeStatus.WAIVED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    assert_fields_equal(held, credits_awarded=None)
    after_refusal = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(after_refusal, reserved=6, awarded=0, posted=0)
    assert after_refusal["version"] == bumped["version"], "the refused award wrote nothing"

    awarded = validate_success(
        client.award_claim(
            claim_id,
            {"expected_student_version": after_refusal["version"], "credits_awarded": 6},
            headers=COORDINATOR,
        )
    )
    assert_claim_dimensions(awarded, assessment_status=AssessmentStatus.AWARDED)
    assert_fields_equal(awarded, credits_awarded=6)
    settled = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(settled, reserved=0, awarded=6, posted=0)
    assert settled["version"] == after_refusal["version"] + 1


def test_the_concurrency_gate_is_read_before_the_terminal_and_shape_rungs(
    client, a_scored_claim_awaiting_the_award_desk
):
    """Replaying a successful award is answered 412, not the terminal-claim 409.

    PRD: "`expected_student_version` equals the current `Student` `version`. Failure:
    `ERR_STALE_STUDENT_VERSION` (412). Applies to awarding a claim." "Required input
    fields are present and every supplied field satisfies its declared type, enum domain
    and numeric range. Failure: `ERR_INVALID_REQUEST` (400)." "The claim's assessment
    dimension has exactly three terminal states — `AWARDED`, `DENIED_FINAL` and
    `WITHDRAWN` — and any attempt to advance a claim sitting in one of them is refused
    with `ERR_CLAIM_ALREADY_TERMINAL` before any more specific from-state check is
    consulted."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_student_version_at_award_is_refused_then_a_refreshed_read_succeeds
    """
    scenario = a_scored_claim_awaiting_the_award_desk
    student_id = scenario["student"]["id"]
    claim_id = scenario["claim"]["id"]

    first_read = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    for _ in range(3):
        repeat = get_success_data(client.get_student(student_id, headers=COORDINATOR))
        assert repeat["version"] == first_read["version"], "a read is not a mutation"

    payload = {"expected_student_version": first_read["version"], "credits_awarded": 6}
    awarded = validate_success(client.award_claim(claim_id, payload, headers=COORDINATOR))
    assert_fields_equal(awarded, credits_awarded=6)

    # The award moved the ledger, so the identical payload is now stale. Rung 12
    # answers ahead of the terminal-claim rung 14.
    replay = client.award_claim(claim_id, payload, headers=COORDINATOR)
    validate_error(replay, ApiErrorId.ERR_STALE_STUDENT_VERSION, 412)

    current = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert current["version"] == first_read["version"] + 1
    terminal = client.award_claim(
        claim_id,
        {"expected_student_version": current["version"], "credits_awarded": 6},
        headers=COORDINATOR,
    )
    # With the token now fresh, the state rungs answer. Which one is not uniquely
    # determined: S3.5 refuses "any attempt to advance" a terminal claim with
    # `ERR_CLAIM_ALREADY_TERMINAL`, while rung 14's applies-to list omits awarding
    # and leaves it to rung 15a's `ERR_CLAIM_NOT_SCORED`. Either is PRD-faithful.
    assert terminal.status_code == 409, (
        "a fresh token reaches the state rungs, which refuse with 409, got %d"
        % terminal.status_code
    )
    validate_error_is_one_of(
        terminal,
        [ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL, ApiErrorId.ERR_CLAIM_NOT_SCORED],
    )

    # Rung 8 sits above both: a body with no token at all never reaches either.
    shapeless = client.award_claim(claim_id, {"credits_awarded": 6}, headers=COORDINATOR)
    validate_error(shapeless, ApiErrorId.ERR_INVALID_REQUEST, 400)

    unmoved = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert unmoved["version"] == current["version"], "three refusals wrote nothing"
    assert_ledger(unmoved, reserved=0, awarded=6, posted=0)


@pytest.fixture
def a_draft_claim_with_a_submitted_portfolio(client):
    """A DRAFT 6-credit claim whose portfolio is SUBMITTED at 9000 basis points.

    OC1 is mapped `PRIMARY` for its whole 8000 weight and OC2 `SUPPORTING` for half
    of its 2000, so the frozen provisional figure is 9000.
    """
    fx.set_clock(client, fx.CLOCK_EPOCH)
    program = _bscs(client)
    course = _cs150(client)
    student = _student(client, program["id"])
    outcomes = fx.outcomes_of(client, course["id"])
    claim, portfolio = _portfolio_claim(
        client, student["id"], course, outcomes, Alignment.SUPPORTING
    )
    return {
        "program": program,
        "course": course,
        "student": student,
        "claim": claim,
        "portfolio": portfolio,
    }


def test_the_submit_response_already_carries_every_field_it_caused(
    client, a_draft_claim_with_a_submitted_portfolio
):
    """One request settles the claim, the invoice, the ledger and the audit.

    PRD: "On success the portfolio's `status` becomes `SUBMITTED`, `submitted_at` is
    stamped with the logical clock, `provisional_coverage_bp` is recomputed and frozen,
    and that same value is copied onto the parent claim's `provisional_coverage_bp`."
    "`assessment_status` becomes `SUBMITTED` and `submitted_at` is stamped with the
    logical clock, while `claim_number` remains whatever was fixed at creation.
    `priority_tier` is set to `EXPEDITED` when `rush_requested` is true and to
    `STANDARD` otherwise. `credits_requested` is added to the student's
    `pla_credits_reserved`" "On a first submission the claim's invoice is created with
    its line set, subtotal, discount and total per §3.10, and the fee dimension advances
    `UNBILLED → INVOICED`."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response_that_causes_it
    """
    scenario = a_draft_claim_with_a_submitted_portfolio
    claim_id = scenario["claim"]["id"]
    student_id = scenario["student"]["id"]
    assert_fields_equal(
        scenario["portfolio"],
        status=PortfolioStatus.SUBMITTED,
        artifact_count=2,
        provisional_coverage_bp=9000,
    )

    submitted = validate_success(
        client.submit_claim(claim_id, headers=make_student_headers(student_id))
    )
    assert_claim_dimensions(
        submitted,
        assessment_status=AssessmentStatus.SUBMITTED,
        fee_status=FeeStatus.INVOICED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    assert_fields_equal(
        submitted, provisional_coverage_bp=9000, priority_tier=PriorityTier.STANDARD
    )
    assert_instant(submitted["submitted_at"], fx.CLOCK_EPOCH, "submitted_at")

    # The invoice the submission created is fully priced on the very next call.
    rows, meta = validate_paginated(client.list_invoices({"claim_id": claim_id}, headers=COORDINATOR))
    assert meta["total_count"] == 1, "exactly one invoice per claim"
    assert_invoice_money(
        rows[0],
        subtotal_cents=30000,
        discount_bp=1000,
        discount_cents=3000,
        total_cents=27000,
        paid_cents=0,
        balance_due_cents=27000,
    )

    reserved = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(reserved, reserved=6, awarded=0, posted=0)
    audit = get_success_data(client.get_graduation_audit(student_id, headers=COORDINATOR))
    assert_audit(
        audit,
        effective_pla_cap_credits=30,
        pla_credits_reserved=6,
        pla_cap_remaining_reserved_inclusive=24,
        pla_cap_remaining_posted_only=30,
    )

    # The design expects the portfolio to lock here; PRD S3.4 locks it only "When the
    # assessor finishes scoring", so it is still SUBMITTED with its frozen coverage.
    portfolio = get_success_data(
        client.get_portfolio(scenario["portfolio"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(
        portfolio, status=PortfolioStatus.SUBMITTED, provisional_coverage_bp=9000
    )
    assert_instant(portfolio["submitted_at"], fx.CLOCK_EPOCH, "portfolio submitted_at")

    baseline = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    for _ in range(3):
        again = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
        assert_fields_equal(
            again,
            provisional_coverage_bp=baseline["provisional_coverage_bp"],
            fee_status=baseline["fee_status"],
            version=baseline["version"],
        )


def test_the_award_and_the_posting_are_visible_to_the_very_next_read(
    client, a_scored_claim_awaiting_the_award_desk
):
    """Two ledger shelves move, and each response already reports the move.

    PRD: "A successful posting sets `credit_status` to `POSTED`, records `posted_term`,
    and sets `posted_credits` to `credits_awarded`. The ledger moves the credit one
    shelf along: `credits_awarded` leaves `pla_credits_awarded` and enters
    `pla_credits_posted`, so the reserved-inclusive total is unchanged by a posting
    while the posted-only total rises." "It counts **posted credit only**: claims whose
    `credit_status` is `POSTED`." "reports `total_credits_applied` as
    `institutional_credits_earned` plus `transfer_credits_accepted` plus
    `pla_credits_posted`."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response_that_causes_it
    """
    scenario = a_scored_claim_awaiting_the_award_desk
    student_id = scenario["student"]["id"]
    claim_id = scenario["claim"]["id"]

    before_award = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    awarded = validate_success(
        client.award_claim(
            claim_id,
            {"expected_student_version": before_award["version"], "credits_awarded": 6},
            headers=COORDINATOR,
        )
    )
    assert_claim_dimensions(
        awarded,
        assessment_status=AssessmentStatus.AWARDED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    assert_fields_equal(awarded, credits_awarded=6, posted_credits=None)
    after_award = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(after_award, reserved=0, awarded=6, posted=0)
    assert after_award["version"] == before_award["version"] + 1

    posted = validate_success(
        client.post_transcript(claim_id, {"posted_term": "2026FA"}, headers=REGISTRAR)
    )
    assert_claim_dimensions(posted, credit_status=CreditStatus.POSTED)
    assert_fields_equal(posted, posted_credits=6, posted_term="2026FA", credits_awarded=6)

    after_posting = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(after_posting, reserved=0, awarded=0, posted=6)
    assert after_posting["version"] == after_award["version"] + 1

    audit = get_success_data(client.get_graduation_audit(student_id, headers=REGISTRAR))
    assert_audit(
        audit,
        student_id=student_id,
        program_id=scenario["program"]["id"],
        effective_pla_cap_credits=30,
        pla_credits_posted=6,
        pla_credits_awarded=0,
        pla_credits_reserved=0,
        pla_cap_remaining_posted_only=24,
        pla_cap_remaining_reserved_inclusive=24,
        upper_division_pla_posted=0,
        upper_division_remaining=6,
        institutional_credits_earned=60,
        transfer_credits_accepted=0,
        total_credits_applied=66,
        residency_satisfied=True,
        audit_status=AuditStatus.DEFICIENT_CREDITS,
    )
