"""Two interval geometries that must not be confused for one another.

The assessor buffered window is closed on both ends and padded by 24 hours, so a
touch collides. The crosswalk validity window is half-open, so a touch does not.
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
from test_helpers.assertions import assert_fields_equal, assert_instant, assert_sla
from test_helpers.test_users import COORDINATOR, OFFICER_APPROVER, OFFICER_REVIEWER
from test_helpers.types import (
    Alignment,
    AssignmentStatus,
    CourseLevel,
    RuleStatus,
    SourceType,
    SuspendReason,
)


def _one_outcome_course(client, course_code, credits, level=CourseLevel.LOWER):
    return fx.new_course(
        client,
        course_code=course_code,
        department_code="CS",
        credits=credits,
        level=level,
        learning_outcomes=[f.outcome_payload("OC1", 10000, mastery_threshold_bp=7000)],
    )


def _waived_submitted_portfolio_claim(client, student_id, course, credits_requested):
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
            invoice["id"], {"waive_reason": "Pilot cohort"}, headers=COORDINATOR
        )
    )
    return claim


@pytest.fixture
def one_held_window_and_a_clock_on_its_padded_endpoint(client):
    """One ASSIGNED window held by a single-slot assessor, clock on the pad edge.

    The first assignment is never accepted and the sweep is never run, so it keeps
    holding its window past `due_at`. The clock is then moved to exactly
    ``due_at`` plus the 24-hour pad.
    """
    program = fx.new_program(
        client,
        program_code="BSCSBUF",
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
        allowed_source_types=[SourceType.PORTFOLIO],
    )
    course_one = _one_outcome_course(client, "CS150", 6)
    course_two = _one_outcome_course(client, "CS210", 6)
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=0, institutional_credits_earned=60
    )
    assessor = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=1,
    )
    claim_one = _waived_submitted_portfolio_claim(client, student["id"], course_one, 6)
    assignment_one = fx.assign_assessor(client, claim_one["id"], assessor["id"])
    claim_two = _waived_submitted_portfolio_claim(client, student["id"], course_two, 6)
    fx.set_clock(client, "2026-08-12T00:00:00Z")
    return {
        "assessor": assessor,
        "claim_one": claim_one,
        "claim_two": claim_two,
        "assignment_one": assignment_one,
    }


def test_a_window_touching_the_padded_endpoint_exhausts_the_single_slot(
    client, one_held_window_and_a_clock_on_its_padded_endpoint
):
    """A new window opening exactly on the pad's closed edge collides.

    PRD: "Each of the assessor's existing assignments in `ASSIGNED` or `ACCEPTED`
    projects a padded closed interval running from 24 hours before its `assigned_at`
    to 24 hours after its `due_at`." "Because both intervals are closed on both
    ends, **touching endpoints do collide**: a new window beginning exactly 24 hours
    after another assignment's `due_at` conflicts, while one beginning a single
    millisecond later does not."

    Design: Difficulty/resource_temporal_overlap/assessor_buffered_window_closed_endpoint_touch_conflicts_but_one_ms_later_does_not
    """
    scenario = one_held_window_and_a_clock_on_its_padded_endpoint
    held = scenario["assignment_one"]
    # A STANDARD portfolio claim with one artifact: base 240 hours, multiplier 10000.
    assert_sla(held, sla_hours=240, due_at="2026-08-11T00:00:00Z", at_risk_at="2026-08-09T00:00:00Z")
    assert_instant(held["assigned_at"], "2026-08-01T00:00:00Z", "assigned_at")
    still_holding = get_success_data(client.get_assignment(held["id"], headers=COORDINATOR))
    assert_fields_equal(still_holding, status=AssignmentStatus.ASSIGNED)

    response = client.create_assignment(
        scenario["claim_two"]["id"],
        {"assessor_id": scenario["assessor"]["id"]},
        headers=COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_ASSESSOR_CAPACITY_CONFLICT, 409)

    listing = client.list_assignments(
        {"claim_id": scenario["claim_two"]["id"]}, headers=COORDINATOR
    )
    rows, _meta = validate_paginated(listing)
    assert rows == [], "the refused assignment must not create a row"

    assessor = get_success_data(
        client.get_assessor(scenario["assessor"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(assessor, active_assignment_count=1)


def test_one_millisecond_past_the_padded_endpoint_clears_the_conflict(
    client, one_held_window_and_a_clock_on_its_padded_endpoint
):
    """Moving the clock a single millisecond later makes the same request legal.

    PRD: "Comparisons are made at millisecond resolution." "`due_at` is
    `assigned_at` advanced by `sla_hours` hours."

    Design: Difficulty/resource_temporal_overlap/assessor_buffered_window_closed_endpoint_touch_conflicts_but_one_ms_later_does_not
    """
    scenario = one_held_window_and_a_clock_on_its_padded_endpoint
    fx.set_clock(client, "2026-08-12T00:00:00.001Z")

    assignment = validate_success(
        client.create_assignment(
            scenario["claim_two"]["id"],
            {"assessor_id": scenario["assessor"]["id"]},
            headers=COORDINATOR,
        ),
        expected_status=201,
    )
    assert_fields_equal(assignment, status=AssignmentStatus.ASSIGNED)
    assert_sla(assignment, sla_hours=240, due_at="2026-08-22T00:00:00.001Z")
    assert_instant(assignment["assigned_at"], "2026-08-12T00:00:00.001Z", "assigned_at")

    assessor = get_success_data(
        client.get_assessor(scenario["assessor"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(assessor, active_assignment_count=2)


@pytest.fixture
def one_approved_window_and_two_candidates(client):
    """One APPROVED crosswalk window plus an adjacent and an overlapping candidate.

    R1 holds ``[2026-01-01T00:00:00Z, 2027-01-01T00:00:00Z)``. R2 starts exactly
    where R1 ends and runs open-ended. R3 starts one millisecond before R1 ends and
    ends where R2 begins. Both candidates sit in ``UNDER_REVIEW``, reviewed by the
    reviewing officer so that the approving officer is a different user.
    """
    course = _one_outcome_course(client, "CS150", 6)
    recommendation = fx.published_recommendation(
        client,
        credential_code="CLEP-CS",
        source_type=SourceType.CREDIT_BY_EXAM,
        recommended_credits=6,
        recommended_level=CourseLevel.LOWER,
        effective_from="2026-01-01T00:00:00Z",
    )
    rule_one = fx.approved_rule(
        client,
        recommendation["id"],
        course["id"],
        awarded_credits=6,
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
    )

    def candidate(awarded_credits, effective_from, effective_to):
        rule = get_success_data(
            client.create_rule(
                f.rule_payload(
                    recommendation["id"],
                    course["id"],
                    awarded_credits=awarded_credits,
                    effective_from=effective_from,
                    effective_to=effective_to,
                ),
                headers=OFFICER_REVIEWER,
            )
        )
        return get_success_data(
            client.submit_rule_for_review(rule["id"], headers=OFFICER_REVIEWER)
        )

    adjacent = candidate(6, "2027-01-01T00:00:00Z", None)
    overlapping = candidate(5, "2026-12-31T23:59:59.999Z", "2027-01-01T00:00:00Z")
    return {
        "recommendation": recommendation,
        "course": course,
        "approved": rule_one,
        "adjacent": adjacent,
        "overlapping": overlapping,
    }


def _approve(client, rule_id, recommendation_id):
    recommendation = get_success_data(
        client.get_recommendation(recommendation_id, headers=OFFICER_APPROVER)
    )
    return client.approve_rule(
        rule_id,
        {"expected_recommendation_version": recommendation["version"]},
        headers=OFFICER_APPROVER,
    )


def test_a_window_starting_where_another_ends_is_approvable(
    client, one_approved_window_and_two_candidates
):
    """Half-open windows that touch at a single instant do not overlap.

    PRD: "Adjacency is therefore legal: a rule ending exactly at
    `2027-01-01T00:00:00Z` and a rule starting exactly at `2027-01-01T00:00:00Z` do
    not overlap and may both be `APPROVED`."

    Design: Difficulty/resource_temporal_overlap/articulation_half_open_adjacency_is_legal_while_one_ms_overlap_is_rejected
    """
    scenario = one_approved_window_and_two_candidates
    assert_fields_equal(scenario["approved"], status=RuleStatus.APPROVED)
    assert_fields_equal(scenario["adjacent"], status=RuleStatus.UNDER_REVIEW)
    assert scenario["adjacent"]["pinned_recommendation_version"] is None

    approved = validate_success(
        _approve(client, scenario["adjacent"]["id"], scenario["recommendation"]["id"])
    )
    assert_fields_equal(approved, status=RuleStatus.APPROVED)
    # Approval pins the recommendation's terms_version, which publication left at 1.
    assert_fields_equal(approved, pinned_recommendation_version=1)

    recommendation = get_success_data(
        client.get_recommendation(scenario["recommendation"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(recommendation, approved_rule_count=2)


def test_one_millisecond_of_overlap_is_rejected_until_the_sibling_is_suspended(
    client, one_approved_window_and_two_candidates
):
    """A window reaching one millisecond into R1 conflicts; suspending R1 clears it.

    PRD: "Formally, two windows overlap when the first window's `effective_from` is
    strictly earlier than the second's `effective_to` and the second's
    `effective_from` is strictly earlier than the first's `effective_to`, treating a
    null end as unbounded." "Rules in `DRAFT`, `UNDER_REVIEW`, `SUSPENDED` or
    `RETIRED` never conflict with anything."

    Design: Difficulty/resource_temporal_overlap/articulation_half_open_adjacency_is_legal_while_one_ms_overlap_is_rejected
    """
    scenario = one_approved_window_and_two_candidates
    validate_success(_approve(client, scenario["adjacent"]["id"], scenario["recommendation"]["id"]))

    refused = _approve(
        client, scenario["overlapping"]["id"], scenario["recommendation"]["id"]
    )
    validate_error(refused, ApiErrorId.ERR_ARTICULATION_WINDOW_OVERLAP, 409)

    held = get_success_data(
        client.get_rule(scenario["overlapping"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(held, status=RuleStatus.UNDER_REVIEW)
    assert held["pinned_recommendation_version"] is None
    unchanged = get_success_data(
        client.get_recommendation(scenario["recommendation"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(unchanged, approved_rule_count=2)

    suspended = validate_success(
        client.suspend_rule(scenario["approved"]["id"], {}, headers=OFFICER_APPROVER)
    )
    assert_fields_equal(
        suspended, status=RuleStatus.SUSPENDED, suspend_reason=SuspendReason.MANUAL_REVIEW
    )

    now_free = validate_success(
        _approve(client, scenario["overlapping"]["id"], scenario["recommendation"]["id"])
    )
    assert_fields_equal(now_free, status=RuleStatus.APPROVED, awarded_credits=5)
