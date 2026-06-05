"""Escalation-tier day boundary, interval-occupation rules (half-open session vs
closed-interval assignment-rule window), and conserved-quantity invariants
(CEU and compliant count under issue/revoke/recurrence-reset). Queue A (difficulty).
"""
import pytest

from test_helpers import (
    get_success_data,
    validate_error,
    TEST_USERS,
    ApiErrorId,
    set_clock,
    create_employee,
    create_published_course,
    create_enrollment,
    setup_started_enrollment,
    complete_enrollment,
    submit_attempt,
    get_enrollment,
    get_certificate_for_enrollment,
    open_session,
    create_assignment_rule,
    make_learner_headers,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Difficulty/boundary_precision_check/
#   escalation_tier_boundary_seven_vs_eight_days_on_escalations_run
# ===========================================================================
def _setup_overdue_enrollment(api, due_in_days, clock_after):
    set_clock("2026-01-01T00:00:00.000Z")
    emp = create_employee(department="OPERATIONS", job_role="IC")
    course = create_published_course(passing_score=70)
    enr = create_enrollment(emp["id"], course["id"], is_required=True, due_in_days=due_in_days)
    set_clock(clock_after)
    get_success_data(api.run_escalations(ADMIN))
    return emp, course, enr


def test_seven_days_overdue_lands_tier_one(api):
    """PRD §3.9: "from 1 through 7 days the tier is 1; from 8 through 30 days the tier
    is 2".

    Design: Difficulty/boundary_precision_check/escalation_tier_boundary_seven_vs_eight_days_on_escalations_run
    """
    emp, course, enr = _setup_overdue_enrollment(
        api, due_in_days=7, clock_after="2026-01-15T00:00:00.000Z"  # due 01-08, now 01-15 → 7 days
    )
    refreshed = get_enrollment(enr["id"])
    assert refreshed["escalation_tier"] == 1, (
        f"exactly 7 days overdue → tier 1, got {refreshed['escalation_tier']}"
    )


def test_overdue_not_started_enrollment_is_expired_by_sweep(api):
    """PRD §3.9: "an enrollment still NOT_STARTED or IN_PROGRESS whose due_date is
    strictly before current_utc is moved to EXPIRED, incrementing its version."

    Design: Difficulty/boundary_precision_check/escalation_tier_boundary_seven_vs_eight_days_on_escalations_run
    """
    emp, course, enr = _setup_overdue_enrollment(
        api, due_in_days=7, clock_after="2026-01-15T00:00:00.000Z"
    )
    refreshed = get_enrollment(enr["id"])
    assert refreshed["status"] == "EXPIRED", (
        f"overdue NOT_STARTED enrollment → EXPIRED, got {refreshed['status']}"
    )


# ===========================================================================
# Difficulty/resource_temporal_overlap/
#   tracking_session_half_open_interval_single_open_per_enrollment
# ===========================================================================
def test_second_open_session_while_one_active_is_rejected(api):
    """PRD §3.6: "at most one session per enrollment may be non-TERMINATED at a time —
    opening a second while one is still INITIALIZED or RUNNING is refused with
    ERR_SESSION_ALREADY_OPEN."

    Design: Difficulty/resource_temporal_overlap/tracking_session_half_open_interval_single_open_per_enrollment
    """
    emp, course, started = setup_started_enrollment(
        course_overrides={"passing_score": 70}, employee_overrides={"department": "FINANCE"},
    )
    open_session(started["id"], emp["id"])  # one INITIALIZED session occupies the enrollment
    resp = api.open_tracking_session(started["id"], make_learner_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_ALREADY_OPEN.value)


def test_initialized_session_blocks_a_second_open(api):
    """PRD §3.6: "Opening a session against an IN_PROGRESS enrollment creates it in
    INITIALIZED status ... at most one session per enrollment may be non-TERMINATED at
    a time."

    Design: Difficulty/resource_temporal_overlap/tracking_session_half_open_interval_single_open_per_enrollment
    """
    emp, course, started = setup_started_enrollment(
        course_overrides={"passing_score": 70}, employee_overrides={"department": "FINANCE"},
    )
    sess = open_session(started["id"], emp["id"])
    assert sess["status"] == "INITIALIZED"
    resp = api.open_tracking_session(started["id"], make_learner_headers(emp["id"]))
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}"


# ===========================================================================
# Difficulty/resource_temporal_overlap/assignment_rule_closed_interval_window_overlap
# ===========================================================================
def test_assignment_rule_touching_window_endpoint_is_overlap(api):
    """PRD §3.3: "if a new rule's closed [effective_from, effective_to] interval
    intersects an existing ACTIVE rule's window for that same target, the creation is
    refused with ERR_ASSIGNMENT_RULE_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/assignment_rule_closed_interval_window_overlap
    """
    set_clock()
    course = create_published_course(passing_score=70)
    create_assignment_rule(
        target_department="ENGINEERING", target_job_role="IC", course_id=course["id"],
        due_in_days=30, effective_from="2026-01-01T00:00:00.000Z",
        effective_to="2026-06-30T00:00:00.000Z",
    )
    resp = api.create_assignment_rule(
        f.create_assignment_rule_payload(
            target_department="ENGINEERING", target_job_role="IC", course_id=course["id"],
            due_in_days=30, effective_from="2026-06-30T00:00:00.000Z",
            effective_to="2026-12-31T00:00:00.000Z",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_RULE_OVERLAP.value)


def test_assignment_rule_overlap_returns_409(api):
    """PRD §3.3: "two ACTIVE rules aimed at the same target — the same combination of
    target_department, target_job_role, and the chosen course_id or learning_path_id —
    may not have overlapping windows."

    Design: Difficulty/resource_temporal_overlap/assignment_rule_closed_interval_window_overlap
    """
    set_clock()
    course = create_published_course(passing_score=70)
    create_assignment_rule(
        target_department="ENGINEERING", target_job_role="IC", course_id=course["id"],
        due_in_days=30, effective_from="2026-01-01T00:00:00.000Z",
        effective_to="2026-06-30T00:00:00.000Z",
    )
    resp = api.create_assignment_rule(
        f.create_assignment_rule_payload(
            target_department="ENGINEERING", target_job_role="IC", course_id=course["id"],
            due_in_days=30, effective_from="2026-06-30T00:00:00.000Z",
            effective_to="2026-12-31T00:00:00.000Z",
        ),
        ADMIN,
    )
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}"


# ===========================================================================
# Difficulty/compensating_invariant/ceu_conservation_issue_then_revoke
# ===========================================================================
def test_ceu_total_returns_to_zero_after_issue_then_revoke(api):
    """PRD §2.10: "Issuing a certificate adds its ceu_credited to total_ceu_earned ...
    revoking or expiring a certificate subtracts the same ceu_credited."

    Design: Difficulty/compensating_invariant/ceu_conservation_issue_then_revoke
    """
    emp, course, enr, cert = complete_enrollment(
        pass_score=75,
        course_overrides={"passing_score": 70, "ceu_credits": 9.00, "ceu_policy": "STANDARD"},
        enrollment_overrides={"is_required": True},
    )
    before = get_success_data(api.get_employee(emp["id"], ADMIN))
    assert before["total_ceu_earned"] == pytest.approx(9.00, abs=0.001)
    get_success_data(api.revoke_certificate(cert["id"], ADMIN))
    after = get_success_data(api.get_employee(emp["id"], ADMIN))
    assert after["total_ceu_earned"] == pytest.approx(0, abs=0.001), (
        f"+9.00 issue then -9.00 revoke → 0 with no drift, got {after['total_ceu_earned']}"
    )


def test_revoked_certificate_is_terminal_revoked(api):
    """PRD §3.8: "A ComplianceAdmin may revoke an ACTIVE certificate, moving it to the
    terminal REVOKED state."

    Design: Difficulty/compensating_invariant/ceu_conservation_issue_then_revoke
    """
    emp, course, enr, cert = complete_enrollment(
        pass_score=75,
        course_overrides={"passing_score": 70, "ceu_credits": 9.00, "ceu_policy": "STANDARD"},
        enrollment_overrides={"is_required": True},
    )
    revoked = get_success_data(api.revoke_certificate(cert["id"], ADMIN))
    assert revoked["status"] == "REVOKED"


# ===========================================================================
# Difficulty/compensating_invariant/
#   compliant_count_conservation_complete_then_recurrence_reset
# ===========================================================================
def _setup_required_recurring_completed(api):
    set_clock("2026-01-01T00:00:00.000Z")
    emp = create_employee(department="OPERATIONS", job_role="IC")
    course = create_published_course(
        passing_score=70, ceu_credits=3.00, is_recurring=True, recurrence_months=12,
    )
    learner = make_learner_headers(emp["id"])
    enr = create_enrollment(emp["id"], course["id"], is_required=True)
    started = get_success_data(api.start_enrollment(enr["id"], learner))
    submit_attempt(enr["id"], emp["id"], 95, started["version"])
    return emp, course, enr


def test_compliant_count_is_one_on_required_completion(api):
    """PRD §3.5: "when the enrollment is_required, the employee's
    compliant_required_count rises by one."

    Design: Difficulty/compensating_invariant/compliant_count_conservation_complete_then_recurrence_reset
    """
    emp, course, enr = _setup_required_recurring_completed(api)
    holder = get_success_data(api.get_employee(emp["id"], ADMIN))
    assert holder["compliant_required_count"] == 1, (
        f"required completion → count 1, got {holder['compliant_required_count']}"
    )


def test_recurrence_reset_returns_compliant_count_to_zero(api):
    """PRD §3.8: "the sweep moves that ACTIVE certificate to EXPIRED and applies the
    same compensation as a revoke ... and, when the linked enrollment is required,
    decrementing compliant_required_count."

    Design: Difficulty/compensating_invariant/compliant_count_conservation_complete_then_recurrence_reset
    """
    emp, course, enr = _setup_required_recurring_completed(api)
    set_clock("2027-02-01T00:00:00.000Z")
    get_success_data(api.run_escalations(ADMIN))
    refreshed = get_enrollment(enr["id"])
    holder = get_success_data(api.get_employee(emp["id"], ADMIN))
    assert refreshed["status"] == "NOT_STARTED"
    assert holder["compliant_required_count"] == 0, (
        f"recurrence reset compensates → count 0, got {holder['compliant_required_count']}"
    )
