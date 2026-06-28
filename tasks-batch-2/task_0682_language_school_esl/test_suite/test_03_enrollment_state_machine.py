"""Enrollment & visa state machines: forks, cycles, transitions, terminal lockdown.

Difficulty queue: non_linear_state_machine (confirm fork, visa ACTIVE->PROBATION->ACTIVE cycle).
Corner queue: invalid transitions, initial state, terminal lockdown, precondition
              enforcement, cross-entity void, conditional cascade on add-on cancel.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_student_headers, set_clock,
    create_cohort, create_student, create_placed_student, create_enrollment, confirm,
    create_corporate_contract_payload, create_add_on_payload, confirm_enrollment_payload,
    score_placement_test_payload, create_placement_test_payload,
    setup_active_international, setup_capacity1_with_waitlist, issue_i20, activate_status,
    place_probation, mark_attendance, add_progress_report,
)

REG = TEST_USERS["registrar_headers"]
DSO = TEST_USERS["dso_headers"]
INSTR = TEST_USERS["instructor_headers"]


# =====================================================================
# Difficulty / non_linear_state_machine / enrollment_confirm_forks_enrolled_vs_waitlisted
# =====================================================================
def test_confirm_fork_enrolled_branch(api):
    """PRD §3.3: "When the cohort has a free seat — that is, its status is OPEN and
    seats_taken is below capacity — the enrollment advances PLACEMENT_PENDING → ENROLLED."

    Design: Difficulty/non_linear_state_machine/enrollment_confirm_forks_enrolled_vs_waitlisted
    """
    cohort, stu_a, enr_a, stu_b, enr_b = setup_capacity1_with_waitlist()
    assert enr_a["status"] == "ENROLLED"
    assert cohort["seats_taken"] == 1, f"seat consumed by ENROLLED branch, got {cohort['seats_taken']}"


def test_confirm_fork_waitlisted_branch(api):
    """PRD §3.3: "When the cohort is FULL, or equivalently when seats_taken is at or
    above capacity, the enrollment instead advances PLACEMENT_PENDING → WAITLISTED,
    consuming no seat and parking behind any enrollments already waitlisted on that
    cohort, ordered first-in-first-out by created_at ascending."

    Design: Difficulty/non_linear_state_machine/enrollment_confirm_forks_enrolled_vs_waitlisted
    """
    cohort, stu_a, enr_a, stu_b, enr_b = setup_capacity1_with_waitlist()
    assert enr_b["status"] == "WAITLISTED"
    # WAITLISTED branch computes no tuition.
    assert enr_b["tuition_invoice_cents"] == 0, "no tuition on the waitlist branch"
    assert cohort["seats_taken"] == 1, "waitlist consumes no extra seat"


# =====================================================================
# Difficulty / non_linear_state_machine / student_visa_status_active_probation_active_cycle
# =====================================================================
def test_visa_status_active_probation_active_cycle(api):
    """PRD §3.8: "A student is placed on probation, transitioning ACTIVE → PROBATION
    ... explicitly when a DSO places them on probation"
    PRD §3.8: "A DSO clears probation, transitioning PROBATION → ACTIVE, but only when
    the current status is PROBATION and the student is once again meeting a full course
    of study by the same enrolled-weekly-hours rule"

    Design: Difficulty/non_linear_state_machine/student_visa_status_active_probation_active_cycle
    """
    stu, cohort, enr = setup_active_international(weekly_hours=18)
    assert stu["visa_status"] == "ACTIVE"
    place_probation(stu["id"], reason="low engagement")
    # Clear probation -> ACTIVE again (the 18h enrollment still satisfies full course of study).
    data = validate_success(api.clear_probation(stu["id"], DSO, {"reason": "remediated"}))
    assert data["visa_status"] == "ACTIVE", f"cycle must return to ACTIVE, got {data['visa_status']}"


def test_place_probation_transitions_active_to_probation(api):
    """PRD §3.8: "the explicit placement requires the current status to be ACTIVE and
    appends a ComplianceEvent of type PROBATION_PLACED (prior ACTIVE, new PROBATION)."

    Design: Difficulty/non_linear_state_machine/student_visa_status_active_probation_active_cycle
    """
    stu, cohort, enr = setup_active_international(weekly_hours=18)
    data = validate_success(api.place_probation(stu["id"], DSO, {"reason": "concern"}))
    assert data["visa_status"] == "PROBATION", f"expected PROBATION, got {data['visa_status']}"


# =====================================================================
# Corner / state_machines / new_enrollment_starts_in_placement_pending
# =====================================================================
def test_new_enrollment_starts_in_placement_pending(api):
    """PRD §3.3: "A new enrollment begins in PLACEMENT_PENDING state with a null
    enrolled_at, zero sessions_attended and sessions_elapsed, an attendance_rate of
    1.0, a tuition_invoice_cents of 0, a refund_cents of 0, a null completion_score,
    and a null termination_reason."

    Design: Corner/state_machines/new_enrollment_starts_in_placement_pending
    """
    cohort = create_cohort(level="B1", track="GENERAL")
    stu = create_student(track="GENERAL")
    data = validate_success(api.create_enrollment(
        {"student_id": stu["id"], "cohort_id": cohort["id"]}, REG), 201)
    assert data["status"] == "PLACEMENT_PENDING"
    assert data["enrolled_at"] is None
    assert data["tuition_invoice_cents"] == 0


# =====================================================================
# Corner / state_machines / score_already_scored_test_returns_invalid_state
# =====================================================================
def test_score_already_scored_test_returns_invalid_state(api):
    """PRD §3.1: "Scoring requires that the test currently be in REGISTERED state;
    scoring a test in any other state is rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/score_already_scored_test_returns_invalid_state
    """
    stu = create_student()
    pt = get_success_data(api.create_placement_test({"student_id": stu["id"]}, REG))
    get_success_data(api.score_placement_test(pt["id"], {"raw_score": 50}, INSTR))
    validate_error(api.score_placement_test(pt["id"], {"raw_score": 80}, INSTR),
                   ApiErrorId.ERR_INVALID_STATE.value)


# =====================================================================
# Corner / state_machines / withdraw_from_completed_terminal_returns_invalid_state
# =====================================================================
def test_withdraw_from_completed_returns_invalid_state(api):
    """PRD §2.8: "fifth, that the target resource is in a state from which the
    requested transition is legal (ERR_INVALID_STATE, 409)."
    PRD §3.7: "Withdrawal requires only that the enrollment be in ENROLLED state."

    Design: Corner/state_machines/withdraw_from_completed_terminal_returns_invalid_state
    """
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=9, base_tuition_cents=100000,
                           schedule_block="MORNING", term_start="2026-04-01T00:00:00Z",
                           term_end="2026-04-10T00:00:00Z", total_sessions=10)
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    mark_attendance(enr["id"], 1, "PRESENT")
    add_progress_report(enr["id"], 80, 80, 80, 80)
    set_clock("2026-04-11T00:00:00Z")
    get_success_data(api.complete_enrollment(enr["id"], REG))
    validate_error(api.withdraw_enrollment(enr["id"], REG), ApiErrorId.ERR_INVALID_STATE.value)


# =====================================================================
# Corner / state_machines / issue_i20_for_non_international_returns_invalid_state
# =====================================================================
def test_issue_i20_for_non_international_returns_invalid_state(api):
    """PRD §3.8: "Issuance requires that the student is_international be true and that
    the current visa_status be NONE."

    Design: Corner/state_machines/issue_i20_for_non_international_returns_invalid_state
    """
    stu = create_student(is_international=False)
    validate_error(api.issue_i20(stu["id"], DSO, {}), ApiErrorId.ERR_INVALID_STATE.value)


# =====================================================================
# Corner / state_machines / terminate_status_cascades_void_certification
# =====================================================================
def test_terminate_status_voids_certification(api):
    """PRD §3.8: "Termination appends a ComplianceEvent of type I20_TERMINATED ...
    then cascades: every currently ENROLLED enrollment of the student is terminated
    with termination_reason VISA_NONCOMPLIANCE ... and the student's
    certification_status is set to VOIDED if it was previously PROVISIONAL or CERTIFIED."

    Design: Corner/state_machines/terminate_status_cascades_void_certification
    """
    # International student, I-20 issued, ENROLLED into a short 18h cohort, activated,
    # completed once (-> PROVISIONAL), then placed on probation, then terminated.
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=18, base_tuition_cents=100000,
                           schedule_block="MORNING", term_start="2026-04-01T00:00:00Z",
                           term_end="2026-04-10T00:00:00Z", total_sessions=10)
    stu = create_placed_student(level="B1", track="GENERAL", is_international=True)
    issue_i20(stu["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    activate_status(stu["id"])
    mark_attendance(enr["id"], 1, "PRESENT")
    add_progress_report(enr["id"], 80, 80, 80, 80)
    set_clock("2026-04-11T00:00:00Z")
    get_success_data(api.complete_enrollment(enr["id"], REG))
    # Now PROVISIONAL; place on probation then terminate.
    place_probation(stu["id"], reason="post-completion review")
    data = validate_success(api.terminate_status(stu["id"], DSO, {"reason": "visa violation"}))
    assert data["visa_status"] == "TERMINATED"
    assert data["certification_status"] == "VOIDED", (
        f"certification must be VOIDED on visa termination, got {data['certification_status']}")


# =====================================================================
# Corner / state_machines / cancel_addon_after_enrollment_terminal_returns_invalid_state
# =====================================================================
def test_cancel_addon_after_enrollment_withdrawn_returns_invalid_state(api):
    """PRD §3.9: "A Student cancels their own add-on, transitioning it ACTIVE →
    CANCELLED, which requires the add-on to currently be ACTIVE and its parent
    enrollment to be in one of PLACEMENT_PENDING, ENROLLED, or WAITLISTED state — an
    add-on cannot be cancelled once its enrollment has reached a terminal state."

    Design: Corner/state_machines/cancel_addon_after_enrollment_terminal_returns_invalid_state
    """
    cohort = create_cohort(level="B1", track="GENERAL", schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    headers = make_student_headers(stu["id"])
    add_on = get_success_data(api.create_add_on(
        create_add_on_payload(stu["id"], enr["id"], "CONVERSATION_CLUB", 4), headers))
    confirm(enr["id"], cohort["version"], require_seat=True)
    get_success_data(api.withdraw_enrollment(enr["id"], REG))  # enrollment now WITHDRAWN (terminal)
    validate_error(api.cancel_add_on(add_on["id"], headers), ApiErrorId.ERR_INVALID_STATE.value)
