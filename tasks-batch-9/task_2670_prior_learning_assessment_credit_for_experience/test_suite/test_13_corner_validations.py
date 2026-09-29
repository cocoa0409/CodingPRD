"""Validation corners: one rung fires, the rungs beneath it stay silent.

Every refusal here is paired with the neighbouring request that succeeds, so a
blanket rejection is as visible as a missing check.
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
    assert_audit,
    assert_claim_dimensions,
    assert_fields_equal,
    assert_instant,
    assert_invoice_money,
    assert_ledger,
    ids_of,
)
from test_helpers.test_users import COORDINATOR, REGISTRAR, make_student_headers
from test_helpers.types import (
    Alignment,
    AppealStatus,
    AssessmentStatus,
    CourseLevel,
    CreditStatus,
    FeeStatus,
    PaymentMethod,
    PortfolioStatus,
    Recommendation,
    RuleStatus,
    SourceType,
)

CLOCK_EPOCH = "2026-08-01T00:00:00Z"


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


def _cs150(client, course_code="CS150", credits=6):
    return fx.new_course(
        client,
        course_code=course_code,
        department_code="CS",
        credits=credits,
        level=CourseLevel.LOWER,
        learning_outcomes=_cs150_outcomes(),
    )


def _student(client, program_id, student_number="S-1001", **overrides):
    return fx.new_student(
        client,
        program_id,
        student_number=student_number,
        transfer_credits_accepted=0,
        institutional_credits_earned=60,
        **overrides,
    )


def _two_artifact_portfolio(client, claim_id, student_id, outcomes):
    portfolio = fx.new_portfolio(client, claim_id, student_id)
    fx.attach_artifact(
        client, portfolio["id"], student_id, [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    fx.attach_artifact(
        client, portfolio["id"], student_id, [f.mapping(outcomes[1]["id"], Alignment.SUPPORTING)]
    )
    return portfolio


def _submitted_portfolio_claim(client, student_id, course, outcomes, credits_requested=6):
    claim = fx.new_claim(
        client,
        student_id,
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=credits_requested,
    )
    portfolio = _two_artifact_portfolio(client, claim["id"], student_id, outcomes)
    fx.submit_portfolio(client, portfolio["id"], student_id)
    fx.submit_claim(client, claim["id"], student_id)
    return claim, portfolio, fx.invoice_for_claim(client, claim["id"])


def _waive(client, invoice_id):
    return get_success_data(
        client.waive_invoice(
            invoice_id, {"waive_reason": "Institutional hardship waiver"}, headers=COORDINATOR
        )
    )


def test_the_clock_refuses_a_rewind_and_accepts_its_own_current_value(client):
    """A rejected rewind leaves the clock exactly where it stood.

    PRD: "The clock advances only when an operator explicitly sets it, supplying
    `current_utc`; the response reports the new `current_utc` alongside the
    `previous_utc` it replaced. A requested value earlier than the clock's present
    value is refused with `ERR_CLOCK_NOT_MONOTONIC` (422) — the clock never moves
    backwards, though setting it to exactly its current value is permitted."

    Design: Corner/validations/clock_rewind_rejected_as_not_monotonic
    """
    advanced = validate_success(
        client.set_clock("2026-08-05T00:00:00Z", headers=COORDINATOR)
    )
    assert_instant(advanced["current_utc"], "2026-08-05T00:00:00Z", "current_utc")
    assert_instant(advanced["previous_utc"], CLOCK_EPOCH, "previous_utc")

    rewound = client.set_clock("2026-08-04T23:59:59Z", headers=COORDINATOR)
    validate_error(rewound, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC, 422)

    standing_still = validate_success(
        client.set_clock("2026-08-05T00:00:00Z", headers=COORDINATOR)
    )
    assert_instant(standing_still["current_utc"], "2026-08-05T00:00:00Z", "current_utc")
    assert_instant(standing_still["previous_utc"], "2026-08-05T00:00:00Z", "previous_utc")

    forward = validate_success(
        client.set_clock("2026-08-05T00:00:01Z", headers=COORDINATOR)
    )
    assert_instant(forward["previous_utc"], "2026-08-05T00:00:00Z", "previous_utc")
    assert_instant(forward["current_utc"], "2026-08-05T00:00:01Z", "current_utc")


def test_a_second_claim_for_the_same_course_needs_the_superseding_link(client):
    """The escape hatch is naming the withdrawn claim, not merely having one.

    PRD: "(a) The student has no other claim for the same `course_id` in a
    non-terminal or `AWARDED` state, unless the new claim declares a
    `supersedes_claim_id` pointing at a `DENIED_FINAL` or `WITHDRAWN` claim for that
    course; failure is `ERR_DUPLICATE_CLAIM` (409) on claim creation."

    Design: Corner/validations/duplicate_active_claim_rejected_unless_it_supersedes_a_withdrawn_one
    """
    program = _bscs(client)
    course = _cs150(client)
    student = _student(client, program["id"])
    student_headers = make_student_headers(student["id"])
    first = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )

    duplicate = client.create_claim(
        f.claim_payload(
            student["id"],
            course["id"],
            source_type=SourceType.PORTFOLIO,
            credits_requested=6,
        ),
        headers=student_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CLAIM, 409)

    rows, _meta = validate_paginated(
        client.list_claims(
            {"student_id": student["id"], "course_id": course["id"]}, headers=COORDINATOR
        )
    )
    assert ids_of(rows) == [first["id"]], "the refused create must not have added a row"

    validate_success(
        client.withdraw_claim(
            first["id"], {"withdraw_reason": "Changed my mind"}, headers=student_headers
        )
    )
    successor = validate_success(
        client.create_claim(
            f.claim_payload(
                student["id"],
                course["id"],
                source_type=SourceType.PORTFOLIO,
                credits_requested=6,
                supersedes_claim_id=first["id"],
            ),
            headers=student_headers,
        ),
        201,
    )
    assert_fields_equal(successor, supersedes_claim_id=first["id"])
    assert_claim_dimensions(successor, assessment_status=AssessmentStatus.DRAFT)

    untouched = get_success_data(client.get_claim(first["id"], headers=COORDINATOR))
    assert_claim_dimensions(untouched, assessment_status=AssessmentStatus.WITHDRAWN)
    assert successor["claim_number"] != untouched["claim_number"]


@pytest.fixture
def invoiced_claim_awaiting_27000_cents(client):
    """A submitted portfolio claim whose invoice stands at 27000 cents unpaid."""
    program = _bscs(client)
    course = _cs150(client)
    student = _student(client, program["id"])
    outcomes = fx.outcomes_of(client, course["id"])
    claim, _portfolio, invoice = _submitted_portfolio_claim(
        client, student["id"], course, outcomes
    )
    return {"student": student, "claim": claim, "invoice": invoice}


def test_a_financial_aid_payment_is_refused_where_the_same_card_payment_lands(
    client, invoiced_claim_awaiting_27000_cents
):
    """The amount is exactly right; only the method is wrong.

    PRD: "A payment whose `method` is `FINANCIAL_AID` is refused, because assessment
    fees are institutional charges that Title IV aid may not cover and `aid_eligible`
    on every invoice is permanently false. Failure: `ERR_AID_NOT_APPLICABLE` (422)."
    "A `FINANCIAL_AID` payment is always refused with `ERR_AID_NOT_APPLICABLE`,
    because `aid_eligible` is false on every assessment-fee invoice without
    exception."

    Design: Corner/validations/financial_aid_payment_method_rejected_because_assessment_fees_are_aid_ineligible
    """
    scenario = invoiced_claim_awaiting_27000_cents
    invoice_id = scenario["invoice"]["id"]
    student_headers = make_student_headers(scenario["student"]["id"])
    assert scenario["invoice"]["aid_eligible"] is False
    assert_invoice_money(scenario["invoice"], total_cents=27000, balance_due_cents=27000)

    refused = client.pay_invoice(
        invoice_id,
        f.payment_payload(27000, PaymentMethod.FINANCIAL_AID),
        headers=student_headers,
    )
    validate_error(refused, ApiErrorId.ERR_AID_NOT_APPLICABLE, 422)

    untouched = get_success_data(client.get_invoice(invoice_id, headers=COORDINATOR))
    assert_invoice_money(untouched, paid_cents=0, balance_due_cents=27000)
    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, fee_status=FeeStatus.INVOICED)

    settled = validate_success(
        client.pay_invoice(
            invoice_id, f.payment_payload(27000, PaymentMethod.CARD), headers=student_headers
        )
    )
    assert_invoice_money(settled, paid_cents=27000, balance_due_cents=0)
    paid = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(paid, fee_status=FeeStatus.PAID)


def test_a_payment_above_the_balance_is_refused_rather_than_clamped(
    client, invoiced_claim_awaiting_27000_cents
):
    """8000 cents against a 7000-cent balance moves nothing at all.

    PRD: "`amount_cents` is at most the invoice's `balance_due_cents`; an overpayment
    is refused outright and never auto-refunded. Failure:
    `ERR_PAYMENT_EXCEEDS_BALANCE` (422)." "An invoice whose `fee_status` is
    `UNBILLED`, `WAIVED`, `REFUNDED` or `RETAINED` accepts no money movement, and an
    invoice already at `PAID` with `balance_due_cents` of 0 accepts no further
    payment. Failure: `ERR_INVOICE_NOT_PAYABLE` (409)."

    Design: Corner/validations/cumulative_payments_above_the_balance_rejected_as_exceeds_balance
    """
    scenario = invoiced_claim_awaiting_27000_cents
    invoice_id = scenario["invoice"]["id"]
    claim_id = scenario["claim"]["id"]
    student_headers = make_student_headers(scenario["student"]["id"])

    part = validate_success(
        client.pay_invoice(
            invoice_id, f.payment_payload(20000, PaymentMethod.CARD), headers=student_headers
        )
    )
    assert_invoice_money(part, paid_cents=20000, balance_due_cents=7000)
    assert_claim_dimensions(
        get_success_data(client.get_claim(claim_id, headers=COORDINATOR)),
        fee_status=FeeStatus.PARTIALLY_PAID,
    )

    over = client.pay_invoice(
        invoice_id, f.payment_payload(8000, PaymentMethod.CARD), headers=student_headers
    )
    validate_error(over, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, 422)
    unmoved = get_success_data(client.get_invoice(invoice_id, headers=COORDINATOR))
    assert_invoice_money(unmoved, paid_cents=20000, balance_due_cents=7000, refunded_cents=0)

    exact = validate_success(
        client.pay_invoice(
            invoice_id, f.payment_payload(7000, PaymentMethod.CARD), headers=student_headers
        )
    )
    assert_invoice_money(exact, paid_cents=27000, balance_due_cents=0)
    assert_claim_dimensions(
        get_success_data(client.get_claim(claim_id, headers=COORDINATOR)),
        fee_status=FeeStatus.PAID,
    )

    # A settled invoice fails the payability rung at 19, well above the overpayment
    # rung at 41, so the balance rule is no longer the one that speaks.
    once_more = client.pay_invoice(
        invoice_id, f.payment_payload(1, PaymentMethod.CARD), headers=student_headers
    )
    validate_error(once_more, ApiErrorId.ERR_INVOICE_NOT_PAYABLE, 409)


@pytest.fixture
def denied_claim_with_a_336_hour_window(client):
    """A denied PORTFOLIO claim whose appeal window closes at 2026-08-15T00:00:00Z.

    The invoice is waived rather than paid, so the assessor-assignment fee gate is
    cleared without any payment arithmetic and the scenario turns only on the clock.
    Two points on each outcome make verified coverage 5000, below the 7000 pass
    threshold, so the assessor completes with FAIL and the coordinator denies.
    """
    program = _bscs(client)
    course = _cs150(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = _student(client, program["id"])
    assessor = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
        appeal_panel_member=False,
    )
    claim, portfolio, invoice = _submitted_portfolio_claim(
        client, student["id"], course, outcomes
    )
    _waive(client, invoice["id"])
    assignment = fx.assign_assessor(client, claim["id"], assessor["id"])
    fx.accept_assignment(client, assignment["id"], assessor["id"])
    fx.score_all_outcomes(client, assignment["id"], assessor["id"], outcomes, [2, 2])
    completed = fx.complete_assignment(
        client, assignment["id"], assessor["id"], Recommendation.FAIL
    )
    assert_fields_equal(completed, verified_coverage_bp=5000)
    denied = get_success_data(
        client.deny_claim(
            claim["id"],
            {"denial_reason": "Verified coverage below the pass threshold"},
            headers=COORDINATOR,
        )
    )
    return {
        "student": student,
        "assessor": assessor,
        "claim": claim,
        "portfolio": portfolio,
        "invoice": invoice,
        "denied": denied,
    }


def test_an_appeal_filed_exactly_on_the_deadline_finds_the_window_closed(
    client, denied_claim_with_a_336_hour_window
):
    """The clock standing on 2026-08-15T00:00:00Z is one instant too late.

    PRD: "`assessment_status` becomes `DENIED`, the reason is recorded, and
    `appeal_deadline_at` is set to the logical clock advanced by 336 hours." "The
    logical clock reads strictly earlier than the claim's `appeal_deadline_at`; a
    clock standing exactly at the deadline finds it closed. Failure:
    `ERR_APPEAL_WINDOW_CLOSED` (409)."

    Design: Corner/validations/appeal_filed_exactly_at_the_336_hour_deadline_rejected_as_window_closed
    """
    scenario = denied_claim_with_a_336_hour_window
    denied = scenario["denied"]
    assert_claim_dimensions(denied, assessment_status=AssessmentStatus.DENIED)
    assert_fields_equal(denied, verified_coverage_bp=5000, appeal_count=0)
    # Denial at the epoch plus 336 hours is exactly the fifteenth of August.
    assert_instant(denied["appeal_deadline_at"], "2026-08-15T00:00:00Z", "appeal_deadline_at")

    moved = fx.set_clock(client, "2026-08-15T00:00:00Z")
    assert_instant(moved["current_utc"], denied["appeal_deadline_at"], "current_utc")

    refused = client.create_appeal(
        {"claim_id": scenario["claim"]["id"], "grounds": "The assessor overlooked two artifacts"},
        headers=make_student_headers(scenario["student"]["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED, 409)

    rows, _meta = validate_paginated(
        client.list_appeals({"claim_id": scenario["claim"]["id"]}, headers=COORDINATOR)
    )
    assert ids_of(rows) == [], "a refused filing must not leave an Appeal behind"

    unchanged = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(unchanged, assessment_status=AssessmentStatus.DENIED)
    assert_fields_equal(unchanged, appeal_count=0)


def test_an_appeal_filed_one_second_earlier_is_accepted(
    client, denied_claim_with_a_336_hour_window
):
    """A clock strictly earlier than the deadline still finds the window open.

    PRD: "Filing creates an `Appeal` in `status` `FILED` with `filed_at` stamped from
    the logical clock, and it snapshots `prior_scorer_assessor_ids` — the identifiers
    of every assessor who scored this claim." "The claim's `appeal_count` increments
    by one, its `assessment_status` advances `DENIED → APPEAL_PENDING`, and its
    `version` increments."

    Design: Corner/validations/appeal_filed_exactly_at_the_336_hour_deadline_rejected_as_window_closed
    """
    scenario = denied_claim_with_a_336_hour_window
    fx.set_clock(client, "2026-08-14T23:59:59Z")

    filed = validate_success(
        client.create_appeal(
            {
                "claim_id": scenario["claim"]["id"],
                "grounds": "The assessor overlooked two artifacts",
            },
            headers=make_student_headers(scenario["student"]["id"]),
        ),
        201,
    )
    assert_fields_equal(
        filed,
        status=AppealStatus.FILED,
        reviewer_assessor_id=None,
        assigned_at=None,
        decided_at=None,
        decision_note=None,
    )
    assert_instant(filed["filed_at"], "2026-08-14T23:59:59Z", "filed_at")

    stored = get_success_data(client.get_appeal(filed["id"], headers=COORDINATOR))
    assert stored["prior_scorer_assessor_ids"] == [scenario["assessor"]["id"]], (
        "the snapshot names every assessor who scored this claim"
    )

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.APPEAL_PENDING)
    assert_fields_equal(claim, appeal_count=1)
    assert claim["version"] == scenario["denied"]["version"] + 1, (
        "filing increments the claim's version exactly once"
    )


@pytest.fixture
def an_empty_portfolio(client):
    """A DRAFT PORTFOLIO claim whose portfolio holds no artifacts at all."""
    program = _bscs(client)
    course = _cs150(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = _student(client, program["id"])
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    portfolio = fx.new_portfolio(client, claim["id"], student["id"])
    return {
        "student": student,
        "outcomes": outcomes,
        "claim": claim,
        "portfolio": portfolio,
    }


def test_an_empty_portfolio_reports_the_artifact_floor_not_the_coverage_floor(
    client, an_empty_portfolio
):
    """Both evidence floors are violated, and the lower-numbered rung answers.

    PRD: "A new portfolio begins in `status` `DRAFT` with `artifact_count` at 0,
    `revision_round` at 0, `submitted_at` null and both `provisional_coverage_bp` and
    `verified_coverage_bp` null." "First, `artifact_count` must be at least 1, or the
    submission fails with `ERR_PORTFOLIO_NO_ARTIFACTS`." "A `PORTFOLIO`-source
    claim's portfolio has `artifact_count` of at least 1. Failure:
    `ERR_PORTFOLIO_NO_ARTIFACTS` (422). Applies to submitting a portfolio and
    submitting a claim."

    Design: Corner/validations/portfolio_submit_with_zero_artifacts_returns_priority_34_not_the_coverage_error
    """
    scenario = an_empty_portfolio
    student_headers = make_student_headers(scenario["student"]["id"])
    portfolio_id = scenario["portfolio"]["id"]

    before = get_success_data(client.get_portfolio(portfolio_id, headers=COORDINATOR))
    assert_fields_equal(
        before,
        status=PortfolioStatus.DRAFT,
        artifact_count=0,
        provisional_coverage_bp=None,
        verified_coverage_bp=None,
        submitted_at=None,
    )

    refused = client.submit_portfolio(portfolio_id, headers=student_headers)
    validate_error(refused, ApiErrorId.ERR_PORTFOLIO_NO_ARTIFACTS, 422)
    assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_INSUFFICIENT_OUTCOME_COVERAGE, (
        "the artifact floor outranks the coverage floor"
    )

    unchanged = get_success_data(client.get_portfolio(portfolio_id, headers=COORDINATOR))
    assert_fields_equal(unchanged, status=PortfolioStatus.DRAFT, submitted_at=None)

    claim_refused = client.submit_claim(scenario["claim"]["id"], headers=student_headers)
    validate_error(claim_refused, ApiErrorId.ERR_PORTFOLIO_NO_ARTIFACTS, 422)
    rows, _meta = validate_paginated(
        client.list_invoices({"claim_id": scenario["claim"]["id"]}, headers=COORDINATOR)
    )
    assert ids_of(rows) == [], "a refused first submission creates no invoice"

    still_draft = get_success_data(
        client.get_claim(scenario["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(still_draft, assessment_status=AssessmentStatus.DRAFT)


def test_one_supporting_artifact_clears_the_floor_and_exposes_the_coverage_rung(
    client, an_empty_portfolio
):
    """A single SUPPORTING mapping on the 2000-weight outcome reaches only 1000.

    PRD: "Each outcome earns a credit figure: 10000 basis points when any artifact of
    the portfolio maps that outcome with `alignment` `PRIMARY`; otherwise 5000 basis
    points when any artifact maps it with `alignment` `SUPPORTING`; otherwise 0."
    "Second, the recomputed `provisional_coverage_bp` must be at least 5000 basis
    points — half the course's weighted outcomes reached, counting a `SUPPORTING`
    mapping as half credit — or the submission fails with
    `ERR_INSUFFICIENT_OUTCOME_COVERAGE`."

    Design: Corner/validations/portfolio_submit_with_zero_artifacts_returns_priority_34_not_the_coverage_error
    """
    scenario = an_empty_portfolio
    portfolio_id = scenario["portfolio"]["id"]
    fx.attach_artifact(
        client,
        portfolio_id,
        scenario["student"]["id"],
        [f.mapping(scenario["outcomes"][1]["id"], Alignment.SUPPORTING)],
    )

    # OC1 unmapped contributes 0; OC2 at half credit contributes 2000 * 5000 / 10000.
    stocked = get_success_data(client.get_portfolio(portfolio_id, headers=COORDINATOR))
    assert_fields_equal(stocked, artifact_count=1, provisional_coverage_bp=1000)

    refused = client.submit_portfolio(
        portfolio_id, headers=make_student_headers(scenario["student"]["id"])
    )
    validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_OUTCOME_COVERAGE, 422)

    unchanged = get_success_data(client.get_portfolio(portfolio_id, headers=COORDINATOR))
    assert_fields_equal(unchanged, status=PortfolioStatus.DRAFT, submitted_at=None)


@pytest.fixture
def awarded_claim_awaiting_the_registrar(client):
    """A 6-credit LOWER claim awarded in full and still ``NOT_POSTED``.

    Both artifacts map their outcome as ``PRIMARY`` so provisional coverage is 10000,
    and four points on each outcome make verified coverage 10000 as well, which is a
    clean PASS. The invoice is waived, which is one of the four fee states a posting
    accepts.
    """
    program = _bscs(client)
    course = _cs150(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = _student(client, program["id"])
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
    for outcome in outcomes:
        fx.attach_artifact(
            client, portfolio["id"], student["id"], [f.mapping(outcome["id"], Alignment.PRIMARY)]
        )
    fx.submit_portfolio(client, portfolio["id"], student["id"])
    fx.submit_claim(client, claim["id"], student["id"])
    _waive(client, fx.invoice_for_claim(client, claim["id"])["id"])
    fx.scored_claim(client, claim["id"], assessor["id"], outcomes, [4, 4])
    awarded = fx.award_claim(client, claim["id"], student["id"], credits_awarded=6)
    assert_claim_dimensions(
        awarded,
        assessment_status=AssessmentStatus.AWARDED,
        fee_status=FeeStatus.WAIVED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    return {"program": program, "student": student, "claim": claim}


def test_a_collapsed_residency_headroom_answers_ahead_of_the_cap_gate(
    client, awarded_claim_awaiting_the_registrar
):
    """Transfer credit raised after the award breaks residency and the cap at once.

    PRD: "the `effective_pla_cap_credits` for this student — the smaller of the
    programme ceiling and the student's residency headroom". "After the posting, the
    student's `transfer_credits_accepted` plus `pla_credits_posted` remains at most
    `total_credits_required` minus `residency_min_credits`. Failure:
    `ERR_RESIDENCY_REQUIREMENT_VIOLATION` (409)."

    Design: Corner/validations/residency_violation_at_posting_returns_priority_26_ahead_of_the_cap_error
    """
    scenario = awarded_claim_awaiting_the_registrar
    student_id = scenario["student"]["id"]

    before = get_success_data(client.get_graduation_audit(student_id, headers=REGISTRAR))
    assert_audit(
        before,
        effective_pla_cap_credits=30,
        pla_credits_awarded=6,
        pla_credits_posted=0,
        pla_cap_remaining_posted_only=30,
    )

    amended = get_success_data(
        client.patch_student(student_id, {"transfer_credits_accepted": 88}, headers=REGISTRAR)
    )
    assert_fields_equal(amended, transfer_credits_accepted=88)

    # The residency headroom of 120 - 30 - 88 is 2, well under the programme's 30.
    after = get_success_data(client.get_graduation_audit(student_id, headers=REGISTRAR))
    assert_audit(
        after,
        effective_pla_cap_credits=2,
        pla_credits_awarded=6,
        pla_credits_posted=0,
        pla_cap_remaining_posted_only=2,
    )

    refused = client.post_transcript(
        scenario["claim"]["id"], {"posted_term": "2026FA"}, headers=REGISTRAR
    )
    validate_error(refused, ApiErrorId.ERR_RESIDENCY_REQUIREMENT_VIOLATION, 409)
    assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_PLA_CAP_EXCEEDED, (
        "residency sits above the posted-only cap gate on the ladder"
    )

    unposted = get_success_data(
        client.get_claim(scenario["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(unposted, credit_status=CreditStatus.NOT_POSTED)
    assert_fields_equal(unposted, posted_term=None, posted_credits=None)

    student = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(student, awarded=6, posted=0)


def test_restoring_two_credits_of_headroom_lets_the_posting_through(
    client, awarded_claim_awaiting_the_registrar
):
    """With transfer credit back at 80 the same posting is accepted unchanged.

    PRD: "A successful posting sets `credit_status` to `POSTED`, records
    `posted_term`, and sets `posted_credits` to `credits_awarded`. The ledger moves
    the credit one shelf along: `credits_awarded` leaves `pla_credits_awarded` and
    enters `pla_credits_posted`".

    Design: Corner/validations/residency_violation_at_posting_returns_priority_26_ahead_of_the_cap_error
    """
    scenario = awarded_claim_awaiting_the_registrar
    student_id = scenario["student"]["id"]
    claim_id = scenario["claim"]["id"]

    get_success_data(
        client.patch_student(student_id, {"transfer_credits_accepted": 88}, headers=REGISTRAR)
    )
    validate_error(
        client.post_transcript(claim_id, {"posted_term": "2026FA"}, headers=REGISTRAR),
        ApiErrorId.ERR_RESIDENCY_REQUIREMENT_VIOLATION,
        409,
    )

    # 80 transfer credits leave a headroom of 10, which covers the 6 being posted.
    get_success_data(
        client.patch_student(student_id, {"transfer_credits_accepted": 80}, headers=REGISTRAR)
    )
    posted = validate_success(
        client.post_transcript(claim_id, {"posted_term": "2026FA"}, headers=REGISTRAR)
    )
    assert_claim_dimensions(posted, credit_status=CreditStatus.POSTED)
    assert_fields_equal(posted, posted_term="2026FA", posted_credits=6)

    student = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(student, awarded=0, posted=6)

    audit = get_success_data(client.get_graduation_audit(student_id, headers=REGISTRAR))
    assert_audit(
        audit,
        effective_pla_cap_credits=10,
        pla_credits_posted=6,
        pla_cap_remaining_posted_only=4,
        total_credits_applied=146,
    )


def test_an_exam_sat_before_the_crosswalk_opened_is_refused(client):
    """The window is measured against ``attempt_date``, not against the clock.

    PRD: "For `CREDIT_BY_EXAM` and `INDUSTRY_CREDENTIAL` claims, `attempt_date` falls
    inside the pinned rule's validity window, which includes `effective_from` and
    excludes `effective_to`. Failure: `ERR_ATTEMPT_DATE_OUTSIDE_WINDOW` (422). Applies
    to claim creation and claim submission."

    Design: Corner/validations/attempt_date_before_the_pinned_rule_window_is_rejected
    """
    program = _bscs(client)
    course = _cs150(client)
    student = _student(client, program["id"])
    recommendation = fx.published_recommendation(
        client,
        credential_code="CLEP-CS",
        source_type=SourceType.CREDIT_BY_EXAM,
        recommended_credits=6,
        recommended_level=CourseLevel.LOWER,
        effective_from="2026-06-01T00:00:00Z",
    )
    rule = fx.approved_rule(
        client,
        recommendation["id"],
        course["id"],
        awarded_credits=6,
        effective_from="2026-06-01T00:00:00Z",
    )
    assert_fields_equal(rule, status=RuleStatus.APPROVED, effective_to=None)
    assert_instant(rule["effective_from"], "2026-06-01T00:00:00Z", "effective_from")

    student_headers = make_student_headers(student["id"])
    payload = f.claim_payload(
        student["id"],
        course["id"],
        source_type=SourceType.CREDIT_BY_EXAM,
        credits_requested=6,
        articulation_rule_id=rule["id"],
        attempt_date="2026-05-20T00:00:00Z",
    )
    refused = client.create_claim(payload, headers=student_headers)
    validate_error(refused, ApiErrorId.ERR_ATTEMPT_DATE_OUTSIDE_WINDOW, 422)
    assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_ARTICULATION_NOT_APPROVED, (
        "the rule is approved; only the attempt date is out of range"
    )

    rows, _meta = validate_paginated(
        client.list_claims({"student_id": student["id"]}, headers=COORDINATOR)
    )
    assert ids_of(rows) == [], "a refused creation leaves no claim row"
    invoices, _invoice_meta = validate_paginated(
        client.list_invoices({"student_id": student["id"]}, headers=COORDINATOR)
    )
    assert ids_of(invoices) == [], "no invoice exists before a claim exists"

    # The lower bound of the window is inclusive, so the opening instant is inside it.
    payload["attempt_date"] = "2026-06-01T00:00:00Z"
    accepted = validate_success(client.create_claim(payload, headers=student_headers), 201)
    assert_claim_dimensions(
        accepted,
        assessment_status=AssessmentStatus.DRAFT,
        fee_status=FeeStatus.UNBILLED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    assert_instant(accepted["attempt_date"], "2026-06-01T00:00:00Z", "attempt_date")

    ledger = get_success_data(client.get_student(student["id"], headers=COORDINATOR))
    assert_ledger(ledger, reserved=0, awarded=0, posted=0)


def test_a_credit_request_outside_the_courses_own_range_is_refused(client):
    """Seven credits against a six-credit course, and zero credits, both fail.

    PRD: "The `credits_requested` figure must be an integer of at least 1 and at most
    the target course's `credits`, failing which the claim is refused with
    `ERR_INVALID_CREDIT_REQUEST`."

    Design: Corner/validations/claim_requesting_more_credits_than_the_course_carries_is_rejected
    """
    program = _bscs(client)
    course = _cs150(client)
    other = _cs150(client, course_code="CS151", credits=3)
    student = _student(client, program["id"])
    student_headers = make_student_headers(student["id"])
    assert_fields_equal(course, credits=6)

    for requested in (7, 0):
        refused = client.create_claim(
            f.claim_payload(
                student["id"],
                course["id"],
                source_type=SourceType.PORTFOLIO,
                credits_requested=requested,
            ),
            headers=student_headers,
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_CREDIT_REQUEST, 422)

    at_ceiling = validate_success(
        client.create_claim(
            f.claim_payload(
                student["id"],
                course["id"],
                source_type=SourceType.PORTFOLIO,
                credits_requested=6,
            ),
            headers=student_headers,
        ),
        201,
    )
    at_floor = validate_success(
        client.create_claim(
            f.claim_payload(
                student["id"],
                other["id"],
                source_type=SourceType.PORTFOLIO,
                credits_requested=1,
            ),
            headers=student_headers,
        ),
        201,
    )
    assert_fields_equal(at_ceiling, credits_requested=6, claim_number=1)
    assert_fields_equal(at_floor, credits_requested=1, claim_number=2)

    rows, _meta = validate_paginated(
        client.list_claims({"student_id": student["id"]}, headers=COORDINATOR)
    )
    assert ids_of(rows) == [at_ceiling["id"], at_floor["id"]], (
        "only the two accepted requests left a row behind"
    )


def test_a_claim_whose_every_gate_holds_is_submitted_invoiced_and_reserved(client):
    """Nothing on the ladder fires, and all three consequences of a submit land.

    PRD: "A submission that does reach `SUBMITTED` has five effects.
    `assessment_status` becomes `SUBMITTED` and `submitted_at` is stamped with the
    logical clock". "`credits_requested` is added to the student's
    `pla_credits_reserved`, and when the course's `level` is `UPPER` the same amount
    is added to `pla_upper_division_committed`; the student's `version` increments by
    one. On a first submission the claim's invoice is created with its line set,
    subtotal, discount and total per §3.10, and the fee dimension advances `UNBILLED →
    INVOICED`." "It reports both capacity variants side by side as
    `pla_cap_remaining_posted_only` and `pla_cap_remaining_reserved_inclusive`,
    precisely so the divergence between them is directly observable."

    Design: Corner/validations/claim_submit_succeeds_when_every_gate_is_satisfied
    """
    program = _bscs(client)
    course = _cs150(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = _student(client, program["id"])
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    portfolio = _two_artifact_portfolio(client, claim["id"], student["id"], outcomes)
    # OC1 at full credit and OC2 at half: (8000 * 10000 + 2000 * 5000) / 10000.
    submitted_portfolio = fx.submit_portfolio(client, portfolio["id"], student["id"])
    assert_fields_equal(
        submitted_portfolio, status=PortfolioStatus.SUBMITTED, provisional_coverage_bp=9000
    )

    before = get_success_data(client.get_student(student["id"], headers=COORDINATOR))
    assert_ledger(before, reserved=0)

    submitted = validate_success(
        client.submit_claim(claim["id"], headers=make_student_headers(student["id"]))
    )
    assert_claim_dimensions(
        submitted,
        assessment_status=AssessmentStatus.SUBMITTED,
        fee_status=FeeStatus.INVOICED,
    )
    assert_fields_equal(submitted, provisional_coverage_bp=9000)
    assert_instant(submitted["submitted_at"], CLOCK_EPOCH, "submitted_at")

    # PORTFOLIO base 15000 plus 2500 per credit over 6 credits, two artifacts so no
    # tier surcharge, and a 30000 subtotal earns the 1000 basis point tier.
    invoice = fx.invoice_for_claim(client, claim["id"])
    assert_invoice_money(
        invoice,
        subtotal_cents=30000,
        discount_bp=1000,
        discount_cents=3000,
        total_cents=27000,
        paid_cents=0,
        balance_due_cents=27000,
    )

    after = get_success_data(client.get_student(student["id"], headers=COORDINATOR))
    assert_ledger(after, reserved=6, awarded=0, posted=0)
    assert after["version"] == before["version"] + 1, (
        "the submit increments the student's version exactly once"
    )

    audit = get_success_data(client.get_graduation_audit(student["id"], headers=REGISTRAR))
    assert_audit(
        audit,
        effective_pla_cap_credits=30,
        pla_credits_reserved=6,
        pla_cap_remaining_reserved_inclusive=24,
        pla_cap_remaining_posted_only=30,
    )
