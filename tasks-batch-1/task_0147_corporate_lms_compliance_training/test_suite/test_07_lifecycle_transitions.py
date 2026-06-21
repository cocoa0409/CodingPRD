"""Valid and invalid lifecycle transitions: republish, archive-with-open-enrollments,
reopen-non-failed, waived terminal lockdown, enrollment initial state, session
self-loop. Queue B (corner) — state_machines section.
"""
from test_helpers import (
    get_success_data,
    validate_error,
    TEST_USERS,
    ApiErrorId,
    set_clock,
    create_employee,
    create_published_course,
    create_enrollment,
    setup_enrollment,
    setup_started_enrollment,
    open_session,
    get_enrollment,
    make_learner_headers,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Corner/state_machines/publish_already_published_course_returns_invalid_state
# ===========================================================================
def test_publish_already_published_course_returns_invalid_state(api):
    """PRD §3.1: "The course must currently be DRAFT, or the transition is refused as
    ERR_INVALID_STATE."

    Design: Corner/state_machines/publish_already_published_course_returns_invalid_state
    """
    set_clock()
    course = create_published_course(passing_score=70)
    resp = api.publish_course(course["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner/state_machines/archive_course_with_open_enrollments_returns_invalid_state
# ===========================================================================
def test_archive_course_with_open_enrollment_returns_open_enrollments_error(api):
    """PRD §3.1: "there must be no enrollment for it still in NOT_STARTED or IN_PROGRESS
    (else ERR_COURSE_HAS_OPEN_ENROLLMENTS)."

    Design: Corner/state_machines/archive_course_with_open_enrollments_returns_invalid_state
    """
    emp, course, enr = setup_enrollment()  # course PUBLISHED, one NOT_STARTED enrollment
    resp = api.archive_course(course["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_COURSE_HAS_OPEN_ENROLLMENTS.value)


# ===========================================================================
# Corner/state_machines/reopen_non_failed_enrollment_returns_invalid_state
# ===========================================================================
def test_reopen_not_started_enrollment_returns_invalid_state(api):
    """PRD §3.5: "The enrollment must be FAILED (else ERR_INVALID_STATE)."

    Design: Corner/state_machines/reopen_non_failed_enrollment_returns_invalid_state
    """
    emp, course, enr = setup_enrollment()  # NOT_STARTED
    resp = api.reopen_enrollment(enr["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner/state_machines/waived_enrollment_is_terminal_second_start_returns_invalid_state
# ===========================================================================
def test_start_waived_enrollment_returns_invalid_state(api):
    """PRD §3.5: "A ComplianceAdmin may waive an enrollment that is NOT_STARTED,
    IN_PROGRESS, FAILED, or EXPIRED, moving it to the terminal WAIVED state."
    PRD §3.4: "The enrollment must be NOT_STARTED (else ERR_INVALID_STATE)."

    Design: Corner/state_machines/waived_enrollment_is_terminal_second_start_returns_invalid_state
    """
    emp, course, enr = setup_enrollment()
    waived = get_success_data(api.waive_enrollment(enr["id"], ADMIN))
    assert waived["status"] == "WAIVED"
    resp = api.start_enrollment(enr["id"], make_learner_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner/state_machines/newly_created_enrollment_initial_state_not_started
# ===========================================================================
def test_new_enrollment_initial_state_and_counters(api):
    """PRD §3.4: "The new enrollment starts NOT_STARTED with cycle_index 1 and the
    system-set fields seeded — best_score and latest_score null, final_grade null,
    attempts_used 0."

    Design: Corner/state_machines/newly_created_enrollment_initial_state_not_started
    """
    set_clock()
    emp = create_employee()
    course = create_published_course(passing_score=70)
    enr = get_success_data(
        api.create_enrollment(f.create_enrollment_payload(emp["id"], course["id"]), ADMIN)
    )
    assert enr["status"] == "NOT_STARTED"
    assert enr["cycle_index"] == 1, f"cycle_index seeded to 1, got {enr['cycle_index']}"
    assert enr["attempts_used"] == 0, f"attempts_used seeded to 0, got {enr['attempts_used']}"


# ===========================================================================
# Corner/state_machines/tracking_session_commit_self_loop_accumulates
# ===========================================================================
def test_session_commit_self_loop_keeps_running_and_updates_progress(api):
    """PRD §3.6: "Committing runtime data moves a session from INITIALIZED to RUNNING on
    the first commit and then self-loops on RUNNING for subsequent commits, each
    accumulating data. A commit ... updates progress_pct."

    Design: Corner/state_machines/tracking_session_commit_self_loop_accumulates
    """
    emp, course, started = setup_started_enrollment(course_overrides={"passing_score": 70})
    learner = make_learner_headers(emp["id"])
    sess = open_session(started["id"], emp["id"])
    get_success_data(api.commit_tracking_session(sess["id"], f.commit_session_payload("INCOMPLETE", 30), learner))
    after = get_success_data(api.commit_tracking_session(sess["id"], f.commit_session_payload("INCOMPLETE", 75), learner))
    assert after["status"] == "RUNNING", f"second commit keeps RUNNING, got {after['status']}"
    assert after["progress_pct"] == 75, f"progress updated to latest 75, got {after['progress_pct']}"
