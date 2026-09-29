"""Calculation corners: thresholds, selector order, frozen curves and constants.

Every figure asserted here is re-derived from the PRD's own arithmetic rather
than read back from the system, so a formula that is merely self-consistent still
fails.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_audit,
    assert_claim_dimensions,
    assert_fields_equal,
    assert_instant,
    assert_invoice_money,
    assert_ledger,
    assert_line_absent,
    assert_sla,
)
from test_helpers.test_users import COORDINATOR, REGISTRAR, make_student_headers
from test_helpers.types import (
    Alignment,
    AssessmentStatus,
    AssignmentStatus,
    AuditStatus,
    CourseLevel,
    FeeStatus,
    InvoiceLineKind,
    PortfolioStatus,
    RecommendationStatus,
    RevokeReason,
    RuleStatus,
    SelectionReason,
    SlaState,
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


def _cs150(client):
    return fx.new_course(
        client,
        course_code="CS150",
        department_code="CS",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=_cs150_outcomes(),
    )


def _two_artifact_portfolio(client, claim_id, student_id, outcomes):
    """A DRAFT portfolio: OC1 mapped PRIMARY and OC2 mapped SUPPORTING.

    Two artifacts keep both the artifact surcharge tier and the turnaround
    multiplier tier on their lowest rung.
    """
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


@pytest.fixture
def assignment_with_a_240_hour_allowance(client):
    """One assignment issued at the epoch on a 240-hour turnaround allowance.

    A PORTFOLIO source carries a base allowance of 240 hours; two artifacts keep
    the multiplier at 10000 basis points and the claim is not rushed, so
    ``sla_hours`` is exactly 240.
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
    outcomes = fx.outcomes_of(client, course["id"])
    claim, portfolio, invoice = _submitted_portfolio_claim(
        client, student["id"], course, outcomes
    )
    _waive(client, invoice["id"])
    assignment = fx.assign_assessor(client, claim["id"], assessor["id"])
    return {
        "student": student,
        "assessor": assessor,
        "claim": claim,
        "portfolio": portfolio,
        "assignment": assignment,
    }


def test_both_service_level_rungs_are_inclusive_at_their_thresholds(
    client, assignment_with_a_240_hour_allowance
):
    """7000, 8000, 9000 and 10000 basis points read ON_TRACK, AT_RISK, AT_RISK, BREACHED.

    PRD: "`elapsed_bp` is that elapsed figure multiplied by 10000, divided by
    `sla_hours`, rounded half up. `sla_state` is `BREACHED` when `elapsed_bp` is at
    least 10000, `AT_RISK` when it is at least 8000 but below 10000, and `ON_TRACK`
    otherwise. Both comparisons are inclusive: a clock standing exactly at
    `at_risk_at` reports `AT_RISK`, and a clock standing exactly at `due_at` reports
    `BREACHED`." "Only assignments in `ASSIGNED` or `ACCEPTED` are candidates for
    revocation by the sweep".

    Design: Corner/calculations/assignment_sla_state_boundaries_are_inclusive_on_both_rungs
    """
    scenario = assignment_with_a_240_hour_allowance
    assignment_id = scenario["assignment"]["id"]
    # 240 hours is 10 days; the at-risk offset is 240 * 8000 / 10000 == 192 hours.
    assert_sla(
        scenario["assignment"],
        sla_hours=240,
        due_at="2026-08-11T00:00:00Z",
        at_risk_at="2026-08-09T00:00:00Z",
    )
    assert_instant(scenario["assignment"]["assigned_at"], CLOCK_EPOCH, "assigned_at")

    ladder = [
        ("2026-08-08T00:00:00Z", 7000, SlaState.ON_TRACK),
        ("2026-08-09T00:00:00Z", 8000, SlaState.AT_RISK),
        ("2026-08-10T00:00:00Z", 9000, SlaState.AT_RISK),
        ("2026-08-11T00:00:00Z", 10000, SlaState.BREACHED),
    ]
    for instant, expected_bp, expected_state in ladder:
        fx.set_clock(client, instant)
        read = get_success_data(client.get_assignment(assignment_id, headers=COORDINATOR))
        assert_sla(read, elapsed_bp=expected_bp, sla_state=expected_state)
        assert_fields_equal(read, status=AssignmentStatus.ASSIGNED)

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_fields_equal(claim, sla_breach_count=0)
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.UNDER_ASSESSMENT)


@pytest.fixture
def three_idle_assessors_and_a_settled_claim(client):
    """E-9001 rank 2, then E-9002 rank 3, then E-9003 rank 3, all idle.

    The creation order is what makes the rank-3 tie decidable: E-9002 is registered
    before E-9003.
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
    first = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    second = fx.new_assessor(
        client,
        employee_number="E-9002",
        department_code="CS",
        credential_rank=3,
        max_concurrent_assignments=3,
    )
    third = fx.new_assessor(
        client,
        employee_number="E-9003",
        department_code="CS",
        credential_rank=3,
        max_concurrent_assignments=3,
    )
    outcomes = fx.outcomes_of(client, course["id"])
    claim, _portfolio, invoice = _submitted_portfolio_claim(
        client, student["id"], course, outcomes
    )
    _waive(client, invoice["id"])
    return {"claim": claim, "first": first, "second": second, "third": third}


def test_auto_selection_prefers_rank_then_the_longer_registered_assessor(
    client, three_idle_assessors_and_a_settled_claim
):
    """Three idle candidates: rank descending eliminates one, creation order the next.

    PRD: "When the coordinator omits `assessor_id`, the server ranks the surviving
    pool and takes the first row. The ordering is by `active_assignment_count`
    ascending, then `credential_rank` descending, then `created_at` ascending, then
    `employee_number` ascending. That is a total order because `employee_number` is
    unique, so the choice is fully deterministic; no random property, and
    specifically never the row's `id`, participates in the filter, the ranking or any
    tie-break."

    Design: Corner/calculations/assessor_auto_selection_ranks_by_load_then_rank_then_created_at
    """
    scenario = three_idle_assessors_and_a_settled_claim
    chosen = validate_success(
        client.create_assignment(scenario["claim"]["id"], {}, headers=COORDINATOR), 201
    )
    assert_fields_equal(
        chosen,
        assessor_id=scenario["second"]["id"],
        status=AssignmentStatus.ASSIGNED,
        selection_reason=SelectionReason.AUTO_SELECTED,
    )
    assert chosen["assessor_id"] != scenario["first"]["id"], (
        "credential_rank 2 must lose to rank 3 under rank descending"
    )
    assert chosen["assessor_id"] != scenario["third"]["id"], (
        "the rank-3 tie must break on created_at ascending"
    )

    for key, expected in (("first", 0), ("second", 1), ("third", 0)):
        assessor = get_success_data(
            client.get_assessor(scenario[key]["id"], headers=COORDINATOR)
        )
        assert_fields_equal(assessor, active_assignment_count=expected)

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.UNDER_ASSESSMENT)


@pytest.fixture
def a_frozen_deadline_and_a_grown_portfolio(client):
    """One assignment issued on 2 artifacts, then the portfolio grows to 4.

    The revision request revokes the first assignment and reopens the portfolio, two
    more artifacts are attached, the claim is resubmitted — which reprices the
    invoice onto the 4-through-8 artifact tier — the new balance is settled, and the
    clock advances one day before the replacement is issued.
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
    first = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    second = fx.new_assessor(
        client,
        employee_number="E-9002",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    outcomes = fx.outcomes_of(client, course["id"])
    claim, portfolio, invoice = _submitted_portfolio_claim(
        client, student["id"], course, outcomes
    )
    fx.pay_invoice_in_full(client, claim["id"], student["id"])
    original = fx.assign_assessor(client, claim["id"], first["id"])
    get_success_data(
        client.request_revision(
            claim["id"],
            {"revision_note": "Add two more work products covering OC2"},
            headers=COORDINATOR,
        )
    )
    fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    fx.attach_artifact(
        client,
        portfolio["id"],
        student["id"],
        [f.mapping(outcomes[1]["id"], Alignment.SUPPORTING)],
    )
    fx.submit_portfolio(client, portfolio["id"], student["id"])
    fx.submit_claim(client, claim["id"], student["id"])
    get_success_data(
        client.pay_invoice(
            invoice["id"],
            f.payment_payload(3600),
            headers=make_student_headers(student["id"]),
        )
    )
    fx.set_clock(client, "2026-08-02T00:00:00Z")
    return {
        "student": student,
        "second": second,
        "claim": claim,
        "portfolio": portfolio,
        "invoice": invoice,
        "original": original,
    }


def test_a_grown_portfolio_reprices_the_invoice_but_never_the_issued_deadline(
    client, a_frozen_deadline_and_a_grown_portfolio
):
    """The old assignment keeps 240 hours while the replacement is issued 300.

    PRD: "Later artifact edits never move an existing assignment's `due_at`; only a
    newly created assignment picks up a new tier." "The artifact tier then stretches
    it: a portfolio holding 3 artifacts or fewer applies a multiplier of 10000 basis
    points (no change), one holding 4 through 8 artifacts applies 12500 basis points,
    and one holding 9 or more applies 15000 basis points". "The existing invoice is
    recomputed rather than recreated — the artifact tier and rush lines may well have
    changed since the first pricing — and `recompute_count` increments by one."

    Design: Corner/calculations/existing_assignment_due_at_frozen_while_replacement_picks_new_artifact_tier
    """
    scenario = a_frozen_deadline_and_a_grown_portfolio
    stale = get_success_data(
        client.get_assignment(scenario["original"]["id"], headers=COORDINATOR)
    )
    assert_sla(stale, sla_hours=240, due_at="2026-08-11T00:00:00Z")
    assert_fields_equal(
        stale, status=AssignmentStatus.REVOKED, revoke_reason=RevokeReason.REVISION_REQUESTED
    )

    portfolio = get_success_data(
        client.get_portfolio(scenario["portfolio"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(portfolio, artifact_count=4, revision_round=1)
    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_fields_equal(claim, revision_round=1)

    # 15000 base plus 2500 per credit over 6 credits plus the 4000-cent tier line.
    invoice = get_success_data(
        client.get_invoice(scenario["invoice"]["id"], headers=COORDINATOR)
    )
    assert_invoice_money(
        invoice,
        subtotal_cents=34000,
        discount_bp=1000,
        discount_cents=3400,
        total_cents=30600,
        paid_cents=30600,
        balance_due_cents=0,
        recompute_count=1,
    )
    assert_claim_dimensions(claim, fee_status=FeeStatus.PAID)

    replacement = validate_success(
        client.create_assignment(
            scenario["claim"]["id"], {"assessor_id": scenario["second"]["id"]}, headers=COORDINATOR
        ),
        201,
    )
    assert_fields_equal(replacement, assessor_id=scenario["second"]["id"])
    assert_instant(replacement["assigned_at"], "2026-08-02T00:00:00Z", "assigned_at")
    # 240 * 12500 / 10000 == 300 hours, and 300 * 8000 / 10000 == 240 hours.
    assert_sla(
        replacement,
        sla_hours=300,
        due_at="2026-08-14T12:00:00Z",
        at_risk_at="2026-08-12T00:00:00Z",
    )


@pytest.fixture
def two_students_with_nothing_posted(client):
    """Two students of the same programme, one 30 institutional credits short."""
    program = _bscs(client)
    short = fx.new_student(
        client,
        program["id"],
        student_number="S-1001",
        transfer_credits_accepted=0,
        institutional_credits_earned=90,
    )
    complete = fx.new_student(
        client,
        program["id"],
        student_number="S-1002",
        transfer_credits_accepted=0,
        institutional_credits_earned=120,
    )
    return {"program": program, "short": short, "complete": complete}


def test_the_audit_status_ladder_reports_the_first_condition_that_holds(
    client, two_students_with_nothing_posted
):
    """Residency is clean and the cap is clean, so only the credit total decides.

    PRD: "`audit_status` is evaluated in exactly this order, and the order is part of
    the specification. When `residency_satisfied` is false the status is
    `RESIDENCY_DEFICIENT`, and no other condition is consulted. Otherwise, when
    `pla_credits_posted` exceeds the effective cap the status is `PLA_CAP_VIOLATION`.
    Otherwise, when `total_credits_applied` is below the programme's
    `total_credits_required` the status is `DEFICIENT_CREDITS`. Otherwise the status
    is `ELIGIBLE`." "reports `total_credits_applied` as `institutional_credits_earned`
    plus `transfer_credits_accepted` plus `pla_credits_posted`."

    Design: Corner/calculations/graduation_audit_status_order_residency_then_cap_then_credits
    """
    scenario = two_students_with_nothing_posted
    expectations = [
        ("short", 90, AuditStatus.DEFICIENT_CREDITS),
        ("complete", 120, AuditStatus.ELIGIBLE),
    ]
    for key, applied, status in expectations:
        audit = get_success_data(
            client.get_graduation_audit(scenario[key]["id"], headers=REGISTRAR)
        )
        assert_audit(
            audit,
            student_id=scenario[key]["id"],
            program_id=scenario["program"]["id"],
            total_credits_applied=applied,
            residency_satisfied=True,
            audit_status=status,
        )
        assert audit["audit_status"] not in (
            AuditStatus.PLA_CAP_VIOLATION,
            AuditStatus.RESIDENCY_DEFICIENT,
        )
        assert_audit(audit, pla_credits_posted=0, pla_credits_reserved=0, pla_credits_awarded=0)
        # The programme ceiling of 30 binds below the residency headroom of 90, and
        # with no claim in existence both capacity variants coincide.
        assert_audit(
            audit,
            effective_pla_cap_credits=30,
            pla_cap_remaining_posted_only=30,
            pla_cap_remaining_reserved_inclusive=30,
        )
        assert_audit(audit, upper_division_pla_posted=0, upper_division_remaining=6)


def test_a_deleted_artifact_leaves_its_outcome_in_the_denominator(client):
    """Coverage falls from 9000 to 8000 rather than the outcome dropping out.

    PRD: "Deleting one decrements `artifact_count` by one and recomputes
    `provisional_coverage_bp` as well; a deleted artifact is gone rather than flagged,
    and it contributes nothing to any subsequent computation." "outcomes with no
    evidence at all enter the sum contributing zero rather than being dropped from
    the denominator — the denominator is fixed at 10000 precisely because the
    course's weights total 10000."

    Design: Corner/calculations/coverage_input_set_excludes_a_deleted_artifact
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
    outcomes = fx.outcomes_of(client, course["id"])
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    portfolio = fx.new_portfolio(client, claim["id"], student["id"])
    kept = fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    doomed = fx.attach_artifact(
        client,
        portfolio["id"],
        student["id"],
        [f.mapping(outcomes[1]["id"], Alignment.SUPPORTING)],
    )
    two_artifacts = get_success_data(
        client.get_portfolio(portfolio["id"], headers=COORDINATOR)
    )
    assert_fields_equal(two_artifacts, artifact_count=2, provisional_coverage_bp=9000)

    removal = client.delete_artifact(
        portfolio["id"], doomed["id"], headers=make_student_headers(student["id"])
    )
    assert removal.status_code == 204, (
        "the one deletion returns 204, got %s" % removal.status_code
    )

    one_artifact = get_success_data(
        client.get_portfolio(portfolio["id"], headers=COORDINATOR)
    )
    assert_fields_equal(one_artifact, artifact_count=1)
    rows, _meta = validate_paginated(
        client.list_artifacts({"portfolio_id": portfolio["id"]}, headers=COORDINATOR)
    )
    assert [row["id"] for row in rows] == [kept["id"]]

    # 8000 * 10000 for the PRIMARY mapping plus 2000 * 0 for the evidence-free OC2.
    submitted = fx.submit_portfolio(client, portfolio["id"], student["id"])
    assert_fields_equal(
        submitted, status=PortfolioStatus.SUBMITTED, provisional_coverage_bp=8000
    )
    assert submitted["provisional_coverage_bp"] != 9000

    unchanged = get_success_data(client.get_claim(claim["id"], headers=COORDINATOR))
    assert_claim_dimensions(unchanged, assessment_status=AssessmentStatus.DRAFT)


def test_an_exam_claim_draws_the_lower_base_fee_and_the_lower_discount_tier(client):
    """5000 rather than 15000 keeps the subtotal below the 25000-cent boundary.

    PRD: "The base assessment fee is 5000 cents for a `CREDIT_BY_EXAM` claim, 15000
    cents for `PORTFOLIO`, nothing at all for `MILITARY_TRAINING`, and 7500 cents for
    `INDUSTRY_CREDENTIAL`. The per-credit fee is 2500 cents multiplied by
    `credits_requested`." "A subtotal of at least 25000 cents earns `discount_bp` of
    1000; a subtotal of at least 10000 but below 25000 earns 500; anything below 10000
    earns 0." "it is the pinned crosswalk rule's `awarded_credits` multiplied by
    10000, divided by the course's `credits`, rounded half up, and then capped at
    10000"

    Design: Corner/calculations/fee_constants_by_source_type_place_credit_by_exam_in_the_lower_discount_tier
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
    recommendation = fx.published_recommendation(
        client,
        credential_code="CLEPCS",
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
    # Creation, publication and the rule's approval each move the generic counter,
    # while only an amendment would move terms_version.
    assert_fields_equal(
        get_success_data(client.get_recommendation(recommendation["id"], headers=COORDINATOR)),
        status=RecommendationStatus.PUBLISHED,
        version=3,
        terms_version=1,
    )
    assert_fields_equal(
        rule, status=RuleStatus.APPROVED, pinned_recommendation_version=1
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
    submitted = fx.submit_claim(client, claim["id"], student["id"])
    assert_claim_dimensions(submitted, assessment_status=AssessmentStatus.SUBMITTED)
    assert_fields_equal(submitted, provisional_coverage_bp=10000)

    # 5000 base plus 2500 per credit over 6 credits, with no portfolio and no rush.
    invoice = fx.invoice_for_claim(client, claim["id"])
    assert_invoice_money(
        invoice,
        subtotal_cents=20000,
        discount_bp=500,
        discount_cents=1000,
        total_cents=19000,
        balance_due_cents=19000,
    )
    assert_line_absent(invoice, InvoiceLineKind.ARTIFACT_TIER_SURCHARGE)
    assert_line_absent(invoice, InvoiceLineKind.RUSH_SURCHARGE)

    settled = get_success_data(client.get_claim(claim["id"], headers=COORDINATOR))
    assert_claim_dimensions(settled, fee_status=FeeStatus.INVOICED)
    assert_ledger(
        get_success_data(client.get_student(student["id"], headers=COORDINATOR)), reserved=6
    )
