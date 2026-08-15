"""SEVIS record creation/initialization and term-enrollment registration
claims (PRD §3.2, §3.3)."""
from test_helpers import (
    ALT_STUDENT,
    ApiErrorId,
    assert_sevis_record,
    assert_term_enrollment,
    create_i20_form,
    create_sevis_record,
    create_student,
    create_term_enrollment,
    get_enrollment,
    get_record,
    get_student,
    initialize_record,
    issue_i20_form,
    register_enrollment,
    set_clock,
    setup_active_student,
    setup_initialized_student,
    setup_student_with_draft_i20,
    setup_student_with_draft_record,
    submit_verified_document,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_sevis_record_second_create_returns_409(api, dso_headers):
    """PRD §3.2: "the record lands in `DRAFT` status, and a second creation
    attempt for the same student is rejected with `ERR_RECORD_ALREADY_EXISTS`."

    Design: Corner/entities/sevis_record_second_create_returns_409
    """
    ctx = setup_student_with_draft_record()
    resp = api.create_sevis_record(
        ctx["student"]["id"],
        {"program_start_date": "2026-08-24", "program_end_date": "2027-05-31"},
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RECORD_ALREADY_EXISTS, 409)


def test_initialize_without_issued_i20_returns_no_issued_i20(api, dso_headers):
    """PRD §3.2: "Initialization on a record not in `DRAFT` is rejected with
    `ERR_RECORD_NOT_DRAFT`; initialization without any `ISSUED` form for the
    record is rejected with `ERR_NO_ISSUED_I20`."

    Design: Corner/state_machines/initialize_without_issued_i20_returns_no_issued_i20
    """
    ctx = setup_student_with_draft_i20()  # I-20 drafted but never issued
    resp = api.initialize_sevis_record(ctx["record"]["id"], dso_headers)
    validate_error(resp, ApiErrorId.ERR_NO_ISSUED_I20, 409)
    assert get_record(ctx["student"]["id"])["status"] == "DRAFT"


def test_initialize_twice_returns_record_not_draft(api, dso_headers):
    """PRD §3.2: "Initialization on a record not in `DRAFT` is rejected with
    `ERR_RECORD_NOT_DRAFT`; initialization without any `ISSUED` form for the
    record is rejected with `ERR_NO_ISSUED_I20`."

    Design: Corner/state_machines/initialize_twice_returns_record_not_draft
    """
    ctx = setup_initialized_student()
    assert ctx["record"]["status"] == "INITIAL"
    resp = api.initialize_sevis_record(ctx["record"]["id"], dso_headers)
    validate_error(resp, ApiErrorId.ERR_RECORD_NOT_DRAFT, 409)


def test_enrollment_duplicate_term_returns_409(api, dso_headers):
    """PRD §3.3: "One enrollment may exist per (`student_id`, `term_code`)
    pair; a duplicate is rejected with `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/entities/enrollment_duplicate_term_returns_409
    """
    student = create_student()
    create_term_enrollment(student["id"])
    resp = api.create_term_enrollment(
        {
            "student_id": student["id"],
            "term_code": "2026-FALL",
            "term_start_date": "2026-08-24",
            "term_end_date": "2026-12-11",
            "enrolled_credits": 9,
        },
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT, 409)


def test_enrollment_inverted_dates_returns_invalid_request(api, dso_headers):
    """PRD §3.3: "A DSO creates one with the `student_id`, a `term_code` such
    as `2026-FALL`, the `term_start_date`, the `term_end_date` (which must be
    later than the start), and the `enrolled_credits` (zero or greater)."
    PRD §2.9: "Malformed request bodies — a missing required field, a type
    mismatch, an invalid enum value, or a malformed date — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/enrollment_inverted_dates_returns_invalid_request
    """
    student = create_student()
    resp = api.create_term_enrollment(
        {
            "student_id": student["id"],
            "term_code": "2026-FALL",
            "term_start_date": "2026-12-11",
            "term_end_date": "2026-08-24",
            "enrolled_credits": 12,
        },
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_register_after_deadline_on_late_created_enrollment(api, dso_headers):
    """PRD §3.3: "Registration requires the enrollment still `PENDING`
    (otherwise `ERR_ENROLLMENT_NOT_REGISTERABLE`), the student's record in
    `INITIAL` or `ACTIVE` (otherwise `ERR_RECORD_NOT_ACTIVE`), the
    `enrolled_credits` at or above the `effective_min_credits` floor — meeting
    the floor exactly counts as full-time (otherwise
    `ERR_BELOW_FULL_COURSE_LOAD`, HTTP 422) — and the clock date no later than
    30 days after `term_start_date` (otherwise
    `ERR_REGISTRATION_DEADLINE_PASSED`)."
    PRD §3.3: "New enrollments land in `PENDING`."

    Design: Corner/validations/register_after_deadline_on_late_created_enrollment_returns_deadline_passed
    """
    ctx = setup_initialized_student()
    # Advance past the registration deadline (term_start 2026-08-24 + 30 days),
    # then create the enrollment: created after the sweep, it stays PENDING.
    set_clock("2026-09-24T00:00:00Z")
    enrollment = create_term_enrollment(ctx["student"]["id"])
    assert enrollment["status"] == "PENDING"
    resp = api.register_term_enrollment(enrollment["id"], dso_headers)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_DEADLINE_PASSED, 409)


class TestRegisterGatedByRecordState:
    """Cross-entity gate: registration requires the record INITIAL/ACTIVE."""

    def test_register_rejected_while_record_draft(self, api, dso_headers):
        """PRD §3.3: "Registration requires the enrollment still `PENDING`
        (otherwise `ERR_ENROLLMENT_NOT_REGISTERABLE`), the student's record in
        `INITIAL` or `ACTIVE` (otherwise `ERR_RECORD_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/register_gated_by_record_state
        """
        ctx = setup_student_with_draft_record()
        enrollment = create_term_enrollment(ctx["student"]["id"])
        resp = api.register_term_enrollment(enrollment["id"], dso_headers)
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_ACTIVE, 409)
        assert get_enrollment(enrollment["id"])["status"] == "PENDING"

    def test_first_registration_activates_record(self, api, dso_headers):
        """PRD §3.3: "The first successful registration for a student also
        flips their SEVIS record from `INITIAL` to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/register_gated_by_record_state
        """
        ctx = setup_student_with_draft_record()
        student_id = ctx["student"]["id"]
        enrollment = create_term_enrollment(student_id)
        # Fund, issue the I-20, and initialize: record reaches INITIAL.
        submit_verified_document(student_id)
        i20 = create_i20_form(student_id, ctx["record"]["id"])
        issue_i20_form(i20["id"])
        initialize_record(ctx["record"]["id"])

        registered = register_enrollment(enrollment["id"])
        assert_term_enrollment(registered)
        assert registered["status"] == "REGISTERED"
        record = get_record(student_id)
        assert_sevis_record(record)
        assert record["status"] == "ACTIVE"


class TestRegisterFullTimeBoundary:
    """Credit-count boundary at registration: 12 passes, 11 fails (UG)."""

    def test_register_at_exactly_12_credits_succeeds(self, api, dso_headers):
        """PRD §3.3: "the `enrolled_credits` at or above the
        `effective_min_credits` floor — meeting the floor exactly counts as
        full-time (otherwise `ERR_BELOW_FULL_COURSE_LOAD`, HTTP 422)".
        PRD §3.3: "With no approved reduced course load, the floor is 12
        credits for an `UNDERGRADUATE` student and 9 credits for a `GRADUATE`
        student."

        Design: Difficulty/boundary_precision_check/register_full_time_12_passes_11_fails
        """
        ctx = setup_active_student(enrolled_credits=12, register=False)
        enrollment = ctx["enrollment"]
        assert enrollment["effective_min_credits"] == 12
        registered = register_enrollment(enrollment["id"])
        assert registered["status"] == "REGISTERED"

    def test_register_at_11_credits_rejected(self, api, dso_headers):
        """PRD §3.3: "the `enrolled_credits` at or above the
        `effective_min_credits` floor — meeting the floor exactly counts as
        full-time (otherwise `ERR_BELOW_FULL_COURSE_LOAD`, HTTP 422)".

        Design: Difficulty/boundary_precision_check/register_full_time_12_passes_11_fails
        """
        ctx = setup_active_student(enrolled_credits=11, register=False)
        resp = api.register_term_enrollment(ctx["enrollment"]["id"], dso_headers)
        validate_error(resp, ApiErrorId.ERR_BELOW_FULL_COURSE_LOAD, 422)
        assert get_enrollment(ctx["enrollment"]["id"])["status"] == "PENDING"


class TestDeadlineSweepEnrollmentViolationPosture:
    """Clock-sweep cascade: PENDING -> NOT_ENROLLED -> FAILURE_TO_ENROLL ->
    VIOLATION_OPEN."""

    def test_deadline_sweep_flips_enrollment_and_opens_violation(self, api, dso_headers):
        """PRD §3.3: "An enrollment still `PENDING` when the clock passes 30
        days after `term_start_date` flips to `NOT_ENROLLED`, and the sweep
        simultaneously opens a `FAILURE_TO_ENROLL` violation in `OPEN` status
        for the student — which in turn recomputes the student's
        `compliance_posture` to `VIOLATION_OPEN`."

        Design: Difficulty/transitive_cascade/deadline_sweep_enrollment_violation_posture
        """
        ctx = setup_active_student(register=False)  # INITIAL record, PENDING enrollment
        enrollment_id = ctx["enrollment"]["id"]
        # term_start 2026-08-24 + 30 days = 2026-09-23; clock lands past it.
        set_clock("2026-09-24T00:00:00Z")

        enrollment = get_enrollment(enrollment_id)
        assert enrollment["status"] == "NOT_ENROLLED"

        violations, meta = validate_paginated(
            api.list_status_violations(ctx["student"]["id"], dso_headers)
        )
        assert meta["total_count"] == 1
        assert violations[0]["violation_type"] == "FAILURE_TO_ENROLL"
        assert violations[0]["status"] == "OPEN"

    def test_deadline_sweep_drives_posture_violation_open(self, api, dso_headers):
        """PRD §3.3: "An enrollment still `PENDING` when the clock passes 30
        days after `term_start_date` flips to `NOT_ENROLLED`, and the sweep
        simultaneously opens a `FAILURE_TO_ENROLL` violation in `OPEN` status
        for the student — which in turn recomputes the student's
        `compliance_posture` to `VIOLATION_OPEN`."
        PRD §2.10: "If any of the student's violations is in `OPEN` or
        `REINSTATEMENT_PENDING` status, the posture is `VIOLATION_OPEN`."

        Design: Difficulty/transitive_cascade/deadline_sweep_enrollment_violation_posture
        """
        ctx = setup_active_student(register=False)
        assert ctx["student"]["compliance_posture"] == "CLEAR"
        set_clock("2026-09-24T00:00:00Z")
        student = get_student(ctx["student"]["id"])
        assert student["compliance_posture"] == "VIOLATION_OPEN"
