"""API-wide contracts: response envelopes, error envelope, validation cascade
basics (auth, path resolution, request shape, body references) and pagination
(PRD §2.2, §2.3, §2.5, §2.8).
"""
from test_helpers import (
    COORD,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_course,
    assert_exam_registration,
    create_course_payload,
    create_registration_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_course,
    make_cycle,
    make_open_cycle,
    make_registration,
    make_student,
    make_student_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSuccessEnvelope:
    def test_object_get_envelope_shape(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601
        UTC timestamp with three fractional digits."

        Design: Corner/endpoints/response_envelope_shape_on_object_get
        """
        cycle = make_cycle()
        course = make_course(cycle["id"])
        res = api.get_course(course["id"], COORD)
        body = res.json()
        assert res.status_code == 200
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == course["id"]

    def test_error_envelope_carries_id_and_message(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_carries_id_and_message
        """
        res = api.get_course(NON_EXISTENT_UUID, COORD)
        body = res.json()
        assert res.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0
        assert set(body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }


class TestCourseCreationContract:
    def test_course_creation_returns_stamped_system_fields(self, api):
        """PRD §3.2: "A freshly created course therefore starts `SUSPENDED`
        with an `authorized_teacher_count` of 0 and a `registered_count` of 0."
        PRD §4: "Operations that create a new resource return `201 Created`."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix."

        Design: Corner/entities/course_creation_returns_stamped_system_fields
        """
        cycle = make_cycle()
        res = api.create_course(
            create_course_payload(
                cycle["id"], subject_code="AP_CALC_BC", exam_fee_cents=9800
            ),
            COORD,
        )
        course = validate_success(res, 201)
        assert_course(course)
        assert is_valid_uuid(course["id"])
        assert is_iso8601_timestamp(course["created_at"])
        assert is_iso8601_timestamp(course["updated_at"])
        assert isinstance(course["version"], int)
        # Derived staffing state at birth (PRD §3.2).
        assert course["status"] == "SUSPENDED"
        assert course["authorized_teacher_count"] == 0
        assert course["registered_count"] == 0
        # Input fields echo verbatim.
        assert course["subject_code"] == "AP_CALC_BC"
        assert course["program"] == "AP"
        assert course["exam_fee_cents"] == 9800
        assert course["credit_threshold"] == 3
        assert course["cycle_id"] == cycle["id"]


class TestValidationCascadeBasics:
    def test_missing_auth_headers_rejected_before_path_resolution(self, api):
        """PRD §2.8: "Authentication. The `X-User-Role` and `X-User-ID` headers
        are present and the role is one of the four recognized roles; otherwise
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.8: "Earlier failures mask later ones: a request that fails an
        earlier check is rejected with that check's error and never evaluated
        against later checks."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        # No X-User-Role / X-User-ID headers at all; the path id would 404,
        # but authentication (step 1) masks path resolution (step 3).
        res = api.get_course(NON_EXISTENT_UUID, headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_get_unknown_course_returns_not_found(self, api):
        """PRD §2.8: "Path identifiers resolve to existing resources, validated
        left to right; the first identifier that does not resolve yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_course_not_found_returns_404
        """
        res = api.get_course(NON_EXISTENT_UUID, COORD)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_registration_missing_course_id_returns_invalid_request(self, api):
        """PRD §2.8: "Required fields are present, types are correct, enum
        values are in range, `end_at` is strictly after `start_at`,
        `grade_level` is within 9 through 12, and any supplied score is within
        its program range (1–5 for AP, 1–7 for IB); unknown or unexpected
        fields in a payload are rejected. Violations yield
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.3: "a payload containing their own `student_id`, the
        `course_id`, and optionally an `accommodation_type`"

        Design: Corner/entities/registration_missing_required_field_returns_invalid_request
        """
        cycle = make_open_cycle()
        make_course(cycle["id"])
        student = make_student()
        res = api.create_registration(
            {"student_id": student["id"]},
            make_student_headers(student["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_course_with_computed_field_returns_invalid_request(self, api):
        """PRD §2.8: "unknown or unexpected fields in a payload are rejected.
        Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "A course's `status` is never set directly."

        Design: Corner/entities/create_course_with_extra_field_returns_invalid_request
        """
        cycle = make_cycle()
        payload = create_course_payload(cycle["id"])
        payload["status"] = "ACTIVE"  # computed, server-owned field
        res = api.create_course(payload, COORD)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_course_with_invalid_program_enum_returns_invalid_request(
        self, api
    ):
        """PRD §3.2: "the `program` (exactly one of `AP` or `IB`)"
        PRD §2.8: "Required fields are present, types are correct, enum values
        are in range ... Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_course_invalid_enum_returns_invalid_request
        """
        cycle = make_cycle()
        res = api.create_course(
            create_course_payload(cycle["id"], program="APX"), COORD
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_registration_with_unknown_course_returns_reference_not_found(
        self, api
    ):
        """PRD §2.8: "Foreign keys carried in the request body — `cycle_id`,
        `course_id`, `student_id`, `teacher_id`, `session_id`, and the
        registration identifiers inside `scores` or `present_registration_ids`
        — resolve to existing resources; otherwise `ERR_REFERENCE_NOT_FOUND`
        (HTTP 422)."

        Design: Corner/entities/registration_with_unknown_course_returns_reference_not_found
        """
        make_open_cycle()
        student = make_student()
        res = api.create_registration(
            create_registration_payload(student["id"], NON_EXISTENT_UUID),
            make_student_headers(student["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND, 422)


class TestRegistrationsPagination:
    def test_registrations_list_paginates_with_limit_and_offset(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter sets the number of items skipped and defaults
        to 0."
        PRD §2.2: "List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope."

        Design: Corner/entities/registrations_list_pagination_interaction
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])
        students = [make_student(full_name=f"Stu {i}") for i in range(3)]
        registrations = [
            make_registration(s["id"], course["id"]) for s in students
        ]
        page1, meta1 = validate_paginated(
            api.list_registrations(
                COORD, params={"course_id": course["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        for row in page1:
            assert_exam_registration(row)
        page2, meta2 = validate_paginated(
            api.list_registrations(
                COORD, params={"course_id": course["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2
        paged_ids = {row["id"] for row in page1} | {row["id"] for row in page2}
        assert paged_ids == {r["id"] for r in registrations}
