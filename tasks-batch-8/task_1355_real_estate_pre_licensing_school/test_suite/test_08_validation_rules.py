"""Request-shape, existence, scope, uniqueness, and temporal validations.

Covers the validation pipeline's individual rules (PRD §2.6) on isolated
scenarios where exactly one rule can fail, plus the entity-level field rules
(required fields, defaults, computed-field rejection, enum rejection,
server-minted system fields).
"""
from test_helpers import (
    BADID,
    CLOCK_DEFAULT_ISO,
    ApiErrorId,
    approve_course,
    create_active_course,
    create_credentialed_instructor,
    create_grant,
    create_licensed_school,
    create_offering,
    create_published_offering,
    create_report,
    create_school,
    create_student,
    enroll,
    get_success_data,
    is_valid_uuid,
    make_school_director_headers,
    make_student_headers,
    run_sweep,
    set_clock,
    setup_publishable_school,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    COMMISSION,
    DIRECTOR,
    REGISTRAR,
    create_course,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Corner/entities/cn_school_create_missing_required_field
# ---------------------------------------------------------------------------

def test_school_create_missing_school_code_rejected(api):
    """PRD §3.1: "A school enters the system when a `SchoolDirector` registers it
    with its legal `school_name`, a `school_code`, the `home_state_code` of its
    primary licensure state" and §2.6 rule 3: "Required fields present, unknown
    fields rejected, enum values within their declared sets... otherwise
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/cn_school_create_missing_required_field
    """
    resp = api.create_school(
        {"school_name": "No Code School", "home_state_code": "TX"}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Corner/entities/cn_course_defaults_applied
# ---------------------------------------------------------------------------

def test_course_defaults_applied(api):
    """PRD §3.2: "Two inputs carry defaults: `max_exam_attempts`, the maximum
    number of non-`INVALIDATED` exam attempts per enrollment, defaults to 2 and
    must be at least 1; and `ce_credit_hours`, the continuing-education hours
    granted on completion, defaults to 0" and "Courses are born `DRAFT`."

    Design: Corner/entities/cn_course_defaults_applied
    """
    school = create_licensed_school()
    course = get_success_data(api.create_course(
        {"school_id": school["id"], "course_code": "PRE-101", "title": "TX Pre-Licensing",
         "course_type": "PRE_LICENSING", "required_seat_minutes": 3000,
         "tuition_cents": 50000, "pass_score_pct": 70,
         "completion_deadline_days": 30}, DIRECTOR))
    assert course["max_exam_attempts"] == 2
    assert course["ce_credit_hours"] == 0
    assert course["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner/entities/cn_computed_field_input_rejected
# ---------------------------------------------------------------------------

def test_computed_field_input_rejected(api):
    """PRD §3.4: "A new offering stands `DRAFT` with `enrolled_count` 0 and
    `seats_available` equal to `capacity`" — the server computes it — and §2.6
    rule 3: "Required fields present, unknown fields rejected... otherwise
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/cn_computed_field_input_rejected
    """
    school = create_licensed_school()
    course = create_active_course(school["id"])
    ins = create_credentialed_instructor(school["id"])
    resp = api.create_offering(
        {"course_id": course["id"], "instructor_id": ins["id"], "state_code": "TX",
         "start_date": "2026-09-01", "end_date": "2026-09-10", "capacity": 2,
         "delivery_mode": "IN_PERSON", "enrolled_count": 7}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Corner/entities/cn_system_fields_server_minted
# ---------------------------------------------------------------------------

def test_system_fields_server_minted(api):
    """PRD §2.5: "The `id` is a server-minted UUID used for identity only, with
    no type prefix... `version` is an integer starting at 1" and §2.4: "At
    server startup, before any adjustment, the clock reads exactly
    `2026-08-01T00:00:00Z`."

    Design: Corner/entities/cn_system_fields_server_minted
    """
    school = create_licensed_school()
    student = get_success_data(api.create_student(
        {"school_id": school["id"], "full_name": "Stu One", "email": "s1@x.com",
         "license_goal_state": "TX"}, REGISTRAR))
    assert is_valid_uuid(student["id"]), "server mints a prefix-free UUID"
    assert student["version"] == 1
    assert student["created_at"].startswith("2026-08-01T00:00:00"), \
        f"created_at reflects the logical clock default, got {student['created_at']}"


# ---------------------------------------------------------------------------
# Corner/entities/cn_invalid_enum_rejected
# ---------------------------------------------------------------------------

def test_invalid_enum_rejected(api):
    """PRD §2.6 rule 3: "enum values within their declared sets
    (`ERR_INVALID_ENUM`)" and §3.2: "a `course_type` of either `PRE_LICENSING`
    or `CONTINUING_ED`".

    Design: Corner/entities/cn_invalid_enum_rejected
    """
    school = create_licensed_school()
    resp = api.create_course(
        {"school_id": school["id"], "course_code": "X", "title": "Bad",
         "course_type": "SEMINAR", "required_seat_minutes": 3000,
         "tuition_cents": 50000, "pass_score_pct": 70,
         "completion_deadline_days": 30}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


# ---------------------------------------------------------------------------
# Corner/entities/cn_misc_not_found
# ---------------------------------------------------------------------------

def test_per_resource_not_found_ids(api):
    """PRD §2.6 rule 4: "Path identifiers are resolved left to right, each
    producing its resource-specific not-found error (`ERR_SCHOOL_NOT_FOUND`,
    `ERR_COURSE_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, `ERR_INSTRUCTOR_NOT_FOUND`,
    `ERR_INSTRUCTOR_APPROVAL_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_ATTENDANCE_RECORD_NOT_FOUND`, `ERR_EXAM_ATTEMPT_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`, `ERR_REFUND_REQUEST_NOT_FOUND`,
    `ERR_CREDIT_REPORT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`)".

    Design: Corner/entities/cn_misc_not_found
    """
    school = create_school()
    ins = get_success_data(api.create_instructor(
        {"school_id": school["id"], "full_name": "Ira Instructor",
         "license_number": "INS-001"}, REGISTRAR))
    instructor_headers = {"X-User-ID": ins["id"], "X-User-Role": "Instructor",
                          "Content-Type": "application/json"}
    cases = [
        (api.get_school(BADID, REGISTRAR), ApiErrorId.ERR_SCHOOL_NOT_FOUND),
        (api.get_course(BADID, REGISTRAR), ApiErrorId.ERR_COURSE_NOT_FOUND),
        (api.get_approval(BADID, REGISTRAR), ApiErrorId.ERR_APPROVAL_NOT_FOUND),
        (api.get_instructor(BADID, REGISTRAR), ApiErrorId.ERR_INSTRUCTOR_NOT_FOUND),
        (api.get_instructor_approval(BADID, REGISTRAR),
         ApiErrorId.ERR_INSTRUCTOR_APPROVAL_NOT_FOUND),
        (api.get_offering(BADID, REGISTRAR), ApiErrorId.ERR_OFFERING_NOT_FOUND),
        (api.get_student(BADID, REGISTRAR), ApiErrorId.ERR_STUDENT_NOT_FOUND),
        (api.get_enrollment(BADID, REGISTRAR), ApiErrorId.ERR_ENROLLMENT_NOT_FOUND),
        (api.void_attendance_record(BADID, instructor_headers),
         ApiErrorId.ERR_ATTENDANCE_RECORD_NOT_FOUND),
        (api.get_exam_attempt(BADID, REGISTRAR), ApiErrorId.ERR_EXAM_ATTEMPT_NOT_FOUND),
        (api.get_certificate(BADID, REGISTRAR), ApiErrorId.ERR_CERTIFICATE_NOT_FOUND),
        (api.get_refund_request(BADID, REGISTRAR),
         ApiErrorId.ERR_REFUND_REQUEST_NOT_FOUND),
        (api.get_credit_report(BADID, COMPLIANCE),
         ApiErrorId.ERR_CREDIT_REPORT_NOT_FOUND),
        (api.get_equivalency_grant(BADID, COMPLIANCE), ApiErrorId.ERR_GRANT_NOT_FOUND),
    ]
    for resp, error_id in cases:
        validate_error(resp, error_id)


# ---------------------------------------------------------------------------
# Corner/entities/cn_fk_integrity_body_reference
# ---------------------------------------------------------------------------

def test_body_fk_reference_must_exist(api):
    """PRD §2.6 rule 4: "body-supplied foreign references — `school_id`,
    `course_id`, `offering_id`, `student_id`, `instructor_id`,
    `proctor_instructor_id` — must each reference an existing entity."

    Design: Corner/entities/cn_fk_integrity_body_reference
    """
    resp = api.create_course(
        {"school_id": BADID, "course_code": "PRE-101", "title": "TX",
         "course_type": "PRE_LICENSING", "required_seat_minutes": 3000,
         "tuition_cents": 50000, "pass_score_pct": 70,
         "completion_deadline_days": 30}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_SCHOOL_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner/entities/cn_pagination_defaults_and_validation
# ---------------------------------------------------------------------------

class TestPaginationDefaultsAndValidation:
    def test_defaults_and_envelope_meta(self, api):
        """PRD §2.3: "`limit` defaults to 10 and must lie between 1 and 100, both
        inclusive; `offset` defaults to 0 and must be greater than or equal to
        0... List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object."

        Design: Corner/entities/cn_pagination_defaults_and_validation
        """
        school = create_school()
        sa = get_success_data(api.create_student(
            {"school_id": school["id"], "full_name": "Stu A", "email": "sa@x.com",
             "license_goal_state": "TX"}, REGISTRAR))
        sb = get_success_data(api.create_student(
            {"school_id": school["id"], "full_name": "Stu B", "email": "sb@x.com",
             "license_goal_state": "TX"}, REGISTRAR))
        _data, meta = validate_paginated(api.list_students(
            REGISTRAR, params={"school_id": school["id"]}))
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10 and meta["offset"] == 0

    def test_limit_offset_page_and_bounds(self, api):
        """PRD §2.3: "Values outside these bounds are rejected with
        `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400)." and "list endpoints sort
        by `created_at` ascending".

        Design: Corner/entities/cn_pagination_defaults_and_validation
        """
        school = create_school()
        sa = get_success_data(api.create_student(
            {"school_id": school["id"], "full_name": "Stu A", "email": "sa@x.com",
             "license_goal_state": "TX"}, REGISTRAR))
        sb = get_success_data(api.create_student(
            {"school_id": school["id"], "full_name": "Stu B", "email": "sb@x.com",
             "license_goal_state": "TX"}, REGISTRAR))
        page, meta = validate_paginated(api.list_students(
            REGISTRAR, params={"school_id": school["id"], "limit": 1, "offset": 1}))
        assert len(page) == 1 and page[0]["id"] == sb["id"], \
            "created_at ascending: offset 1 yields the second-created student"
        assert meta["total_count"] == 2 and meta["has_more"] is False
        validate_error(api.list_students(REGISTRAR, params={"limit": 0}),
                       ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS)
        validate_error(api.list_students(REGISTRAR, params={"limit": 101}),
                       ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS)


# ---------------------------------------------------------------------------
# Corner/entities/cn_audit_event_append_only
# ---------------------------------------------------------------------------

def test_audit_trail_records_mutations_in_order(api):
    """PRD §2.8: "Every mutating operation in the system — actor-driven or
    sweep-driven — appends an `AuditEvent`. Each event records `entity_type`...
    `actor_role` and `actor_id`... and `detail`, a payload object carrying, where
    relevant, the prior status, the new status, and an optional note." and §2.3:
    "the audit trail in particular is always returned in `created_at` ascending
    order."

    Design: Corner/entities/cn_audit_event_append_only
    """
    school = create_school()
    get_success_data(api.license_school(school["id"], COMMISSION))
    events, meta = validate_paginated(api.list_audit_events(
        REGISTRAR, params={"entity_type": "School", "entity_id": school["id"]}))
    assert meta["total_count"] == 2, "creation then licensing"
    # PRD names STATUS_CHANGE verbatim; the creation event's exact name is not
    # pinned by the PRD, so we assert its presence and the transition detail of
    # the STATUS_CHANGE event instead of a literal creation event_type.
    status_changes = [e for e in events if e["event_type"] == "STATUS_CHANGE"]
    assert len(status_changes) == 1
    status_change = status_changes[0]
    assert status_change["actor_role"] == "StateCommission"
    assert status_change["detail"]["from_status"] == "PROVISIONAL"
    assert status_change["detail"]["to_status"] == "LICENSED"


# ---------------------------------------------------------------------------
# Corner/validations/cn_existence_beats_business_rules
# ---------------------------------------------------------------------------

def test_existence_beats_business_rules(api):
    """PRD §2.6: "The evaluation order is: ... 4. **Existence.** Path identifiers
    are resolved left to right, each producing its resource-specific not-found
    error... and body-supplied foreign references ... must each reference an
    existing entity." — existence (rule 4) precedes state gates (rule 6) and
    capacity limits (rule 10).

    Design: Corner/validations/cn_existence_beats_business_rules
    """
    school = create_licensed_school()
    student = create_student(school["id"])
    resp = api.create_enrollment(
        {"offering_id": BADID, "student_id": student["id"]}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_OFFERING_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner/validations/cn_director_scope_other_school
# ---------------------------------------------------------------------------

def test_director_scope_other_school(api):
    """PRD §2.1: "a `SchoolDirector` may act only on schools whose
    `director_user_id` equals `X-User-ID`, and on resources descending from
    those schools. A scope mismatch of any flavor is rejected with
    `ERR_FORBIDDEN_SCOPE` (HTTP 403)."

    Design: Corner/validations/cn_director_scope_other_school
    """
    director_a = make_school_director_headers("dir-a")
    school = create_licensed_school(director_headers=director_a)
    resp = api.create_course(
        {"school_id": school["id"], "course_code": "PRE-101", "title": "TX",
         "course_type": "PRE_LICENSING", "required_seat_minutes": 3000,
         "tuition_cents": 50000, "pass_score_pct": 70,
         "completion_deadline_days": 30},
        make_school_director_headers("dir-b"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SCOPE)


# ---------------------------------------------------------------------------
# Corner/validations/cn_student_self_scope_and_default
# ---------------------------------------------------------------------------

class TestStudentSelfScopeAndDefault:
    def _published_with_two_students(self, api):
        env = setup_publishable_school(capacity=5)
        sa = create_student(env["school"]["id"])
        sb = create_student(env["school"]["id"])
        return env, sa, sb

    def test_self_enroll_defaults_student_id(self, api):
        """PRD §3.5: "For a `Student` caller, `student_id` defaults to the
        caller's `X-User-ID`".

        Design: Corner/validations/cn_student_self_scope_and_default
        """
        env, sa, _sb = self._published_with_two_students(api)
        enr = get_success_data(api.create_enrollment(
            {"offering_id": env["offering"]["id"]}, make_student_headers(sa["id"])))
        assert enr["student_id"] == sa["id"], "student_id defaulted to the caller"

    def test_student_cannot_enroll_or_read_another(self, api):
        """PRD §3.5: "when supplied it must equal it — self-service may not
        enroll others" and §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is
        the `id` of the acting `Student`; ownership checks compare a resource's
        student reference to `X-User-ID`... A scope mismatch of any flavor is
        rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403)."

        Design: Corner/validations/cn_student_self_scope_and_default
        """
        env, sa, sb = self._published_with_two_students(api)
        enr = get_success_data(api.create_enrollment(
            {"offering_id": env["offering"]["id"]}, make_student_headers(sa["id"])))
        resp = api.create_enrollment(
            {"offering_id": env["offering"]["id"], "student_id": sb["id"]},
            make_student_headers(sa["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SCOPE)
        resp2 = api.get_student(sb["id"], make_student_headers(sa["id"]))
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_SCOPE)
        own = get_success_data(api.get_enrollment(enr["id"], make_student_headers(sa["id"])))
        assert own["id"] == enr["id"], "reading own enrollment succeeds"


# ---------------------------------------------------------------------------
# Corner/validations/cn_grant_same_state_rejected
# ---------------------------------------------------------------------------

def test_grant_same_state_rejected(api):
    """PRD §3.2: "The two states must differ (`ERR_GRANT_SAME_STATE`)".

    Design: Corner/validations/cn_grant_same_state_rejected
    """
    school = create_licensed_school()
    course = create_active_course(school["id"])
    resp = api.create_equivalency_grant(
        {"course_id": course["id"], "home_state_code": "TX",
         "recognized_state_code": "TX", "expected_course_version": course["version"]},
        COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_GRANT_SAME_STATE)


# ---------------------------------------------------------------------------
# Corner/validations/cn_approval_singleton_per_state
# ---------------------------------------------------------------------------

def test_approval_singleton_per_state(api):
    """PRD §3.2: "only one application may exist per course-and-state pair, a
    duplicate drawing `ERR_APPROVAL_ALREADY_EXISTS`".

    Design: Corner/validations/cn_approval_singleton_per_state
    """
    school = create_licensed_school()
    course = create_course(school["id"])
    get_success_data(api.create_course_approval(course["id"], {"state_code": "TX"},
                                                COMPLIANCE))
    resp = api.create_course_approval(course["id"], {"state_code": "TX"}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_APPROVAL_ALREADY_EXISTS)


# ---------------------------------------------------------------------------
# Corner/validations/cn_uniqueness_duplicates
# ---------------------------------------------------------------------------

def test_uniqueness_duplicates(api):
    """PRD §3.1: "The `school_code` must be globally unique across all schools...
    and a duplicate is rejected with `ERR_DUPLICATE_SCHOOL_CODE`." PRD §3.2:
    "Each course carries a `course_code` unique within its school (duplicates
    rejected with `ERR_DUPLICATE_COURSE_CODE`)". PRD §3.5: "an `email` unique
    within the school case-insensitively (`ERR_DUPLICATE_STUDENT_EMAIL`)". PRD
    §3.3: "the state-issued `license_number`, which must be unique within the
    school — duplicates are rejected with `ERR_DUPLICATE_INSTRUCTOR_LICENSE`."

    Design: Corner/validations/cn_uniqueness_duplicates
    """
    school = create_licensed_school(school_code="LSRS")
    create_course(school["id"], course_code="PRE-101")
    create_student(school["id"], email="sa@x.com")
    create_credentialed_instructor(school["id"], license_number="INS-001")
    e1 = api.create_school(
        {"school_name": "Other School", "school_code": "LSRS", "home_state_code": "TX"},
        DIRECTOR)
    validate_error(e1, ApiErrorId.ERR_DUPLICATE_SCHOOL_CODE)
    e2 = api.create_course(
        {"school_id": school["id"], "course_code": "PRE-101", "title": "Dup",
         "course_type": "PRE_LICENSING", "required_seat_minutes": 100,
         "tuition_cents": 100, "pass_score_pct": 70, "completion_deadline_days": 10},
        DIRECTOR)
    validate_error(e2, ApiErrorId.ERR_DUPLICATE_COURSE_CODE)
    e3 = api.create_student(
        {"school_id": school["id"], "full_name": "Stu A2", "email": "SA@X.COM",
         "license_goal_state": "TX"}, REGISTRAR)
    validate_error(e3, ApiErrorId.ERR_DUPLICATE_STUDENT_EMAIL)
    e4 = api.create_instructor(
        {"school_id": school["id"], "full_name": "Ira Two", "license_number": "INS-001"},
        REGISTRAR)
    validate_error(e4, ApiErrorId.ERR_DUPLICATE_INSTRUCTOR_LICENSE)


# ---------------------------------------------------------------------------
# Corner/validations/cn_late_renewal_window_closed
# ---------------------------------------------------------------------------

def test_late_renewal_window_closed(api):
    """PRD §3.2: "Renewal is available from either state: from `EXPIRING` at any
    time, and from `EXPIRED` only as a late renewal within 30 days after
    `valid_until` — past that window the attempt fails with
    `ERR_APPROVAL_RENEWAL_WINDOW_CLOSED`."

    Design: Corner/validations/cn_late_renewal_window_closed
    """
    school = create_licensed_school()
    course = create_course(school["id"])
    approval = approve_course(course["id"], valid_until="2026-09-30")
    # Walk the approval APPROVED -> EXPIRING -> EXPIRED, one hop per sweep run
    # (PRD §2.4: "Each entity advances at most one state hop per sweep run").
    set_clock("2026-09-15T00:00:00Z")
    run_sweep()  # within the 30-day runway: APPROVED -> EXPIRING
    set_clock("2026-10-01T00:00:00Z")
    run_sweep()  # past valid_until: EXPIRING -> EXPIRED
    after = get_success_data(api.get_approval(approval["id"], REGISTRAR))
    assert after["status"] == "EXPIRED"
    set_clock("2026-10-31T00:00:00Z")  # 31 days past valid_until
    resp = api.renew_approval(approval["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_APPROVAL_RENEWAL_WINDOW_CLOSED)


# ---------------------------------------------------------------------------
# Corner/validations/cn_decide_invalid_validity_window
# ---------------------------------------------------------------------------

class TestDecideInvalidValidityWindow:
    def _pending_approval(self, api):
        school = create_licensed_school()
        course = create_course(school["id"])
        return get_success_data(api.create_course_approval(
            course["id"], {"state_code": "TX"}, COMPLIANCE))

    def test_missing_validity_dates_rejected(self, api):
        """PRD §3.2: "An approval decision requires the payload's `valid_from`
        and `valid_until` calendar dates with `valid_until` no earlier than
        `valid_from`; missing or inverted windows are rejected with
        `ERR_INVALID_VALIDITY_WINDOW`."

        Design: Corner/validations/cn_decide_invalid_validity_window
        """
        approval = self._pending_approval(api)
        resp = api.decide_approval(approval["id"], {"decision": "APPROVED"}, COMMISSION)
        validate_error(resp, ApiErrorId.ERR_INVALID_VALIDITY_WINDOW)

    def test_inverted_window_rejected_and_state_unchanged(self, api):
        """PRD §3.2: "An approval decision requires the payload's `valid_from`
        and `valid_until` calendar dates with `valid_until` no earlier than
        `valid_from`; missing or inverted windows are rejected with
        `ERR_INVALID_VALIDITY_WINDOW`."

        Design: Corner/validations/cn_decide_invalid_validity_window
        """
        approval = self._pending_approval(api)
        resp = api.decide_approval(
            approval["id"],
            {"decision": "APPROVED", "valid_from": "2027-01-01",
             "valid_until": "2026-06-01"},
            COMMISSION)
        validate_error(resp, ApiErrorId.ERR_INVALID_VALIDITY_WINDOW)
        after = get_success_data(api.get_approval(approval["id"], REGISTRAR))
        assert after["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner/validations/cn_attendance_window_and_minutes
# ---------------------------------------------------------------------------

class TestAttendanceWindowAndMinutes:
    def test_session_outside_offering_window_rejected(self, api):
        """PRD §3.6: "Each `AttendanceRecord` carries a `session_date`, which
        must lie within the offering's window from `start_date` through
        `end_date` inclusive (`ERR_ATTENDANCE_OUT_OF_WINDOW`)".

        Design: Corner/validations/cn_attendance_window_and_minutes
        """
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        resp = api.create_attendance_record(
            enr["id"], {"session_date": "2026-08-20", "minutes": 60},
            {"X-User-ID": env["instructor"]["id"], "X-User-Role": "Instructor",
             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_ATTENDANCE_OUT_OF_WINDOW)

    def test_minutes_outside_range_rejected(self, api):
        """PRD §3.6: "`minutes` attended, between 1 and 1440 inclusive
        (`ERR_ATTENDANCE_MINUTES_INVALID`)".

        Design: Corner/validations/cn_attendance_window_and_minutes
        """
        import pytest
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        headers = {"X-User-ID": env["instructor"]["id"], "X-User-Role": "Instructor",
                   "Content-Type": "application/json"}
        for bad_minutes in (0, 1441):
            resp = api.create_attendance_record(
                enr["id"], {"session_date": "2026-09-03", "minutes": bad_minutes},
                headers)
            validate_error(resp, ApiErrorId.ERR_ATTENDANCE_MINUTES_INVALID)
        assert get_success_data(api.get_enrollment(enr["id"], REGISTRAR))[
            "verified_seat_minutes"] == 0, "no record persisted"


# ---------------------------------------------------------------------------
# Corner/validations/cn_report_period_overlap_closed_interval
# ---------------------------------------------------------------------------

class TestReportPeriodOverlapClosedInterval:
    def test_adjacent_periods_conflict(self, api):
        """PRD §3.8: "Base reports of one school must not overlap: any other base
        report whose closed period intersects the new one, touching endpoints
        included — one report's `period_end` exactly equal to another's
        `period_start` is already a conflict — is rejected with
        `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Corner/validations/cn_report_period_overlap_closed_interval
        """
        school = create_licensed_school()
        create_report(school["id"], "2026-09-01", "2026-09-30")
        resp = api.create_credit_report(
            {"school_id": school["id"], "period_start": "2026-09-30",
             "period_end": "2026-10-31"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

    def test_disjoint_period_allowed(self, api):
        """PRD §3.8: "Base reports of one school must not overlap: any other base
        report whose closed period intersects the new one, touching endpoints
        included — one report's `period_end` exactly equal to another's
        `period_start` is already a conflict". A period starting the day after
        the previous `period_end` is disjoint and allowed; "Reports are born
        `DRAFT`."

        Design: Corner/validations/cn_report_period_overlap_closed_interval
        """
        school = create_licensed_school()
        create_report(school["id"], "2026-09-01", "2026-09-30")
        resp = api.create_credit_report(
            {"school_id": school["id"], "period_start": "2026-09-30",
             "period_end": "2026-10-31"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)
        created = get_success_data(api.create_credit_report(
            {"school_id": school["id"], "period_start": "2026-10-01",
             "period_end": "2026-10-31"}, COMPLIANCE))
        assert created["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner/validations/cn_report_window_invalid
# ---------------------------------------------------------------------------

def test_report_window_invalid(api):
    """PRD §3.8: "A base report is created for a school with a `period_start`
    and `period_end` — the end must not precede the start
    (`ERR_REPORT_WINDOW_INVALID`)".

    Design: Corner/validations/cn_report_window_invalid
    """
    school = create_licensed_school()
    resp = api.create_credit_report(
        {"school_id": school["id"], "period_start": "2026-09-30",
         "period_end": "2026-09-01"}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_REPORT_WINDOW_INVALID)


# ---------------------------------------------------------------------------
# Corner/validations/cn_payment_amount_must_equal_charge_total
# ---------------------------------------------------------------------------

class TestPaymentAmountMustEqualChargeTotal:
    def test_overpayment_by_one_cent_rejected(self, api):
        """PRD §3.5: "Payment capture is exact-amount only: the request's
        `amount_cents` must equal the pinned `charge_total_cents`, with any
        difference rejected as `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/cn_payment_amount_must_equal_charge_total
        """
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        assert enr["charge_total_cents"] == 51500
        resp = api.pay_enrollment(enr["id"], {"amount_cents": 51501}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

    def test_exact_amount_succeeds(self, api):
        """PRD §3.5: "A successful capture moves `payment_status` from `PENDING`
        to `PAID` and sets `paid_cents` to `amount_cents`."

        Design: Corner/validations/cn_payment_amount_must_equal_charge_total
        """
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        validate_error(api.pay_enrollment(enr["id"], {"amount_cents": 51501}, REGISTRAR),
                       ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
        paid = get_success_data(api.pay_enrollment(enr["id"], {"amount_cents": 51500},
                                                   REGISTRAR))
        assert paid["payment_status"] == "PAID"
        assert paid["paid_cents"] == 51500


# ---------------------------------------------------------------------------
# Corner/validations/cn_withdrawal_reason_school_cancelled_rejected
# ---------------------------------------------------------------------------

class TestWithdrawalReasonSchoolCancelledRejected:
    def test_manual_school_cancelled_reason_rejected(self, api):
        """PRD §3.5: "The supplied `reason` must be `VOLUNTARY` or
        `ADMINISTRATIVE` — the third value, `SCHOOL_CANCELLED`, is produced only
        by the offering-cancellation cascade and is rejected on manual withdrawal
        with `ERR_WITHDRAWAL_REASON_INVALID` (HTTP 400)."

        Design: Corner/validations/cn_withdrawal_reason_school_cancelled_rejected
        """
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        resp = api.withdraw_enrollment(enr["id"], {"reason": "SCHOOL_CANCELLED"}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_REASON_INVALID)

    def test_voluntary_then_voids_pending_payment(self, api):
        """PRD §3.5: "If `payment_status` is still `PENDING`, it flips to
        `VOIDED` and no refund request is created."

        Design: Corner/validations/cn_withdrawal_reason_school_cancelled_rejected
        """
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        validate_error(api.withdraw_enrollment(enr["id"], {"reason": "SCHOOL_CANCELLED"},
                                               REGISTRAR),
                       ApiErrorId.ERR_WITHDRAWAL_REASON_INVALID)
        withdrawn = get_success_data(api.withdraw_enrollment(
            enr["id"], {"reason": "VOLUNTARY"}, REGISTRAR))
        assert withdrawn["academic_status"] == "WITHDRAWN"
        assert withdrawn["payment_status"] == "VOIDED"


# ---------------------------------------------------------------------------
# Corner/validations/cn_school_lifecycle_gates_course_creation
# ---------------------------------------------------------------------------

def test_school_lifecycle_gates_course_creation(api):
    """PRD §3.1: "Only a `LICENSED` school may create courses or publish
    offerings — attempts against a `PROVISIONAL` or `SUSPENDED` school are
    rejected with `ERR_SCHOOL_NOT_LICENSED`".

    Design: Corner/validations/cn_school_lifecycle_gates_course_creation
    """
    school = create_school()  # PROVISIONAL, never licensed
    resp = api.create_course(
        {"school_id": school["id"], "course_code": "PRE-101", "title": "TX",
         "course_type": "PRE_LICENSING", "required_seat_minutes": 3000,
         "tuition_cents": 50000, "pass_score_pct": 70,
         "completion_deadline_days": 30}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_SCHOOL_NOT_LICENSED)


# ---------------------------------------------------------------------------
# Corner/validations/cn_course_activation_and_retire_guards
# ---------------------------------------------------------------------------

class TestCourseActivationAndRetireGuards:
    def test_activate_without_approved_approval_rejected(self, api):
        """PRD §3.2: "Before a course can activate, at least one of its approval
        applications must stand `APPROVED`; activation without one fails with
        `ERR_COURSE_NOT_APPROVED_ANYWHERE`."

        Design: Corner/validations/cn_course_activation_and_retire_guards
        """
        school = create_licensed_school()
        course = create_course(school["id"], course_code="C1")
        get_success_data(api.create_course_approval(course["id"], {"state_code": "TX"},
                                                    COMPLIANCE))
        resp = api.activate_course(course["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_APPROVED_ANYWHERE)

    def test_offering_create_on_draft_course_rejected(self, api):
        """PRD §3.4: "Creating the course's offering also enforces the
        instructor's rest-day rule (see below) and requires the course to be
        `ACTIVE` (`ERR_COURSE_NOT_ACTIVE`)."

        Design: Corner/validations/cn_course_activation_and_retire_guards
        """
        school = create_licensed_school()
        draft_course = create_course(school["id"], course_code="C1")
        ins = create_credentialed_instructor(school["id"])
        resp = api.create_offering(
            {"course_id": draft_course["id"], "instructor_id": ins["id"],
             "state_code": "TX", "start_date": "2026-10-01", "end_date": "2026-10-05",
             "capacity": 2, "delivery_mode": "IN_PERSON"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_ACTIVE)

    def test_retire_with_open_offering_rejected(self, api):
        """PRD §3.2: "Retirement moves `ACTIVE` to the terminal `RETIRED`, but
        only when no offering of the course remains in `DRAFT`, `PUBLISHED`, or
        `IN_SESSION` — otherwise `ERR_COURSE_HAS_OPEN_OFFERINGS`."

        Design: Corner/validations/cn_course_activation_and_retire_guards
        """
        school = create_licensed_school()
        course = create_active_course(school["id"], course_code="C2")
        ins = create_credentialed_instructor(school["id"])
        create_offering(course["id"], ins["id"])  # DRAFT offering still open
        resp = api.retire_course(course["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_COURSE_HAS_OPEN_OFFERINGS)


# ---------------------------------------------------------------------------
# Corner/validations/cn_capacity_below_enrolled_on_update
# ---------------------------------------------------------------------------

def test_capacity_below_enrolled_on_update(api):
    """PRD §3.4: "the new capacity may not fall below the offering's current
    `enrolled_count` (`ERR_CAPACITY_BELOW_ENROLLED`)".

    Design: Corner/validations/cn_capacity_below_enrolled_on_update
    """
    env = setup_publishable_school()
    enroll(env["offering"]["id"], env["school"]["id"])
    enroll(env["offering"]["id"], env["school"]["id"])
    offering = get_success_data(api.get_offering(env["offering"]["id"], REGISTRAR))
    resp = api.update_offering(
        env["offering"]["id"],
        {"capacity": 1, "expected_offering_version": offering["version"]},
        DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_BELOW_ENROLLED)
    after = get_success_data(api.get_offering(env["offering"]["id"], REGISTRAR))
    assert after["capacity"] == 2


# ---------------------------------------------------------------------------
# Corner/validations/cn_grant_requires_source_approval_approved
# ---------------------------------------------------------------------------

def test_grant_requires_source_approval_approved(api):
    """PRD §3.2: "the course's approval in the home state must stand `APPROVED`
    (`ERR_SOURCE_APPROVAL_NOT_APPROVED`)".

    Design: Corner/validations/cn_grant_requires_source_approval_approved
    """
    school = create_licensed_school()
    course = create_course(school["id"])
    get_success_data(api.create_course_approval(course["id"], {"state_code": "TX"},
                                                COMPLIANCE))  # stays PENDING
    resp = api.create_equivalency_grant(
        {"course_id": course["id"], "home_state_code": "TX",
         "recognized_state_code": "NM", "expected_course_version": course["version"]},
        COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_SOURCE_APPROVAL_NOT_APPROVED)


# ---------------------------------------------------------------------------
# Corner/validations/cn_report_state_errors
# ---------------------------------------------------------------------------

class TestReportStateErrors:
    def _two_reports_one_submitted(self, api):
        school = create_licensed_school()
        r1 = create_report(school["id"], "2026-09-01", "2026-09-30")
        r2 = create_report(school["id"], "2026-10-01", "2026-10-31")
        get_success_data(api.submit_credit_report(r1["id"], COMPLIANCE))
        return r1, r2

    def test_double_submit_rejected(self, api):
        """PRD §3.8: "Every state-gated step on this cycle — submit requiring
        `DRAFT`, acknowledge and reject requiring `SUBMITTED`, revise requiring
        `REJECTED`, and amendments requiring `ACKNOWLEDGED` — rejects
        out-of-state calls with `ERR_REPORT_STATE_INVALID`."

        Design: Corner/validations/cn_report_state_errors
        """
        r1, _r2 = self._two_reports_one_submitted(api)
        resp = api.submit_credit_report(r1["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_REPORT_STATE_INVALID)

    def test_acknowledge_from_draft_and_amendment_on_draft_rejected(self, api):
        """PRD §3.8: "Every state-gated step on this cycle — submit requiring
        `DRAFT`, acknowledge and reject requiring `SUBMITTED`, revise requiring
        `REJECTED`, and amendments requiring `ACKNOWLEDGED` — rejects
        out-of-state calls with `ERR_REPORT_STATE_INVALID`."

        Design: Corner/validations/cn_report_state_errors
        """
        _r1, r2 = self._two_reports_one_submitted(api)
        resp = api.acknowledge_credit_report(r2["id"], COMMISSION)
        validate_error(resp, ApiErrorId.ERR_REPORT_STATE_INVALID)
        resp2 = api.create_credit_report_amendment(
            r2["id"], {"reason": "premature",
                       "expected_credit_report_version": r2["version"]}, COMPLIANCE)
        validate_error(resp2, ApiErrorId.ERR_REPORT_STATE_INVALID)
