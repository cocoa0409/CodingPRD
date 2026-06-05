"""Cyclic and branching state machines (enrollment retry loop, certificate fork) and
transitive cascades (session terminate → enrollment → cert → path; clock → cert →
recurrence reset). Queue A (difficulty).
"""
import pytest

from test_helpers import (
    get_success_data,
    TEST_USERS,
    set_clock,
    create_employee,
    create_published_course,
    create_enrollment,
    setup_started_enrollment,
    complete_enrollment,
    fail_single_attempt_enrollment,
    submit_attempt,
    get_enrollment,
    get_certificate_for_enrollment,
    setup_published_path,
    create_path_enrollment,
    child_enrollment_for,
    open_session,
    get_path_enrollment,
    make_learner_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Difficulty/non_linear_state_machine/enrollment_failed_to_in_progress_retry_cycle
# ===========================================================================
def test_reopen_failed_enrollment_returns_to_in_progress(api):
    """PRD §3.5: "A ComplianceAdmin can reopen a FAILED enrollment for a fresh try,
    moving it back to IN_PROGRESS."

    Design: Difficulty/non_linear_state_machine/enrollment_failed_to_in_progress_retry_cycle
    """
    emp, course, started = fail_single_attempt_enrollment(fail_score=40)
    failed = get_enrollment(started["id"])
    assert failed["status"] == "FAILED"
    reopened = get_success_data(api.reopen_enrollment(started["id"], ADMIN))
    assert reopened["status"] == "IN_PROGRESS", (
        f"reopen FAILED → IN_PROGRESS, got {reopened['status']}"
    )


def test_reopen_resets_attempts_and_grade_for_the_cycle(api):
    """PRD §3.5: "Reopening stays within the same cycle_index but resets the cycle for
    a clean retry: attempts_used returns to 0 and best_score, latest_score, and
    final_grade are cleared to null."

    Design: Difficulty/non_linear_state_machine/enrollment_failed_to_in_progress_retry_cycle
    """
    emp, course, started = fail_single_attempt_enrollment(fail_score=40)
    get_success_data(api.reopen_enrollment(started["id"], ADMIN))
    enr = get_enrollment(started["id"])
    assert enr["attempts_used"] == 0, f"attempts_used reset to 0, got {enr['attempts_used']}"
    assert enr["final_grade"] is None, f"final_grade cleared to null, got {enr['final_grade']}"


# ===========================================================================
# Difficulty/non_linear_state_machine/certificate_branching_active_to_revoked_vs_expired
# ===========================================================================
def test_revoke_active_certificate_moves_to_revoked(api):
    """PRD §3.8: "A ComplianceAdmin may revoke an ACTIVE certificate, moving it to the
    terminal REVOKED state."

    Design: Difficulty/non_linear_state_machine/certificate_branching_active_to_revoked_vs_expired
    """
    emp, course, enr, cert = complete_enrollment(
        pass_score=88,
        course_overrides={"passing_score": 70, "ceu_credits": 10.00, "ceu_policy": "STANDARD"},
        enrollment_overrides={"is_required": True},
    )
    revoked = get_success_data(api.revoke_certificate(cert["id"], ADMIN))
    assert revoked["status"] == "REVOKED", f"revoke ACTIVE → REVOKED, got {revoked['status']}"


def test_revoke_certificate_compensates_employee_ceu_and_count(api):
    """PRD §3.8: "the certificate's ceu_credited is subtracted from the holder's
    total_ceu_earned, and when the linked enrollment is_required the holder's
    compliant_required_count falls by one."

    Design: Difficulty/non_linear_state_machine/certificate_branching_active_to_revoked_vs_expired
    """
    emp, course, enr, cert = complete_enrollment(
        pass_score=88,
        course_overrides={"passing_score": 70, "ceu_credits": 10.00, "ceu_policy": "STANDARD"},
        enrollment_overrides={"is_required": True},
    )
    get_success_data(api.revoke_certificate(cert["id"], ADMIN))
    holder = get_success_data(api.get_employee(emp["id"], ADMIN))
    assert holder["total_ceu_earned"] == pytest.approx(0, abs=0.001), (
        f"revoke subtracts the 10.00 → 0, got {holder['total_ceu_earned']}"
    )
    assert holder["compliant_required_count"] == 0, (
        f"required cert revoked → count 0, got {holder['compliant_required_count']}"
    )


# ===========================================================================
# Difficulty/transitive_cascade/session_terminate_cascade_depth3_session_enrollment_cert_path
# ===========================================================================
def _setup_single_step_path_running_session(api, reported_score=90):
    set_clock()
    emp = create_employee(department="HR", job_role="IC")
    path, courses = setup_published_path(
        num_steps=1, enforce_sequence=True, set_clock_first=False,
    )
    pe = create_path_enrollment(emp["id"], path["id"])
    child = child_enrollment_for(pe["id"], courses[0]["id"])
    learner = make_learner_headers(emp["id"])
    started = get_success_data(api.start_enrollment(child["id"], learner))
    sess = open_session(child["id"], emp["id"])
    get_success_data(
        api.commit_tracking_session(
            sess["id"], {"lesson_status": "PASSED", "progress_pct": 100,
                         "reported_score": reported_score}, learner
        )
    )
    # Advance the clock so a subsequent terminate stamps terminated_at strictly
    # after the session's started_at (PRD §3.6), staying well within the due date.
    set_clock("2026-01-02T00:00:00.000Z")
    return emp, pe, child, started, sess


def test_session_terminate_completes_enrollment_and_records_grade(api):
    """PRD §3.6: "If the session carries a reported_score, that score is promoted into
    a QuizAttempt on the enrollment and the full enrollment grading cascade of §3.5
    runs against it — driving the enrollment to COMPLETED on a passing score."

    Design: Difficulty/transitive_cascade/session_terminate_cascade_depth3_session_enrollment_cert_path
    """
    emp, pe, child, started, sess = _setup_single_step_path_running_session(api, reported_score=90)
    learner = make_learner_headers(emp["id"])
    term = get_success_data(
        api.terminate_tracking_session(
            sess["id"], learner, {"expected_enrollment_version": started["version"]}
        )
    )
    assert term["status"] == "TERMINATED"
    enr = get_enrollment(child["id"])
    assert enr["status"] == "COMPLETED", f"passing reported_score → COMPLETED, got {enr['status']}"
    assert enr["final_grade"] == 90, f"final_grade promoted from reported_score, got {enr['final_grade']}"


def test_session_terminate_bubbles_sole_step_path_to_completed(api):
    """PRD §3.7: "When a child enrollment reaches COMPLETED and, with it, every
    mandatory step's child enrollment is now COMPLETED or WAIVED, the path enrollment
    recomputes its progress to 100 and bubbles to the terminal COMPLETED."

    Design: Difficulty/transitive_cascade/session_terminate_cascade_depth3_session_enrollment_cert_path
    """
    emp, pe, child, started, sess = _setup_single_step_path_running_session(api, reported_score=90)
    learner = make_learner_headers(emp["id"])
    get_success_data(
        api.terminate_tracking_session(
            sess["id"], learner, {"expected_enrollment_version": started["version"]}
        )
    )
    refreshed = get_path_enrollment(pe["id"])
    assert refreshed["status"] == "COMPLETED", (
        f"sole mandatory step COMPLETED → path COMPLETED, got {refreshed['status']}"
    )
    assert refreshed["progress_pct"] == pytest.approx(100.00, abs=0.001)


# ===========================================================================
# Difficulty/transitive_cascade/clock_recurrence_cascade_depth2_clock_cert_enrollment
# ===========================================================================
def _setup_recurring_completed_then_advance(api, recurrence_months=12):
    set_clock("2026-01-01T00:00:00.000Z")
    emp = create_employee(department="FINANCE", job_role="IC")
    course = create_published_course(
        passing_score=70, ceu_credits=6.00, is_recurring=True, recurrence_months=recurrence_months,
    )
    learner = make_learner_headers(emp["id"])
    enr = create_enrollment(emp["id"], course["id"], is_required=True)
    started = get_success_data(api.start_enrollment(enr["id"], learner))
    submit_attempt(enr["id"], emp["id"], 80, started["version"])
    cert = get_certificate_for_enrollment(enr["id"])
    set_clock("2027-02-01T00:00:00.000Z")  # past expires_at 2027-01-01
    return emp, course, enr, cert


def test_certificate_expiry_recurrence_resets_enrollment_to_not_started(api):
    """PRD §3.8: "that COMPLETED enrollment, whose course is_recurring and whose
    certificate was ACTIVE and is now past its expires_at, returns to NOT_STARTED to
    start a new compliance cycle. The reset advances cycle_index by one."

    Design: Difficulty/transitive_cascade/clock_recurrence_cascade_depth2_clock_cert_enrollment
    """
    emp, course, enr, cert = _setup_recurring_completed_then_advance(api)
    get_success_data(api.run_escalations(ADMIN))
    refreshed_cert = get_success_data(api.get_certificate(cert["id"], ADMIN))
    refreshed_enr = get_enrollment(enr["id"])
    assert refreshed_cert["status"] == "EXPIRED", f"cert past expiry → EXPIRED, got {refreshed_cert['status']}"
    assert refreshed_enr["status"] == "NOT_STARTED", (
        f"recurrence reset → NOT_STARTED, got {refreshed_enr['status']}"
    )
    assert refreshed_enr["cycle_index"] == 2, (
        f"reset advances cycle_index by one, got {refreshed_enr['cycle_index']}"
    )


def test_certificate_expiry_compensates_employee_ceu_on_reset(api):
    """PRD §3.8: "the sweep moves that ACTIVE certificate to EXPIRED and applies the
    same compensation as a revoke — subtracting ceu_credited from the holder's
    total_ceu_earned and, when the linked enrollment is required, decrementing
    compliant_required_count."

    Design: Difficulty/transitive_cascade/clock_recurrence_cascade_depth2_clock_cert_enrollment
    """
    emp, course, enr, cert = _setup_recurring_completed_then_advance(api)
    get_success_data(api.run_escalations(ADMIN))
    holder = get_success_data(api.get_employee(emp["id"], ADMIN))
    assert holder["total_ceu_earned"] == pytest.approx(0, abs=0.001), (
        f"expiry compensates the 6.00 → 0, got {holder['total_ceu_earned']}"
    )
    assert holder["compliant_required_count"] == 0, (
        f"required cert expired → count 0, got {holder['compliant_required_count']}"
    )
