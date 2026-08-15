"""Lifecycle guards, terminal-state lockdowns, and initial states (PRD §3).

Covers School/Course/CourseApproval/CourseOffering/ExamAttempt/RefundRequest/
EquivalencyGrant/Enrollment state-machine guards and the initial states each
resource is born with.
"""
from test_helpers import (
    ApiErrorId,
    approve_course,
    assert_course_approval,
    create_active_course,
    create_credentialed_instructor,
    create_grant,
    create_instructor,
    create_licensed_school,
    create_offering,
    create_published_offering,
    create_proctor,
    create_report,
    create_student,
    enroll,
    enroll_and_pay,
    enroll_with_seat_time,
    enrollment_completed,
    get_certificate,
    get_enrollment,
    get_grant,
    get_offering,
    get_refund_for_enrollment,
    get_school,
    get_success_data,
    record_attendance,
    run_sweep,
    schedule_attempt,
    score_attempt,
    set_clock,
    setup_publishable_school,
    validate_error,
    validate_paginated,
    verify_attempt,
    withdraw_and_get_refund,
    withdraw_payload,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    COMMISSION,
    DIRECTOR,
    REGISTRAR,
    approve_instructor,
    create_course,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Corner/state_machines/cn_school_revoked_terminal_lockdown
# ---------------------------------------------------------------------------

class TestSchoolRevokedTerminalLockdown:
    def test_suspend_on_revoked_school_rejected(self, api):
        """PRD §3.1: "revocation moves any of `PROVISIONAL`, `LICENSED`, or
        `SUSPENDED` to the terminal `REVOKED`... and operations against a
        `REVOKED` school with `ERR_SCHOOL_TERMINAL`."

        Design: Corner/state_machines/cn_school_revoked_terminal_lockdown
        """
        school = create_licensed_school()
        get_success_data(api.revoke_school(school["id"], COMMISSION))
        resp = api.suspend_school(school["id"], COMMISSION)
        validate_error(resp, ApiErrorId.ERR_SCHOOL_TERMINAL)

    def test_revoked_school_status_unchanged_by_failed_suspend(self, api):
        """PRD §3.1: "revocation moves any of `PROVISIONAL`, `LICENSED`, or
        `SUSPENDED` to the terminal `REVOKED`" — terminal means no transition
        fires afterward.

        Design: Corner/state_machines/cn_school_revoked_terminal_lockdown
        """
        school = create_licensed_school()
        get_success_data(api.revoke_school(school["id"], COMMISSION))
        validate_error(api.suspend_school(school["id"], COMMISSION),
                       ApiErrorId.ERR_SCHOOL_TERMINAL)
        assert get_school(school["id"])["status"] == "REVOKED"


# ---------------------------------------------------------------------------
# Corner/state_machines/cn_school_suspend_reinstate_cycle
# ---------------------------------------------------------------------------

class TestSchoolSuspendReinstateCycle:
    def test_suspend_moves_licensed_to_suspended(self, api):
        """PRD §3.1: "suspension moves `LICENSED` to `SUSPENDED`".

        Design: Corner/state_machines/cn_school_suspend_reinstate_cycle
        """
        school = create_licensed_school()
        suspended = get_success_data(api.suspend_school(school["id"], COMMISSION))
        assert suspended["status"] == "SUSPENDED"

    def test_reinstate_returns_suspended_to_licensed(self, api):
        """PRD §3.1: "reinstatement returns `SUSPENDED` to `LICENSED`".

        Design: Corner/state_machines/cn_school_suspend_reinstate_cycle
        """
        school = create_licensed_school()
        get_success_data(api.suspend_school(school["id"], COMMISSION))
        reinstated = get_success_data(api.reinstate_school(school["id"], COMMISSION))
        assert reinstated["status"] == "LICENSED"


# ---------------------------------------------------------------------------
# Corner/state_machines/cn_offering_cancel_from_completed_rejected
# ---------------------------------------------------------------------------

class TestOfferingCancelFromCompletedRejected:
    def _completed_offering(self, api):
        env = setup_publishable_school()
        set_clock("2026-09-05T00:00:00Z")
        run_sweep()   # PUBLISHED -> IN_SESSION
        set_clock("2026-09-12T00:00:00Z")
        run_sweep()   # IN_SESSION -> COMPLETED
        return env

    def test_completed_offering_cannot_be_cancelled(self, api):
        """PRD §3.4: "Cancellation is available from `DRAFT`, `PUBLISHED`, or
        `IN_SESSION`; cancelling an offering in any other state is rejected with
        `ERR_OFFERING_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cn_offering_cancel_from_completed_rejected
        """
        env = self._completed_offering(api)
        offering = get_offering(env["offering"]["id"])
        assert offering["status"] == "COMPLETED"
        resp = api.cancel_offering(env["offering"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_OFFERING_NOT_CANCELLABLE)

    def test_completed_offering_status_survives_failed_cancel(self, api):
        """PRD §3.4: "From `PUBLISHED` the sweep moves the offering to
        `IN_SESSION` when today reaches `start_date`, and from `IN_SESSION` to
        `COMPLETED` once today passes `end_date`." A rejected cancel does not
        move the offering out of `COMPLETED`.

        Design: Corner/state_machines/cn_offering_cancel_from_completed_rejected
        """
        env = self._completed_offering(api)
        validate_error(api.cancel_offering(env["offering"]["id"], DIRECTOR),
                       ApiErrorId.ERR_OFFERING_NOT_CANCELLABLE)
        assert get_offering(env["offering"]["id"])["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Corner/state_machines/cn_score_requires_proctored
# ---------------------------------------------------------------------------

class TestScoreRequiresProctored:
    def _scheduled_attempt(self, api):
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        proctor = create_proctor(env["school"]["id"])
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        attempt = schedule_attempt(enr["id"], proctor["id"])
        return env, proctor, enr, attempt

    def test_scoring_scheduled_attempt_rejected(self, api):
        """PRD §3.7: "the attempt must be `PROCTORED` (verifying requires
        `SCHEDULED`, scoring requires `PROCTORED`, and any other state draws
        `ERR_EXAM_ATTEMPT_STATE_INVALID`)".

        Design: Corner/state_machines/cn_score_requires_proctored
        """
        env, _proctor, _enr, attempt = self._scheduled_attempt(api)
        resp = api.score_exam_attempt(
            attempt["id"], {"score_pct": 90},
            {"X-User-ID": env["instructor"]["id"], "X-User-Role": "Instructor",
             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_EXAM_ATTEMPT_STATE_INVALID)

    def test_failed_score_leaves_attempt_scheduled(self, api):
        """PRD §3.7: "any other state draws `ERR_EXAM_ATTEMPT_STATE_INVALID`" —
        the attempt remains `SCHEDULED` with no outcome.

        Design: Corner/state_machines/cn_score_requires_proctored
        """
        env, _proctor, _enr, attempt = self._scheduled_attempt(api)
        validate_error(api.score_exam_attempt(
            attempt["id"], {"score_pct": 90},
            {"X-User-ID": env["instructor"]["id"], "X-User-Role": "Instructor",
             "Content-Type": "application/json"}),
            ApiErrorId.ERR_EXAM_ATTEMPT_STATE_INVALID)
        after = get_success_data(api.get_exam_attempt(attempt["id"], REGISTRAR))
        assert after["status"] == "SCHEDULED"
        assert after["outcome"] is None


# ---------------------------------------------------------------------------
# Corner/state_machines/cn_refund_denied_terminal_lockdown
# ---------------------------------------------------------------------------

class TestRefundDeniedTerminalLockdown:
    def _denied_refund(self, api):
        env = setup_publishable_school()
        _s, enr = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                 amount_cents=51500)
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=300)
        _w, rr = withdraw_and_get_refund(enr["id"], reason="VOLUNTARY",
                                         effective_date="2026-09-04")
        get_success_data(api.deny_refund_request(
            rr["id"], {"denial_reason": "policy exception not met"}, DIRECTOR))
        return env, enr, rr

    def test_pay_on_denied_rejected(self, api):
        """PRD §3.9: "Payout is the `Registrar`'s act on an `APPROVED` request —
        again, any other state fails with `ERR_REFUND_STATE_INVALID`".

        Design: Corner/state_machines/cn_refund_denied_terminal_lockdown
        """
        _env, _enr, rr = self._denied_refund(api)
        resp = api.pay_refund_request(rr["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_REFUND_STATE_INVALID)

    def test_approve_on_denied_rejected_and_payment_stays_paid(self, api):
        """PRD §3.9: "a denial leaves the enrollment's `payment_status` at
        `PAID`, and approve or deny from any other state fails with
        `ERR_REFUND_STATE_INVALID`."

        Design: Corner/state_machines/cn_refund_denied_terminal_lockdown
        """
        _env, enr, rr = self._denied_refund(api)
        resp = api.approve_refund_request(rr["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_REFUND_STATE_INVALID)
        assert get_enrollment(enr["id"])["payment_status"] == "PAID"


# ---------------------------------------------------------------------------
# Corner/state_machines/cn_grant_revoke_terminal
# ---------------------------------------------------------------------------

class TestGrantRevokeTerminal:
    def test_second_revoke_rejected(self, api):
        """PRD §3.2: "Revocation by the `StateCommission` or the
        `ComplianceOfficer` moves a grant from `ACTIVE` or `SUSPENDED` to the
        terminal `REVOKED` — any other state draws `ERR_GRANT_STATE_INVALID`."

        Design: Corner/state_machines/cn_grant_revoke_terminal
        """
        school = create_licensed_school()
        course = create_active_course(school["id"])
        grant = create_grant(course["id"], "TX", "NM", course["version"])
        get_success_data(api.revoke_equivalency_grant(grant["id"], COMMISSION))
        resp = api.revoke_equivalency_grant(grant["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_GRANT_STATE_INVALID)
        assert get_grant(grant["id"])["status"] == "REVOKED"


# ---------------------------------------------------------------------------
# Corner/state_machines/cn_initial_states_on_create
# ---------------------------------------------------------------------------

class TestInitialStatesOnCreate:
    def test_approval_born_pending_round_one(self, api):
        """PRD §3.2: "Submitting an application for a `state_code` creates a
        `CourseApproval` in `PENDING` with `application_round` 1".

        Design: Corner/state_machines/cn_initial_states_on_create
        """
        school = create_licensed_school()
        course = create_course(school["id"])
        approval = get_success_data(api.create_course_approval(
            course["id"], {"state_code": "TX"}, COMPLIANCE))
        assert_course_approval(approval)
        assert approval["status"] == "PENDING"
        assert approval["application_round"] == 1

    def test_offering_enrollment_and_report_initial_states(self, api):
        """PRD §3.4: "A new offering stands `DRAFT` with `enrolled_count` 0 and
        `seats_available` equal to `capacity`." PRD §3.5: "The new enrollment
        starts with `academic_status` `ENROLLED` and `payment_status` `PENDING`"
        PRD §3.8: "its `submission_count` starts at 0. Reports are born `DRAFT`."
        and "The report's `reporting_deadline_date` is `period_end` plus 30
        calendar days".

        Design: Corner/state_machines/cn_initial_states_on_create
        """
        env_setup = setup_publishable_school()
        draft = create_offering(env_setup["course"]["id"], env_setup["instructor"]["id"],
                                start_date="2026-11-01", end_date="2026-11-05")
        assert draft["status"] == "DRAFT"
        _s, enr = enroll(env_setup["offering"]["id"], env_setup["school"]["id"])
        assert enr["academic_status"] == "ENROLLED"
        assert enr["payment_status"] == "PENDING"
        report = create_report(env_setup["school"]["id"], "2026-09-01", "2026-09-30")
        assert report["status"] == "DRAFT"
        assert report["submission_count"] == 0
        assert report["reporting_deadline_date"] == "2026-10-30"


# ---------------------------------------------------------------------------
# Corner/state_machines/cn_approval_decide_from_approved_rejected
# ---------------------------------------------------------------------------

class TestApprovalDecideFromApprovedRejected:
    def test_second_decide_rejected(self, api):
        """PRD §2.6: "approval in the correct state for decide, resubmit, or
        renew (`ERR_APPROVAL_STATE_INVALID`)" and §3.2: "The `StateCommission`
        then decides by supplying a `decision` of approve or deny" — decide is
        defined on a pending application ("Submitting an application ... creates
        a `CourseApproval` in `PENDING`... The `StateCommission` then decides"),
        and a renewal-pending application ("Renewal moves the application to
        `RENEWAL_PENDING`, from which the commission decides again"); an
        already-APPROVED application is in neither state.

        Design: Corner/state_machines/cn_approval_decide_from_approved_rejected
        """
        school = create_licensed_school()
        course = create_course(school["id"])
        approval = approve_course(course["id"])
        resp = api.decide_approval(approval["id"], {"decision": "DENIED"}, COMMISSION)
        validate_error(resp, ApiErrorId.ERR_APPROVAL_STATE_INVALID)
        after = get_success_data(api.get_approval(approval["id"], REGISTRAR))
        assert after["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Corner/state_machines/cn_certificate_requires_exam_passed
# ---------------------------------------------------------------------------

class TestCertificateRequiresExamPassed:
    def test_certificate_on_withdrawn_enrollment_rejected(self, api):
        """PRD §3.8: "Certificate issuance is the `Registrar`'s act on an
        enrollment standing `EXAM_PASSED` — any other state fails with
        `ERR_ENROLLMENT_STATE_INVALID`".

        Design: Corner/state_machines/cn_certificate_requires_exam_passed
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        get_success_data(api.withdraw_enrollment(enr["id"], withdraw_payload("VOLUNTARY"),
                                                 REGISTRAR))
        resp = api.issue_certificate(enr["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_STATE_INVALID)

    def test_no_certificate_exists_after_rejection(self, api):
        """PRD §3.8: "Certificate issuance is the `Registrar`'s act on an
        enrollment standing `EXAM_PASSED` — any other state fails with
        `ERR_ENROLLMENT_STATE_INVALID` — and at most one certificate ever exists
        per enrollment."

        Design: Corner/state_machines/cn_certificate_requires_exam_passed
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        get_success_data(api.withdraw_enrollment(enr["id"], withdraw_payload("VOLUNTARY"),
                                                 REGISTRAR))
        validate_error(api.issue_certificate(enr["id"], REGISTRAR),
                       ApiErrorId.ERR_ENROLLMENT_STATE_INVALID)
        certs, _meta = validate_paginated(api.list_certificates(REGISTRAR))
        assert [c for c in certs if c["enrollment_id"] == enr["id"]] == [], \
            "no Certificate exists for the withdrawn enrollment"


# ---------------------------------------------------------------------------
# Corner/state_machines/cn_double_certificate_and_double_pay_rejected
# ---------------------------------------------------------------------------

class TestDoubleCertificateAndDoublePayRejected:
    def _completed_paid_enrollment(self, api):
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        proctor = create_proctor(env["school"]["id"])
        _s, enr = enroll_and_pay(env["offering"]["id"], env["school"]["id"])
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=60)
        attempt = schedule_attempt(enr["id"], proctor["id"])
        verify_attempt(attempt["id"], proctor["id"])
        score_attempt(attempt["id"], env["instructor"]["id"], 90)
        cert = get_success_data(api.issue_certificate(enr["id"], REGISTRAR))
        return env, enr, cert

    def test_second_certificate_rejected(self, api):
        """PRD §3.8: "Certificate issuance is the `Registrar`'s act on an
        enrollment standing `EXAM_PASSED` — any other state fails with
        `ERR_ENROLLMENT_STATE_INVALID` — and at most one certificate ever exists
        per enrollment."

        Design: Corner/state_machines/cn_double_certificate_and_double_pay_rejected
        """
        _env, enr, cert = self._completed_paid_enrollment(api)
        resp = api.issue_certificate(enr["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_STATE_INVALID)
        certs, _meta = validate_paginated(api.list_certificates(REGISTRAR))
        mine = [c for c in certs if c["enrollment_id"] == enr["id"]]
        assert len(mine) == 1, "at most one certificate ever exists per enrollment"
        assert mine[0]["id"] == cert["id"]

    def test_second_pay_rejected(self, api):
        """PRD §2.6: "enrollment in a withdrawable, payable, voidable,
        certificate-issuable, or attempt-schedulable state
        (`ERR_ENROLLMENT_STATE_INVALID`)" — a PAID enrollment is no longer in a
        payable state ("A successful capture moves `payment_status` from
        `PENDING` to `PAID`", §3.5).

        Design: Corner/state_machines/cn_double_certificate_and_double_pay_rejected
        """
        _env, enr, _cert = self._completed_paid_enrollment(api)
        resp = api.pay_enrollment(enr["id"], {"amount_cents": 51500}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_STATE_INVALID)
