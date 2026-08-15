"""Credit-report lateness/rounding, RBAC, segregation of duties, the regulatory
sweep, audit-trail cascades, list filters, and the response envelope.

Covers PRD §2.1-§2.4 (roles, envelope, pagination, clock/sweep), §2.8 (audit
trail), and §3.8 (late fees, per-line rounding).
"""
from test_helpers import (
    ApiErrorId,
    assert_audit_event,
    create_licensed_school,
    create_proctor,
    create_report,
    enroll,
    enroll_and_pay,
    enroll_with_seat_time,
    get_enrollment,
    get_offering,
    get_success_data,
    make_proctor_headers,
    make_student_headers,
    record_attendance,
    run_sweep,
    schedule_attempt,
    set_clock,
    setup_publishable_school,
    validate_error,
    validate_paginated,
    validate_success,
    verify_attempt,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    COMMISSION,
    DIRECTOR,
    REGISTRAR,
    approve_course,
    create_course,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Corner/calculations/cn_late_fee_boundary_and_cap
# ---------------------------------------------------------------------------

class TestLateFeeBoundaryAndCap:
    def _three_reports(self, api):
        school = create_licensed_school()
        r1 = create_report(school["id"], "2026-09-01", "2026-09-30")  # deadline 2026-10-30
        r2 = create_report(school["id"], "2026-10-01", "2026-10-31")  # deadline 2026-11-30
        r3 = create_report(school["id"], "2026-11-01", "2026-11-30")  # deadline 2026-12-30
        return r1, r2, r3

    def test_submit_on_deadline_has_no_fee(self, api):
        """PRD §3.8: "`late_days` is the number of days by which the submit
        calendar date falls after `reporting_deadline_date`, floored at zero, so
        submitting exactly on the deadline day yields zero late days and no fee."

        Design: Corner/calculations/cn_late_fee_boundary_and_cap
        """
        r1, _r2, _r3 = self._three_reports(api)
        set_clock("2026-10-30T12:00:00Z")
        submitted = get_success_data(api.submit_credit_report(r1["id"], COMPLIANCE))
        assert submitted["late_days"] == 0
        assert submitted["late_fee_cents"] == 0

    def test_three_days_late_and_cap_at_forty_five(self, api):
        """PRD §3.8: "When at least one late day exists, `late_fee_cents` is 5000
        cents plus 1000 cents per late day, capped at 50000 cents — the cap binds
        from 45 late days upward, where the formula reaches the cap exactly."

        Design: Corner/calculations/cn_late_fee_boundary_and_cap
        """
        _r1, r2, r3 = self._three_reports(api)
        set_clock("2026-12-03T12:00:00Z")
        submitted2 = get_success_data(api.submit_credit_report(r2["id"], COMPLIANCE))
        assert submitted2["late_days"] == 3
        assert submitted2["late_fee_cents"] == 8000  # 5000 + 1000*3
        set_clock("2027-02-13T12:00:00Z")
        submitted3 = get_success_data(api.submit_credit_report(r3["id"], COMPLIANCE))
        assert submitted3["late_days"] == 45
        assert submitted3["late_fee_cents"] == 50000  # cap binds exactly


# ---------------------------------------------------------------------------
# Corner/calculations/cn_report_line_rounding_per_line_then_sum
# ---------------------------------------------------------------------------

class TestReportLineRoundingPerLineThenSum:
    def _two_certificates(self, api):
        """Two CE courses (7.24 and 0.24 credit hours), one COMPLETED enrollment
        each, certificates issued at the default clock (issue year 2026)."""
        school = create_licensed_school()
        from test_helpers.fixtures import create_credentialed_instructor, \
            create_active_course, create_published_offering
        ins = create_credentialed_instructor(school["id"])
        proctor = create_proctor(school["id"])
        certs = []
        for code, hours, window in (("CE-A", 7.24, ("2026-09-01", "2026-09-10")),
                                    ("CE-B", 0.24, ("2026-09-12", "2026-09-20"))):
            course = create_active_course(
                school["id"], course_code=code, course_type="CONTINUING_ED",
                required_seat_minutes=60, tuition_cents=10000, ce_credit_hours=hours)
            offering = create_published_offering(
                course["id"], ins["id"], start_date=window[0], end_date=window[1])
            _s, enr = enroll(offering["id"], school["id"])
            record_attendance(enr["id"], ins["id"], session_date=window[0], minutes=60)
            attempt = schedule_attempt(enr["id"], proctor["id"],
                                       scheduled_at="2026-09-25T14:00:00Z")
            verify_attempt(attempt["id"], proctor["id"])
            from test_helpers import score_attempt
            score_attempt(attempt["id"], ins["id"], 90)
            certs.append(get_success_data(api.issue_certificate(enr["id"], REGISTRAR)))
        return school, certs

    def test_per_line_rounding_then_sum(self, api):
        """PRD §3.8: "Each line carries the certificate as `certificate_id`, its
        enrollment, its student, and a `credit_hours` value rounded to the
        nearest half hour with halves rounded up; `total_credit_hours` is the sum
        of the per-line rounded values — rounding per line first and then summing
        is the pinned order, since summing raw hours and rounding once yields
        different results."

        Design: Corner/calculations/cn_report_line_rounding_per_line_then_sum
        """
        school, certs = self._two_certificates(api)
        report = create_report(school["id"], "2026-08-01", "2026-08-31")
        # 7.24 -> 7.0 per line; 0.24 -> 0.0 per line; raw sum 7.48 would round to 7.5.
        assert report["total_credit_hours"] == 7.0
        lines = {line["certificate_id"]: line["credit_hours"] for line in report["line_items"]}
        assert lines[certs[0]["id"]] == 7.0
        assert lines[certs[1]["id"]] == 0.0

    def test_line_ordering_by_issue_date_then_created(self, api):
        """PRD §3.8: "Lines are ordered by certificate `issue_date` ascending,
        ties broken by certificate `created_at` ascending."

        Design: Corner/calculations/cn_report_line_rounding_per_line_then_sum
        """
        school, certs = self._two_certificates(api)
        report = create_report(school["id"], "2026-08-01", "2026-08-31")
        ordered = [line["certificate_id"] for line in report["line_items"]]
        # Both certificates share the same issue date (the default clock day), so
        # created_at ascending orders certA before certB.
        assert ordered == [certs[0]["id"], certs[1]["id"]]


# ---------------------------------------------------------------------------
# Corner/rbac/cn_rbac_registrar_cannot_create_course
# ---------------------------------------------------------------------------

def test_rbac_registrar_cannot_create_course(api):
    """PRD §4: `POST /courses` lists authorized role SchoolDirector only, and
    §2.1: "When the role is valid but not on the endpoint's authorized list, the
    rejection is `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/cn_rbac_registrar_cannot_create_course
    """
    school = create_licensed_school()
    resp = api.create_course(
        {"school_id": school["id"], "course_code": "PRE-101", "title": "TX",
         "course_type": "PRE_LICENSING", "required_seat_minutes": 3000,
         "tuition_cents": 50000, "pass_score_pct": 70,
         "completion_deadline_days": 30}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


# ---------------------------------------------------------------------------
# Corner/rbac/cn_rbac_student_cannot_decide_approval
# ---------------------------------------------------------------------------

def test_rbac_student_cannot_decide_approval(api):
    """PRD §4: `POST /approvals/{id}/decide` lists authorized role
    StateCommission only, and §2.1: "When the role is valid but not on the
    endpoint's authorized list, the rejection is `ERR_UNAUTHORIZED_ROLE` (HTTP
    403)."

    Design: Corner/rbac/cn_rbac_student_cannot_decide_approval
    """
    school = create_licensed_school()
    course = create_course(school["id"])
    approval = get_success_data(api.create_course_approval(course["id"],
                                                           {"state_code": "TX"}, COMPLIANCE))
    from test_helpers import create_student
    student = create_student(school["id"])
    resp = api.decide_approval(
        approval["id"],
        {"decision": "APPROVED", "valid_from": "2026-08-01", "valid_until": "2027-07-31"},
        make_student_headers(student["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = get_success_data(api.get_approval(approval["id"], REGISTRAR))
    assert after["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner/rbac/cn_rbac_proctor_cannot_score_and_student_cannot_read_staff_endpoints
# ---------------------------------------------------------------------------

class TestRbacProctorAndStudentExclusivity:
    def _proctored_attempt(self, api):
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        proctor = create_proctor(env["school"]["id"])
        student, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                             env["instructor"]["id"], minutes=60)
        attempt = schedule_attempt(enr["id"], proctor["id"])
        verify_attempt(attempt["id"], proctor["id"])
        return env, proctor, student, attempt

    def test_proctor_cannot_score(self, api):
        """PRD §3.7: "Scoring belongs to the instructor of record alone" and §4:
        `POST /exam-attempts/{id}/score` lists authorized role Instructor only;
        §2.1: "When the role is valid but not on the endpoint's authorized list,
        the rejection is `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/cn_rbac_proctor_cannot_score_and_student_cannot_read_staff_endpoints
        """
        _env, proctor, _student, attempt = self._proctored_attempt(api)
        resp = api.score_exam_attempt(attempt["id"], {"score_pct": 90},
                                      make_proctor_headers(proctor["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_exam_attempt(attempt["id"], REGISTRAR))
        assert after["status"] == "PROCTORED"

    def test_student_cannot_read_staff_audit_log(self, api):
        """PRD §4: `GET /audit-events` lists authorized roles StateCommission,
        SchoolDirector, Registrar, ComplianceOfficer (no Student), and §2.1:
        "When the role is valid but not on the endpoint's authorized list, the
        rejection is `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/cn_rbac_proctor_cannot_score_and_student_cannot_read_staff_endpoints
        """
        _env, _proctor, student, _attempt = self._proctored_attempt(api)
        resp = api.list_audit_events(make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


# ---------------------------------------------------------------------------
# Corner/validations/cn_proctor_scope_verify
# ---------------------------------------------------------------------------

class TestProctorScopeVerify:
    def test_wrong_proctor_cannot_verify(self, api):
        """PRD §3.7: "On exam day the assigned proctor verifies the candidate —
        verification requires the caller's `X-User-ID` to equal the attempt's
        `proctor_instructor_id` (`ERR_FORBIDDEN_SCOPE`)".

        Design: Corner/validations/cn_proctor_scope_verify
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        proctor = create_proctor(env["school"]["id"])
        other = create_proctor(env["school"]["id"])
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        attempt = schedule_attempt(enr["id"], proctor["id"])
        resp = api.verify_exam_attempt(attempt["id"], make_proctor_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SCOPE)

    def test_assigned_proctor_verifies(self, api):
        """PRD §3.7: "moving the attempt from `SCHEDULED` to `PROCTORED` and
        stamping `verified_at`".

        Design: Corner/validations/cn_proctor_scope_verify
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        proctor = create_proctor(env["school"]["id"])
        other = create_proctor(env["school"]["id"])
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        attempt = schedule_attempt(enr["id"], proctor["id"])
        validate_error(api.verify_exam_attempt(attempt["id"],
                                               make_proctor_headers(other["id"])),
                       ApiErrorId.ERR_FORBIDDEN_SCOPE)
        verified = get_success_data(api.verify_exam_attempt(
            attempt["id"], make_proctor_headers(proctor["id"])))
        assert verified["status"] == "PROCTORED"
        assert verified["verified_at"] is not None


# ---------------------------------------------------------------------------
# Corner/rbac/cn_sod_proctor_must_not_be_instructor
# ---------------------------------------------------------------------------

class TestSodProctorMustNotBeInstructor:
    def test_offering_instructor_as_proctor_rejected(self, api):
        """PRD §3.7: "Segregation of duties is absolute: the proctor must not be
        the offering's instructor of record — a `proctor_instructor_id` equal to
        the offering's `instructor_id` is rejected with
        `ERR_PROCTOR_IS_INSTRUCTOR`".

        Design: Corner/rbac/cn_sod_proctor_must_not_be_instructor
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        resp = api.create_exam_attempt(
            enr["id"],
            {"scheduled_at": "2026-09-11T14:00:00Z",
             "proctor_instructor_id": env["instructor"]["id"]},
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_PROCTOR_IS_INSTRUCTOR)

    def test_distinct_proctor_succeeds_without_slot_consumption(self, api):
        """PRD §3.7: "The new attempt's `attempt_number` is `exam_attempts_used`
        plus 1, and it starts `SCHEDULED`." The rejected create consumes no slot.

        Design: Corner/rbac/cn_sod_proctor_must_not_be_instructor
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60})
        proctor = create_proctor(env["school"]["id"])
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        validate_error(api.create_exam_attempt(
            enr["id"], {"scheduled_at": "2026-09-11T14:00:00Z",
                        "proctor_instructor_id": env["instructor"]["id"]}, REGISTRAR),
            ApiErrorId.ERR_PROCTOR_IS_INSTRUCTOR)
        attempt = get_success_data(api.create_exam_attempt(
            enr["id"], {"scheduled_at": "2026-09-11T14:00:00Z",
                        "proctor_instructor_id": proctor["id"]}, REGISTRAR))
        assert attempt["attempt_number"] == 1, "rejected create consumed no slot"


# ---------------------------------------------------------------------------
# Corner/cross_cutting/cn_scheduled_sweep_advances_epochs
# ---------------------------------------------------------------------------

class TestScheduledSweepAdvancesEpochs:
    def _seat_time_met_with_scheduled_attempt(self, api):
        env = setup_publishable_school(
            course_overrides={"required_seat_minutes": 60,
                              "completion_deadline_days": 30})
        proctor = create_proctor(env["school"]["id"])
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        attempt = schedule_attempt(enr["id"], proctor["id"],
                                   scheduled_at="2026-09-11T14:00:00Z")
        return env, enr, attempt

    def test_sweep_advances_offering_at_start_date(self, api):
        """PRD §2.4: "second, `PUBLISHED` offerings whose `start_date` is today
        or earlier move to `IN_SESSION`... fourth, exam attempts still
        `SCHEDULED` more than 24 hours after their `scheduled_at` instant move to
        `NO_SHOW`".

        Design: Corner/cross_cutting/cn_scheduled_sweep_advances_epochs
        """
        env, _enr, _attempt = self._seat_time_met_with_scheduled_attempt(api)
        set_clock("2026-09-05T00:00:00Z")
        summary = run_sweep()
        assert summary["offerings_advanced"] == 1, "PUBLISHED -> IN_SESSION"
        assert summary["attempts_no_show"] == 0, "24h grace not elapsed at 2026-09-05"
        assert get_offering(env["offering"]["id"])["status"] == "IN_SESSION"

    def test_sweep_no_show_after_grace_and_expiry_after_deadline(self, api):
        """PRD §2.4: "fourth, exam attempts still `SCHEDULED` more than 24 hours
        after their `scheduled_at` instant move to `NO_SHOW`... third,
        non-terminal enrollments whose `deadline_date` is before today move to
        `EXPIRED`" and "Each entity advances at most one state hop per sweep
        run".

        Design: Corner/cross_cutting/cn_scheduled_sweep_advances_epochs
        """
        env, enr, _attempt = self._seat_time_met_with_scheduled_attempt(api)
        set_clock("2026-09-05T00:00:00Z")
        run_sweep()
        set_clock("2026-09-12T15:00:00Z")
        summary = run_sweep()
        assert summary["attempts_no_show"] == 1, "scheduled_at + 24h = 2026-09-12T14:00 passed"
        # The same run completes the offering (IN_SESSION -> COMPLETED; end
        # 2026-09-10 has passed).
        assert get_offering(env["offering"]["id"])["status"] == "COMPLETED"
        set_clock("2026-10-11T00:00:00Z")
        summary = run_sweep()
        assert summary["enrollments_expired"] == 1, "today > deadline 2026-10-10"
        assert summary["offerings_advanced"] == 0
        assert get_enrollment(enr["id"])["academic_status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Corner/cross_cutting/cn_cascade_writes_audit_events
# ---------------------------------------------------------------------------

class TestCascadeWritesAuditEvents:
    def test_cancel_cascade_events_on_offering_and_enrollment(self, api):
        """PRD §3.4: "The cascade writes a `CASCADED_CANCELLATION` audit event on
        the offering and a `STATUS_CHANGE` event per enrollment." and §2.8: with
        "the literal value "system" for sweep and cascade events" on actor fields.

        Design: Corner/cross_cutting/cn_cascade_writes_audit_events
        """
        env = setup_publishable_school()
        _s, enr = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                 amount_cents=51500)
        get_success_data(api.cancel_offering(env["offering"]["id"], DIRECTOR))
        offering_events, _m1 = validate_paginated(api.list_audit_events(
            REGISTRAR, params={"entity_type": "CourseOffering",
                               "entity_id": env["offering"]["id"]}))
        for event in offering_events:
            assert_audit_event(event)
        cancellation = [e for e in offering_events
                        if e["event_type"] == "CASCADED_CANCELLATION"]
        assert len(cancellation) == 1, "offering carries the cascade event"
        assert cancellation[0]["detail"]["to_status"] == "CANCELLED"

        enrollment_events, _m2 = validate_paginated(api.list_audit_events(
            REGISTRAR, params={"entity_type": "Enrollment", "entity_id": enr["id"]}))
        withdrawal = [e for e in enrollment_events
                      if e["event_type"] == "STATUS_CHANGE"
                      and e["detail"].get("to_status") == "WITHDRAWN"]
        assert len(withdrawal) == 1
        assert withdrawal[0]["detail"]["from_status"] == "ENROLLED"
        assert withdrawal[0]["actor_role"] == "system", \
            "cascaded hop is recorded with actor_role 'system'"


# ---------------------------------------------------------------------------
# Corner/endpoints/cn_response_envelope_shape
# ---------------------------------------------------------------------------

def test_response_envelope_shape(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format" carrying `meta.api_request_id`,
    `response_type` ("object" for a single resource), and `data`; and error
    responses carry `response_type` "error" with `data.error_id` and
    `data.message`: "The `error_id` is a unique, machine-readable string that
    identifies the specific error." and "The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/cn_response_envelope_shape
    """
    school = get_success_data(api.create_school(
        {"school_name": "Lone Star Realty School", "school_code": "LSRS-ENV",
         "home_state_code": "TX"}, DIRECTOR))
    resp = api.get_school(school["id"], REGISTRAR)
    body = resp.json()
    assert resp.status_code == 200
    assert "api_request_id" in body["meta"]
    assert body["response_type"] == "object"
    assert body["data"]["id"] == school["id"]

    err_resp = api.get_school("00000000-0000-0000-0000-000000000000", REGISTRAR)
    err_body = err_resp.json()
    assert err_resp.status_code == 404
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_SCHOOL_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]


# ---------------------------------------------------------------------------
# Corner/consistency/cn_immediate_visibility_after_mutation
# ---------------------------------------------------------------------------

def test_immediate_visibility_after_mutation(api):
    """PRD §3.5: "The offering's `enrolled_count` and `seats_available` are
    recomputed" on creation ("This recomputation runs on every event that moves
    an enrollment into or out of the active set — creation, withdrawal, expiry,
    failure, the cancellation cascade, and capacity updates.") — the very next
    read reflects the consumed seat.

    Design: Corner/consistency/cn_immediate_visibility_after_mutation
    """
    env = setup_publishable_school()
    enroll(env["offering"]["id"], env["school"]["id"])
    offering = get_success_data(api.get_offering(env["offering"]["id"], REGISTRAR))
    assert offering["enrolled_count"] == 1
    assert offering["seats_available"] == 1
