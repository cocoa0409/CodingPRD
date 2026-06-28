"""Corner tests for state-machine transitions and side effects (section: state_machines)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, make_instructor_headers, TEST_USERS,
    create_published_course, create_instructor, create_cohort,
    setup_scheduled_cohort, setup_active_enrollment, enroll_student, score_attempt,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestCohortWindowGating:
    def test_conclude_before_window_rejected(self, api):
        """PRD §3.2: "Concluding a cohort advances IN_SESSION to CONCLUDED. It requires the
        cohort to be in IN_SESSION (otherwise ERR_INVALID_STATE) and the clock to have reached
        or passed the cohort's ends_at, or it fails with ERR_COHORT_WINDOW_NOT_OPEN."

        Design: Corner/state_machines/conclude_before_window_returns_window_not_open
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_published_course(exam_type="SAT", format="LIVE")
        inst = create_instructor(certified_exam_types=["SAT"], max_concurrent_cohorts=3)
        cohort = create_cohort(course["id"], seat_capacity=5,
                              starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-30T00:00:00Z")
        validate_success(api.schedule_cohort(cohort["id"], inst["id"], REGISTRAR))
        get_success_data(api.set_clock("2026-06-05T00:00:00Z", REGISTRAR))
        validate_success(api.start_cohort(cohort["id"], REGISTRAR))
        resp = api.conclude_cohort(cohort["id"], REGISTRAR)  # clock 06-05 < ends_at 06-30
        validate_error(resp, ApiErrorId.ERR_COHORT_WINDOW_NOT_OPEN)
        c = validate_success(api.get_cohort(cohort["id"], REGISTRAR))
        assert c["status"] == "IN_SESSION"


class TestInvalidTransitions:
    def test_start_draft_cohort_invalid_state(self, api):
        """PRD §3.2: "Starting a cohort advances SCHEDULED to IN_SESSION. It requires the
        cohort to be in SCHEDULED (otherwise ERR_INVALID_STATE)".

        Design: Corner/state_machines/start_cohort_from_draft_invalid_state
        """
        get_success_data(api.set_clock("2026-07-01T00:00:00Z", REGISTRAR))
        course = create_published_course(exam_type="SAT", format="LIVE")
        cohort = create_cohort(course["id"], seat_capacity=5,
                              starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-30T00:00:00Z")
        resp = api.start_cohort(cohort["id"], REGISTRAR)  # never scheduled
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        c = validate_success(api.get_cohort(cohort["id"], REGISTRAR))
        assert c["status"] == "DRAFT"

    def test_void_completed_attempt_invalid_state(self, api):
        """PRD §3.5: "An instructor may instead void a STARTED attempt, advancing it to
        VOIDED (it must be STARTED, else ERR_INVALID_STATE)."

        Design: Corner/state_machines/void_completed_attempt_invalid_state
        """
        base = setup_active_enrollment(fmt="SELF", student_email="void@x.com")
        scored = score_attempt(base["enrollment"]["id"], base["instructor"]["id"],
                               "PRACTICE", 400, 800, base["student"]["id"])
        assert scored["status"] == "COMPLETED"
        resp = api.void_practice_attempt(
            scored["id"], make_instructor_headers(base["instructor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_practice_attempt(
            scored["id"], make_instructor_headers(base["instructor"]["id"])))
        assert data["status"] == "COMPLETED"


class TestTerminalLockdown:
    def test_conclude_concluded_cohort_rejected(self, api):
        """PRD §3.1: "A cohort's lifecycle states are DRAFT, SCHEDULED, IN_SESSION, CONCLUDED,
        and CANCELLED, with the last two being terminal."
        PRD §3.2: "It requires the cohort to be in IN_SESSION (otherwise ERR_INVALID_STATE)".

        Design: Corner/state_machines/conclude_concluded_cohort_terminal_lockdown
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_published_course(exam_type="SAT", format="SELF")
        inst = create_instructor(certified_exam_types=["SAT"], max_concurrent_cohorts=3)
        cohort = create_cohort(course["id"], seat_capacity=5,
                              starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-30T00:00:00Z")
        validate_success(api.schedule_cohort(cohort["id"], inst["id"], REGISTRAR))
        get_success_data(api.set_clock("2026-06-30T00:00:00Z", REGISTRAR))
        validate_success(api.start_cohort(cohort["id"], REGISTRAR))
        validate_success(api.conclude_cohort(cohort["id"], REGISTRAR))
        resp = api.conclude_cohort(cohort["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        c = validate_success(api.get_cohort(cohort["id"], REGISTRAR))
        assert c["status"] == "CONCLUDED"


class TestSideEffects:
    def test_diagnostic_score_set_on_first_diagnostic(self, api):
        """PRD §3.5: "If the attempt is a DIAGNOSTIC and the student's diagnostic_score is
        still null, the student's diagnostic_score is set to the just-computed scaled_score".

        50/80 of 1600 = 1000.

        Design: Corner/state_machines/diagnostic_score_set_on_first_diagnostic_side_effect
        """
        base = setup_active_enrollment(fmt="SELF", student_email="diag@x.com")
        diag = score_attempt(base["enrollment"]["id"], base["instructor"]["id"],
                             "DIAGNOSTIC", 50, 80, base["student"]["id"])
        assert diag["scaled_score"] == 1000
        student = validate_success(api.get_student(base["student"]["id"], REGISTRAR))
        assert student["diagnostic_score"] == 1000

    def test_cohort_cancel_cascades_enrollment_cancel(self, api):
        """PRD §3.2: "Cancelling a `SCHEDULED` cohort moves it to `CANCELLED`, cascades a
        cancellation onto every enrollment on the cohort whose status is `ACTIVE`,
        `WAITLISTED`, or `PENDING_PAYMENT`"
        PRD §3.2: "and — if an instructor was assigned — decrements that instructor's
        `active_cohort_count` by one."

        Design: Corner/state_machines/cohort_cancel_cascades_enrollment_cancel
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="LIVE")
        student, enr = enroll_student(
            base["cohort"]["id"], expected_cohort_version=base["cohort_version"],
            email="casc@x.com")
        assert enr["status"] == "PENDING_PAYMENT"
        cancelled = validate_success(api.cancel_cohort(base["cohort"]["id"], REGISTRAR))
        assert cancelled["status"] == "CANCELLED"
        enr = validate_success(api.get_enrollment(enr["id"], REGISTRAR))
        assert enr["status"] == "CANCELLED"
        instructor = validate_success(api.get_instructor(base["instructor"]["id"], REGISTRAR))
        assert instructor["active_cohort_count"] == 0
