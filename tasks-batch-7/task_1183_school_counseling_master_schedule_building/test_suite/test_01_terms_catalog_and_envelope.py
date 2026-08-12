"""Terms, catalog, people basics and response envelope."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_student_headers,
    setup_counselor, setup_term, setup_course, setup_student, setup_teacher,
    create_term_payload, create_course_payload, create_student_payload,
    assert_term, assert_course, assert_student, assert_teacher_qualification,
)

ADMIN = TEST_USERS["admin_headers"]


class TestTermCreation:
    def test_term_creation_applies_defaults(self, api):
        """PRD §3.1: "Two optional knobs tune downstream workflows:
        `singleton_section_cap`, the maximum number of single-section courses one
        student may hold (default 2; a value of 0 leaves singletons unrestricted,
        and the cap may not exceed `periods_per_day`), and
        `change_request_max_per_student`, the cap on approved-but-unexecuted
        change requests per student per term (default 3, and at least 1)."
        PRD §3.1: "A new term starts in posture `COLLECTING` with
        `change_window_open` false, `rebalance_epoch` 0, and
        `total_requested_seats` 0"

        Design: Corner/entities/term_creation_applies_defaults
        """
        resp = api.create_term({
            "code": "2040-FALL",
            "periods_per_day": 8,
            "max_students_per_section": 32,
            "class_size_target": 25,
        }, ADMIN)
        data = validate_success(resp, 201)
        assert_term(data)
        assert data["singleton_section_cap"] == 2, "default singleton_section_cap must be 2"
        assert data["change_request_max_per_student"] == 3, "default change_request_max_per_student must be 3"
        assert data["posture"] == "COLLECTING"
        assert data["version"] == 1
        assert data["change_window_open"] is False
        assert data["rebalance_epoch"] == 0

    def test_term_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.2: "a malformed sequence — like any missing required field,
        invalid enum value, or credit value not expressed in quarter steps — is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/term_missing_required_field_returns_invalid_request
        """
        resp = api.create_term({
            "code": "2040-SPR",
            "max_students_per_section": 32,
            "class_size_target": 25,
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestCatalogAndPeople:
    def test_student_computed_fields_input_ignored(self, api):
        """PRD §3.4: "the student's `planned_credit_load` — the sum of course
        `credits` over the student's `ENROLLED` entries for the term, recomputed
        on every enrollment mutation and starting from 0"
        PRD §3.7: "The student's `credit_deficient` flag simply reflects the
        latest audit: true exactly when that audit's `deficiency_credits` is
        positive, and false by default before any audit exists."
        (Both fields are computed; a fresh student has no enrollments and no
        audit, so both start at 0 / false regardless of input noise.)

        Design: Corner/entities/student_computed_fields_input_ignored
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Ent")
        resp = api.create_student({
            "external_ref": "CMP1",
            "full_name": "Computed Stu",
            "grade_level": 9,
            "counselor_id": counselor["id"],
            "planned_credit_load": 99.0,
            "credit_deficient": True,
        }, ADMIN)
        data = validate_success(resp, 201)
        assert data["planned_credit_load"] == 0, f"expected computed 0, got {data['planned_credit_load']}"
        assert data["credit_deficient"] is False

    def test_get_missing_entity_returns_not_found(self, api):
        """PRD §2.8: "the request fails with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not resolve to an existing resource."

        Design: Corner/entities/get_missing_entity_returns_not_found
        """
        resp = api.get_course(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_course_credit_step_constraint_enforced(self, api):
        """PRD §3.1: "a credit value of at least 0.25 and at most 2.00 in
        quarter-credit steps"
        PRD §3.2: "a malformed sequence — like any missing required field,
        invalid enum value, or credit value not expressed in quarter steps — is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/course_credit_step_constraint_enforced
        """
        resp = api.create_course({
            "course_code": "BAD-1",
            "title": "Bad",
            "credits": 1.10,
            "subject_area": "ELECTIVE",
            "grade_band_min": 9,
            "grade_band_max": 12,
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_teacher_qualification_immutable_no_version(self, api):
        """PRD §2.5: "`TeacherQualification`, `CreditAudit`, and `RebalanceRun`
        carry only `id` and `created_at`; both `updated_at` and `version` are
        absent from them."

        Design: Corner/entities/teacher_qualification_immutable_no_version
        """
        teacher = setup_teacher(max_sections=3, full_name="T Q")
        course = setup_course("Q-1", credits=1.0, subject_area="ELECTIVE", title="Qual Course")
        resp = api.create_qualification(teacher["id"], {
            "course_id": course["id"], "qualified_at": "2026-02-01T00:00:00Z",
        }, ADMIN)
        data = validate_success(resp, 201)
        assert_teacher_qualification(data)
        assert "version" not in data, "qualification must not carry version"
        assert "updated_at" not in data

    def test_course_prerequisite_self_reference(self, api):
        """PRD §3.2: "a course with a `prerequisite_course_id` demands that the
        student has either earned credit for the prerequisite course already or
        holds an `ENROLLED` entry in it this term"
        PRD §3.2: "Eligibility is checked when the request is created and again
        when it is submitted, with any failure surfacing as
        `ERR_COURSE_INELIGIBLE` (HTTP 422)"

        Design: Corner/entities/course_prerequisite_self_reference
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Pre")
        term = setup_term("2042-FALL")
        k_pre = setup_course("MATH-201", credits=1.0, subject_area="MATH", title="Algebra I")
        k_seq = setup_course(
            "MATH-302", credits=1.0, subject_area="MATH", title="Algebra IIx",
            prerequisite_course_id=k_pre["id"],
        )
        student = setup_student(counselor["id"], "SEQ1", grade_level=10, earned_credits=0)
        resp = api.create_course_request({
            "student_id": student["id"], "course_id": k_seq["id"],
            "term_id": term["id"], "priority_rank": 1,
        }, make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_COURSE_INELIGIBLE, 422)


class TestCaseload:
    def test_caseload_full_rejection(self, api):
        """PRD §3.1: "Assigning a student to a counselor — at creation or on any
        later reassignment — requires the counselor's `caseload_count` to be
        strictly below `max_caseload`; a full caseload rejects the assignment
        with `ERR_CASELOAD_FULL` (HTTP 422)."

        Design: Corner/validations/caseload_full_rejection
        """
        counselor = setup_counselor(max_caseload=1, full_name="C Full")
        setup_student(counselor["id"], "CF01", grade_level=9)
        resp = api.create_student(
            create_student_payload(external_ref="CF02", grade_level=9,
                                   counselor_id=counselor["id"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CASELOAD_FULL, 422)


class TestPaginationAndEnvelope:
    def test_filtered_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return: it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter specifies the number of items to skip and defaults
        to 0."
        PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/endpoints/filtered_list_pagination_envelope
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Pg")
        term = setup_term("2059-FALL")
        student = setup_student(counselor["id"], "PG01", grade_level=9)
        for i in range(1, 13):
            course = setup_course(f"PG-{i}", credits=1.0, subject_area="ELECTIVE")
            get_success_data(api.create_course_request({
                "student_id": student["id"], "course_id": course["id"],
                "term_id": term["id"], "priority_rank": i,
            }, make_student_headers(student["id"])))

        resp = api.list_course_requests(ADMIN, params={"student_id": student["id"]})
        data, meta = validate_paginated(resp)
        assert len(data) == 10, f"default page must hold 10 items, got {len(data)}"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        resp2 = api.list_course_requests(ADMIN, params={"student_id": student["id"], "offset": 10})
        data2, meta2 = validate_paginated(resp2)
        assert len(data2) == 2, f"offset=10 page must hold 2 items, got {len(data2)}"
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 12

    def test_response_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" with
        `meta.api_request_id`, `meta.api_request_timestamp`, `response_type` and
        `data`; "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with `response_type` = "error" and
        `data.error_id`.

        Design: Corner/endpoints/response_envelope_shape
        """
        resp = api.create_term({
            "code": "2064-FALL", "periods_per_day": 8,
            "max_students_per_section": 32, "class_size_target": 25,
        }, ADMIN)
        body = resp.json()
        assert resp.status_code == 201
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "object"
        assert isinstance(body["data"].get("id"), str)

        err_resp = api.get_course(NON_EXISTENT_UUID, ADMIN)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
