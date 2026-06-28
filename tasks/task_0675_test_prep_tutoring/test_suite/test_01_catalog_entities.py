"""Corner tests for entity CRUD, validation, and field semantics (section: entities)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, make_student_headers, make_instructor_headers, TEST_USERS,
    create_course_payload, create_cohort_payload,
    assert_course, assert_practice_attempt_has_no_version,
    setup_active_enrollment,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ANON = TEST_USERS["anonymous_headers"]
MISSING_UUID = "00000000-0000-4000-8000-000000000000"


class TestCourseCreation:
    def test_create_course_returns_201_draft_with_fields(self, api):
        """PRD §3.1: "A course's status begins at DRAFT on creation."
        PRD §2.4: "The version field is an integer that begins at its initial value and
        increments by one on every mutation to the resource".

        Design: Corner/entities/create_course_returns_201_draft_with_all_fields
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        data = validate_success(api.create_course(
            create_course_payload(exam_type="MCAT", format="ONLINE", title="MCAT Online",
                                  list_price_cents=250000, baseline_scale_max=528,
                                  guarantee_min_delta=10, required_practice_tests=3,
                                  required_attendance_pct=0.7, materials_access_days=180),
            REGISTRAR), expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert data["baseline_scale_max"] == 528
        assert_course(data)

    def test_get_course_not_found_returns_404(self, api):
        """PRD §2.5: "The first identifier in the path that does not resolve to an existing
        resource causes the request to be rejected with ERR_NOT_FOUND."

        Design: Corner/entities/get_course_not_found_returns_404
        """
        resp = api.get_course(MISSING_UUID, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_course_missing_required_field(self, api):
        """PRD §3.3: "it confirms the body is well-formed and its enums and ranges are valid,
        failing otherwise with ERR_INVALID_REQUEST."
        PRD §3.1: "The baseline_scale_max field records the maximum number of points on this
        exam's scale ... and must be strictly greater than zero".

        Omitting baseline_scale_max (required, no default) -> ERR_INVALID_REQUEST.

        Design: Corner/entities/create_course_missing_required_field_returns_invalid_request
        """
        resp = api.create_course(
            {"exam_type": "LSAT", "format": "LIVE", "title": "LSAT",
             "list_price_cents": 90000, "guarantee_min_delta": 7,
             "required_practice_tests": 2, "required_attendance_pct": 0.8,
             "materials_access_days": 60}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_course_invalid_enum_exam_type(self, api):
        """PRD §3.1: "A course names its exam_type — one of SAT, ACT, MCAT, or LSAT".

        exam_type GMAT (outside the allowed set) -> ERR_INVALID_REQUEST.

        Design: Corner/entities/create_course_invalid_enum_exam_type_returns_invalid_request
        """
        resp = api.create_course(
            {"exam_type": "GMAT", "format": "LIVE", "title": "X", "list_price_cents": 90000,
             "baseline_scale_max": 800, "guarantee_min_delta": 50,
             "required_practice_tests": 2, "required_attendance_pct": 0.8,
             "materials_access_days": 60}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCohortCreationValidation:
    def test_cohort_ends_before_starts_rejected(self, api):
        """PRD §3.1: "the session window's starts_at (inclusive) and ends_at (exclusive,
        and required to be strictly after starts_at)".

        ends_at before starts_at -> ERR_INVALID_REQUEST.

        Design: Corner/entities/cohort_ends_before_starts_returns_invalid_request
        """
        course = get_success_data(api.create_course(create_course_payload(), REGISTRAR))
        get_success_data(api.publish_course(course["id"], REGISTRAR))
        resp = api.create_cohort(
            create_cohort_payload(course["id"], seat_capacity=5,
                                  starts_at="2026-06-30T00:00:00Z",
                                  ends_at="2026-06-01T00:00:00Z", total_sessions=4),
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_cohort_wrong_parent_course_not_found(self, api):
        """PRD §2.5: "Body foreign keys are resolved after path identifiers, also in
        declaration order; any unresolved reference likewise yields ERR_NOT_FOUND."

        Design: Corner/entities/cohort_create_wrong_parent_course_not_found
        """
        resp = api.create_cohort(
            create_cohort_payload("00000000-0000-4000-8000-000000000999",
                                  seat_capacity=5, total_sessions=4),
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPracticeAttemptImmutability:
    def test_practice_attempt_has_no_version_field(self, api):
        """PRD §2.4: "A PracticeAttempt is the one exception: it carries only id and
        created_at. A practice attempt has no updated_at and no version field — ... and
        clients must not expect either field on it."

        Design: Corner/entities/practice_attempt_immutable_no_version_field
        """
        base = setup_active_enrollment(fmt="SELF", student_email="imm@x.com")
        att = get_success_data(api.create_practice_attempt(
            {"enrollment_id": base["enrollment"]["id"], "attempt_type": "PRACTICE",
             "raw_correct": 400, "total_items": 800},
            make_student_headers(base["student"]["id"])))
        data = validate_success(api.get_practice_attempt(
            att["id"], make_instructor_headers(base["instructor"]["id"])))
        assert data["status"] == "STARTED"
        assert_practice_attempt_has_no_version(data)


class TestStudentRegistration:
    def test_diagnostic_score_starts_null(self, api):
        """PRD §3.3: "A new student's diagnostic_score is null and stays null until the
        student's first diagnostic practice test is scored (see §3.5)."

        Design: Corner/entities/student_diagnostic_score_is_system_computed_not_input
        """
        data = validate_success(api.register_student(
            {"email": "sys@x.com", "full_name": "Sys"}, ANON), expected_status=201)
        assert data["diagnostic_score"] is None
