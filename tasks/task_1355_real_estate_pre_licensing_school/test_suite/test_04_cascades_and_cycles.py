"""Transitive cascades and cyclic workflows (PRD §3.4, §3.7, §3.8).

Covers the exam-invalidation depth-4 cascade, the offering-cancellation
withdrawal/refund cascade, the approval-expiry grant suspend/resume cascade,
the credit-report correction cycle, and certificate sequence conservation.
"""
from test_helpers import (
    ApiErrorId,
    approve_course,
    create_active_course,
    create_credentialed_instructor,
    create_grant,
    create_licensed_school,
    create_proctor,
    create_report,
    enroll,
    enroll_and_pay,
    enrollment_completed,
    get_certificate,
    get_enrollment,
    get_grant,
    get_offering,
    get_refund_for_enrollment,
    get_success_data,
    record_attendance,
    run_sweep,
    set_clock,
    setup_publishable_school,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COMPLIANCE, COMMISSION, DIRECTOR, REGISTRAR
from test_helpers.fixtures import create_course as _create_course
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/exam_invalidation_depth4_cascade
# ---------------------------------------------------------------------------

class TestExamInvalidationDepth4Cascade:
    def test_scored_passed_invalidation_unwinds_to_report_amendment(self, api):
        """PRD §3.7: "Invalidating a `SCORED` attempt whose `outcome` was
        `PASSED` unwinds the academic record: the enrollment regresses from
        `EXAM_PASSED` back to `SEAT_TIME_MET` — or from `COMPLETED` back to
        `SEAT_TIME_MET`, a rare exit from the apex state — and, when the
        regression leaves a `COMPLETED` enrollment, the cascade continues: the
        enrollment's certificate moves from `ACTIVE` to `REVOKED` with
        `revoked_reason` `EXAM_INVALIDATED`, and that revocation in turn fires
        the credit-report amendment drafting described in §3.8."

        Design: Difficulty/transitive_cascade/exam_invalidation_depth4_cascade
        """
        env = setup_publishable_school(
            course_overrides={"course_type": "CONTINUING_ED",
                              "required_seat_minutes": 60,
                              "tuition_cents": 10000,
                              "ce_credit_hours": 7.5})
        proctor = create_proctor(env["school"]["id"])
        student, enr = enroll(env["offering"]["id"], env["school"]["id"])
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=60)
        from test_helpers import schedule_attempt, verify_attempt, score_attempt
        attempt = schedule_attempt(enr["id"], proctor["id"])
        verify_attempt(attempt["id"], proctor["id"])
        score_attempt(attempt["id"], env["instructor"]["id"], 90)
        # Issue the certificate with the clock pinned inside the report window.
        set_clock("2026-09-11T09:00:00Z")
        cert = get_success_data(api.issue_certificate(enr["id"], REGISTRAR))
        report = create_report(env["school"]["id"], "2026-09-01", "2026-09-30")
        assert report["total_credit_hours"] == 7.5
        set_clock("2026-09-15T09:00:00Z")
        get_success_data(api.submit_credit_report(report["id"], COMPLIANCE))
        get_success_data(api.acknowledge_credit_report(report["id"], COMMISSION))

        # L0 trigger: invalidate the SCORED-PASSED attempt as the assigned proctor.
        from test_helpers import make_proctor_headers
        invalidated = get_success_data(api.invalidate_exam_attempt(
            attempt["id"], {"reason": "identity verification failed"},
            make_proctor_headers(proctor["id"])))
        assert invalidated["status"] == "INVALIDATED"

        enr = get_enrollment(enr["id"])
        assert enr["academic_status"] == "SEAT_TIME_MET", "L1 regression from COMPLETED"
        assert enr["exam_attempts_used"] == 0, "INVALIDATED attempts consume no slot"

        cert = get_certificate(cert["id"])
        assert cert["status"] == "REVOKED"  # L2
        assert cert["revoked_reason"] == "EXAM_INVALIDATED"

        amendments, _meta = validate_paginated(api.list_credit_reports(
            COMPLIANCE, params={"amendment_of_id": report["id"]}))
        assert len(amendments) == 1, "L3 auto-amendment drafted"
        amendment = amendments[0]
        assert amendment["status"] == "DRAFT"
        assert amendment["amendment_of_id"] == report["id"]
        assert amendment["total_credit_hours"] == -7.5, "negated revoked line"

    def test_invalidation_frees_the_exam_slot(self, api):
        """PRD §3.7: "Invalidating a `SCHEDULED` or `PROCTORED` attempt simply
        frees its slot." and "`exam_attempts_used` counts the enrollment's
        attempts in `SCHEDULED`, `PROCTORED`, `SCORED`, or `NO_SHOW` —
        `INVALIDATED` attempts consume no slot".

        Design: Difficulty/transitive_cascade/exam_invalidation_depth4_cascade
        """
        env = setup_publishable_school(
            course_overrides={"course_type": "CONTINUING_ED",
                              "required_seat_minutes": 60,
                              "tuition_cents": 10000,
                              "ce_credit_hours": 7.5})
        proctor = create_proctor(env["school"]["id"])
        student, enr, attempt, cert = enrollment_completed(
            env["offering"]["id"], env["school"]["id"], env["instructor"]["id"],
            proctor["id"], minutes=60, score_pct=90)
        from test_helpers import make_proctor_headers
        get_success_data(api.invalidate_exam_attempt(
            attempt["id"], {"reason": "identity verification failed"},
            make_proctor_headers(proctor["id"])))
        enr = get_enrollment(enr["id"])
        assert enr["exam_attempts_used"] == 0, "slot freed by invalidation"
        assert enr["academic_status"] == "SEAT_TIME_MET", "exam-eligible again"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/offering_cancel_withdrawal_refund_cascade
# ---------------------------------------------------------------------------

class TestOfferingCancelWithdrawalRefundCascade:
    def test_cancel_cascades_withdrawals_and_full_refunds(self, api):
        """PRD §3.4: "Cancelling a `PUBLISHED` or `IN_SESSION` offering triggers
        a three-level cascade. First, every enrollment of the offering whose
        `academic_status` is `ENROLLED`, `IN_PROGRESS`, `SEAT_TIME_MET`, or
        `EXAM_PASSED` moves to `WITHDRAWN` with `withdrawal_reason`
        `SCHOOL_CANCELLED` and `withdrawn_at` set to now... Second, for each such
        enrollment whose `payment_status` is `PAID`, a refund request is
        auto-created in `PENDING` with `reason` `SCHOOL_CANCELLED` and the
        scheduled, statutory, and granted amounts all equal to the enrollment's
        `paid_cents`... Third, the offering's `enrolled_count` and
        `seats_available` are recomputed, each withdrawal decrementing the
        count."

        Design: Difficulty/transitive_cascade/offering_cancel_withdrawal_refund_cascade
        """
        env = setup_publishable_school()
        _sa, ea = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                 amount_cents=51500)
        _sb, eb = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                 amount_cents=51500)
        cancelled = get_success_data(api.cancel_offering(env["offering"]["id"], DIRECTOR))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["enrolled_count"] == 0
        assert cancelled["seats_available"] == 2
        for e in (ea, eb):
            final = get_enrollment(e["id"])
            assert final["academic_status"] == "WITHDRAWN"
            assert final["withdrawal_reason"] == "SCHOOL_CANCELLED"
            rr = get_refund_for_enrollment(e["id"])
            assert rr is not None, "L2 auto-created refund"
            assert rr["reason"] == "SCHOOL_CANCELLED"
            assert rr["granted_refund_cents"] == 51500, "100% branch"

    def test_cascade_refund_settles_to_refunded_after_pay(self, api):
        """PRD §3.4: "for each such enrollment whose `payment_status` is `PAID`,
        a refund request is auto-created in `PENDING` with `reason`
        `SCHOOL_CANCELLED` and the scheduled, statutory, and granted amounts all
        equal to the enrollment's `paid_cents`" and §3.9: "`payment_status`
        moves to `REFUNDED` when the granted amount equals the full
        `paid_cents`".

        Design: Difficulty/transitive_cascade/offering_cancel_withdrawal_refund_cascade
        """
        env = setup_publishable_school()
        _sa, ea = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                 amount_cents=51500)
        get_success_data(api.cancel_offering(env["offering"]["id"], DIRECTOR))
        rr = get_refund_for_enrollment(ea["id"])
        get_success_data(api.approve_refund_request(rr["id"], DIRECTOR))
        paid_rr = get_success_data(api.pay_refund_request(rr["id"], REGISTRAR))
        assert paid_rr["status"] == "PAID"
        final = get_enrollment(ea["id"])
        assert final["payment_status"] == "REFUNDED"
        assert final["retained_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/approval_expiry_grant_suspend_resume_cascade
# ---------------------------------------------------------------------------

class TestApprovalExpiryGrantSuspendResumeCascade:
    def _school_course_grant_expiring(self, api):
        """ACTIVE grant TX->NM on a course whose TX approval has valid_until
        2026-09-30; returns (school, course, approval, grant)."""
        school = create_licensed_school()
        course = _create_course(school["id"])
        approval = approve_course(course["id"], valid_until="2026-09-30")
        course = get_success_data(api.activate_course(course["id"], DIRECTOR))
        grant = create_grant(course["id"], "TX", "NM", course["version"])
        return school, course, approval, grant

    def test_expiry_suspends_and_renewal_approval_resumes(self, api):
        """PRD §3.2: "when an approval lapses to `EXPIRED` — by sweep or by a
        denied renewal — every equivalency grant of that course and state
        standing `ACTIVE` is suspended" and "Approval of a course in its home
        state has a second effect: every equivalency grant of that course keyed
        on that state with status `SUSPENDED` resumes to `ACTIVE`."

        Design: Difficulty/transitive_cascade/approval_expiry_grant_suspend_resume_cascade
        """
        school, course, approval, grant = self._school_course_grant_expiring(api)
        assert grant["status"] == "ACTIVE"
        set_clock("2026-09-01T00:00:00Z")
        run_sweep()  # APPROVED -> EXPIRING
        set_clock("2026-10-01T00:00:00Z")
        summary = run_sweep()  # EXPIRING -> EXPIRED, grant ACTIVE -> SUSPENDED
        assert summary["grants_suspended"] == 1
        assert get_grant(grant["id"])["status"] == "SUSPENDED"
        # Late renewal is within 30 days after valid_until 2026-09-30.
        renewed = get_success_data(api.renew_approval(approval["id"], COMPLIANCE))
        assert renewed["status"] == "RENEWAL_PENDING"
        decided = get_success_data(api.decide_approval(
            approval["id"],
            {"decision": "APPROVED", "valid_from": "2026-10-01",
             "valid_until": "2027-09-30"},
            COMMISSION))
        assert decided["application_round"] == 2
        assert get_grant(grant["id"])["status"] == "ACTIVE", "reverse cascade auto-resume"

    def test_grant_created_active(self, api):
        """PRD §3.2: "A grant is created by the `ComplianceOfficer` with the
        `course_id`, the `home_state_code` where the course holds its direct
        approval, and the `recognized_state_code` doing the recognizing... New
        grants stand `ACTIVE`."

        Design: Difficulty/transitive_cascade/approval_expiry_grant_suspend_resume_cascade
        """
        school, course, approval, grant = self._school_course_grant_expiring(api)
        assert grant["status"] == "ACTIVE"
        assert grant["home_state_code"] == "TX"
        assert grant["recognized_state_code"] == "NM"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/credit_report_correction_cycle
# ---------------------------------------------------------------------------

class TestCreditReportCorrectionCycle:
    def _report_with_line(self, api):
        """Base report (September window) over one ACTIVE certificate of 7.5
        hours; returns (env, report)."""
        env = setup_publishable_school(
            course_overrides={"course_type": "CONTINUING_ED",
                              "required_seat_minutes": 60,
                              "tuition_cents": 10000,
                              "ce_credit_hours": 7.5})
        proctor = create_proctor(env["school"]["id"])
        student, enr = enroll(env["offering"]["id"], env["school"]["id"])
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=60)
        from test_helpers import schedule_attempt, verify_attempt, score_attempt
        attempt = schedule_attempt(enr["id"], proctor["id"])
        verify_attempt(attempt["id"], proctor["id"])
        score_attempt(attempt["id"], env["instructor"]["id"], 90)
        set_clock("2026-09-11T09:00:00Z")
        get_success_data(api.issue_certificate(enr["id"], REGISTRAR))
        report = create_report(env["school"]["id"], "2026-09-01", "2026-09-30")
        return env, report

    def test_correction_loop_submission_count_monotonic(self, api):
        """PRD §3.8: "Rejection opens the correction cycle: revision by the
        `ComplianceOfficer` returns `REJECTED` to `DRAFT`, clears `submitted_at`
        to null, and recomputes `line_items` and `total_credit_hours` from
        current certificate states, ready to be submitted again;
        `submission_count` only ever increases."

        Design: Difficulty/non_linear_state_machine/credit_report_correction_cycle
        """
        _env, report = self._report_with_line(api)
        assert report["total_credit_hours"] == 7.5, "per-line rounded snapshot"
        set_clock("2026-09-15T09:00:00Z")
        submitted = get_success_data(api.submit_credit_report(report["id"], COMPLIANCE))
        assert submitted["late_fee_cents"] == 0, "2026-09-15 <= deadline 2026-10-30"
        assert submitted["submission_count"] == 1
        get_success_data(api.reject_credit_report(
            report["id"], {"reason": "malformed roster row"}, COMMISSION))
        revised = get_success_data(api.revise_credit_report(report["id"], COMPLIANCE))
        assert revised["status"] == "DRAFT", "cycle back"
        assert revised["submitted_at"] is None
        resubmitted = get_success_data(api.submit_credit_report(report["id"], COMPLIANCE))
        assert resubmitted["submission_count"] == 2
        assert resubmitted["late_days"] == 0
        acknowledged = get_success_data(api.acknowledge_credit_report(report["id"], COMMISSION))
        assert acknowledged["status"] == "ACKNOWLEDGED"

    def test_revise_recomputes_lines_from_current_certificate_states(self, api):
        """PRD §3.8: "revision by the `ComplianceOfficer` returns `REJECTED` to
        `DRAFT`, clears `submitted_at` to null, and recomputes `line_items` and
        `total_credit_hours` from current certificate states".

        Design: Difficulty/non_linear_state_machine/credit_report_correction_cycle
        """
        env, report = self._report_with_line(api)
        get_success_data(api.submit_credit_report(report["id"], COMPLIANCE))
        get_success_data(api.reject_credit_report(
            report["id"], {"reason": "malformed roster row"}, COMMISSION))
        # Revoke the only certificate before revising: the recompute drops it.
        certs, _meta = validate_paginated(api.list_certificates(REGISTRAR))
        active = [c for c in certs if c["status"] == "ACTIVE"]
        assert len(active) == 1
        get_success_data(api.revoke_certificate(
            active[0]["id"], {"reason": "commission audit finding"}, COMMISSION))
        revised = get_success_data(api.revise_credit_report(report["id"], COMPLIANCE))
        assert revised["status"] == "DRAFT"
        assert revised["total_credit_hours"] == 0, \
            "revoked certificate no longer contributes lines"
        assert revised["line_items"] == []


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/certificate_sequence_conservation
# ---------------------------------------------------------------------------

class TestCertificateSequenceConservation:
    def _three_exam_passed(self, api):
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60},
                                       offering_overrides={"capacity": 5})
        proctor = create_proctor(env["school"]["id"])
        completed = []
        for score in (90, 85):
            completed.append(enrollment_completed(
                env["offering"]["id"], env["school"]["id"], env["instructor"]["id"],
                proctor["id"], minutes=60, score_pct=score))
        # Third student stops at EXAM_PASSED.
        from test_helpers import enrollment_exam_passed
        third = enrollment_exam_passed(env["offering"]["id"], env["school"]["id"],
                                       env["instructor"]["id"], proctor["id"],
                                       minutes=60, score_pct=75)
        return env, completed, third

    def test_revocation_never_frees_a_number(self, api):
        """PRD §3.8: "the sequence is the count of all certificates the school
        has ever issued in that calendar year plus one, with `ACTIVE` and
        `REVOKED` certificates both counted and numbers never reused — a
        revocation never frees a number."

        Design: Difficulty/compensating_invariant/certificate_sequence_conservation
        """
        env, completed, third = self._three_exam_passed(api)
        certs = [c for (_s, _e, _a, c) in completed]
        school = get_success_data(api.get_school(env["school"]["id"], REGISTRAR))
        prefix = school["school_code"]
        numbers = sorted(c["certificate_number"] for c in certs)
        assert numbers == [f"{prefix}-2026-0001", f"{prefix}-2026-0002"]
        get_success_data(api.revoke_certificate(
            certs[0]["id"], {"reason": "commission audit finding"}, COMMISSION))
        _s, e3, _a = third
        cert3 = get_success_data(api.issue_certificate(e3["id"], REGISTRAR))
        assert cert3["certificate_number"] == f"{prefix}-2026-0003", \
            "revoked numbers are never reused"
        assert get_certificate(certs[0]["id"])["status"] == "REVOKED"
        assert cert3["status"] == "ACTIVE"

    def test_issued_total_equals_active_plus_revoked(self, api):
        """PRD §3.8: "the sequence is the count of all certificates the school
        has ever issued in that calendar year plus one, with `ACTIVE` and
        `REVOKED` certificates both counted and numbers never reused".

        Design: Difficulty/compensating_invariant/certificate_sequence_conservation
        """
        env, completed, third = self._three_exam_passed(api)
        certs = [c for (_s, _e, _a, c) in completed]
        get_success_data(api.revoke_certificate(
            certs[0]["id"], {"reason": "commission audit finding"}, COMMISSION))
        _s, e3, _a = third
        get_success_data(api.issue_certificate(e3["id"], REGISTRAR))
        certs, _m = validate_paginated(api.list_certificates(REGISTRAR))
        active = [c for c in certs if c["status"] == "ACTIVE"]
        revoked = [c for c in certs if c["status"] == "REVOKED"]
        # Invariant: issued total (3) == count(ACTIVE) 2 + count(REVOKED) 1.
        assert len(active) == 2
        assert len(revoked) == 1
        assert len(active) + len(revoked) == 3
