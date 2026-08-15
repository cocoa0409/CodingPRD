"""Response envelope, student/guardian intake rules, auth, and listing."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_iso8601_timestamp,
    ApiErrorId,
    assert_dorm, assert_student, assert_guardian,
    create_dorm_payload, create_student_payload, create_guardian_payload,
    make_student_headers,
    make_parent, make_guardian, make_approved_guardian, make_student,
    NONEXISTENT_UUID,
)


class TestResponseEnvelope:
    def test_success_envelope_shape_and_dorm_persisted(self, api, admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." and "The `response_type` is
        either "object" for a single resource or "array" for a list of resources."
        PRD §3.1: "A dorm's `posture` starts `OPEN`."

        Design: Corner/endpoints/response_envelope_success_and_error_shapes
        """
        res = api.create_dorm(create_dorm_payload(name="Envelope Hall"), admin_headers)
        body = res.json()
        assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
        assert body["meta"].get("api_request_id"), "meta.api_request_id must be present"
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), \
            "meta.api_request_timestamp must be ISO 8601"
        assert body["response_type"] == "object"
        dorm = body["data"]
        assert_dorm(dorm)

        fetched = validate_success(api.get_dorm(dorm["id"], admin_headers), 200)
        assert fetched["id"] == dorm["id"]
        assert fetched["posture"] == "OPEN"

    def test_error_envelope_shape_on_not_found(self, api, admin_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a
        human-readable explanation of what went wrong."
        PRD §2.6: "then existence resolution of path identifiers and body
        foreign keys (`ERR_NOT_FOUND`)".

        Design: Corner/endpoints/response_envelope_success_and_error_shapes
        """
        res = api.get_dorm(NONEXISTENT_UUID, admin_headers)
        body = res.json()
        assert body.get("response_type") == "error"
        assert body["data"].get("message"), "error data.message must be present"
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
        """
        res = api.list_students(headers=None)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestStudentIntake:
    def test_create_student_missing_grade_returns_400(self, api, admin_headers):
        """PRD §2.6: "a missing or malformed required field yields
        `ERR_MISSING_REQUIRED_FIELD` (HTTP 400)".
        PRD §3.2: "A `Student` record captures `legal_name`, `grade` from 9 to 12".

        Design: Corner/entities/student_create_missing_required_field_returns_400
        """
        parent = make_parent()
        payload = create_student_payload(parent["id"], legal_name="No Grade")
        del payload["grade"]
        res = api.create_student(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_MISSING_REQUIRED_FIELD)

    def test_create_student_invalid_gender_enum_returns_422(self, api, admin_headers):
        """PRD §2.6: "a field outside its domain — an unknown enum value, a grade
        outside the nine-to-twelve range, a questionnaire integer outside one to
        five, `beds` outside one to four, `volume_cuft`, `weeks`, or `doses_total`
        below 1, a `returns_at` not strictly after `departs_at`, or an `ends_on`
        not strictly after `starts_on` — yields `ERR_INVALID_FIELD_VALUE`
        (HTTP 422)".
        PRD §3.2: "`gender` of `MALE` or `FEMALE`".

        Design: Corner/entities/student_create_invalid_enum_returns_422
        """
        parent = make_parent()
        payload = create_student_payload(parent["id"], legal_name="Bad Enum",
                                         gender="NONBINARY_X")
        res = api.create_student(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_FIELD_VALUE)

    def test_get_student_nonexistent_returns_not_found(self, api, admin_headers):
        """PRD §2.6: "then existence resolution of path identifiers and body
        foreign keys (`ERR_NOT_FOUND`)".

        Design: Corner/entities/student_get_nonexistent_returns_not_found
        """
        res = api.get_student(NONEXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_students_list_filter_and_pagination(self, api, admin_headers):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
        `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset`
        defaults to 0. All list responses are sorted by `created_at` ascending.
        The `meta` object of a list response carries four pagination fields:
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §4: "List students, optional `parent_id`, `guardian_id`, `grade`,
        `discipline_standing`, `enrollment_status` filters".

        Design: Corner/entities/students_list_pagination_and_filter
        """
        p1, p2, p3 = make_parent(), make_parent(), make_parent()
        make_student(p1["id"], grade=10, gender="MALE", legal_name="G10 A")
        make_student(p2["id"], grade=10, gender="FEMALE", legal_name="G10 B")
        make_student(p3["id"], grade=11, gender="MALE", legal_name="G11 C")

        data1, meta1 = validate_paginated(
            api.list_students(admin_headers, params={"grade": 10, "limit": 1, "offset": 0}))
        assert len(data1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_students(admin_headers, params={"grade": 10, "limit": 1, "offset": 1}))
        assert len(data2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

        assert data1[0]["legal_name"] != data2[0]["legal_name"], \
            "the two pages must surface the two distinct grade-10 students"
        for row in (data1[0], data2[0]):
            assert_student(row)
            assert row["grade"] == 10


class TestGuardianRules:
    def test_wards_counter_tracks_student_creation(self, api, admin_headers):
        """PRD §3.2: "The `wards_assigned` counter tracks how many `ENROLLED` or
        `ON_LEAVE` students reference the guardian."

        Design: Corner/entities/guardian_wards_counter_tracks_student_creation
        """
        guardian = make_approved_guardian(max_wards=3)
        parent = make_parent()
        student = make_student(parent["id"], grade=9, gender="FEMALE",
                               is_international=True, guardian_id=guardian["id"])
        assert student["guardian_id"] == guardian["id"]

        fetched = validate_success(api.get_guardian(guardian["id"], admin_headers), 200)
        assert_guardian(fetched)
        assert fetched["wards_assigned"] == 1

    def test_guardian_approve_twice_returns_invalid_state(self, api, admin_headers):
        """PRD §3.2: "Guardians are created `PENDING`; an administrator approves
        or suspends them."
        PRD §2.6: "Only after all of that does the system check whether the target
        resource sits in a legitimate from-state for the requested transition
        (`ERR_INVALID_STATE`, HTTP 409)".

        Design: Corner/state_machines/guardian_approve_twice_returns_invalid_state
        """
        guardian = make_guardian(max_wards=2)
        approved = validate_success(api.approve_guardian(guardian["id"], admin_headers), 200)
        assert approved["status"] == "APPROVED"

        res = api.approve_guardian(guardian["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_guardian_at_capacity_rejects_second_ward(self, api, admin_headers):
        """PRD §3.2: "assigning a new ward is refused with
        `ERR_GUARDIAN_AT_CAPACITY` once the guardian's `wards_assigned` has
        reached `max_wards`".

        Design: Corner/validations/guardian_capacity_rejected
        """
        guardian = make_approved_guardian(max_wards=1)
        p1, p2 = make_parent(), make_parent()
        make_student(p1["id"], grade=9, gender="FEMALE", is_international=True,
                     guardian_id=guardian["id"], legal_name="Stu K")

        payload = create_student_payload(
            p2["id"], legal_name="Stu L", grade=10, gender="MALE",
            is_international=True, guardian_id=guardian["id"])
        res = api.create_student(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_GUARDIAN_AT_CAPACITY)

    def test_international_student_with_pending_guardian_rejected(self, api, admin_headers):
        """PRD §3.2: "that guardian must already be `APPROVED` (otherwise
        `ERR_GUARDIAN_NOT_APPROVED`)".

        Design: Corner/validations/intl_student_pending_guardian_rejected
        """
        guardian = make_guardian(max_wards=5)  # stays PENDING
        parent = make_parent()
        payload = create_student_payload(
            parent["id"], legal_name="Stu X", grade=9, gender="FEMALE",
            is_international=True, guardian_id=guardian["id"])
        res = api.create_student(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_GUARDIAN_NOT_APPROVED)

    def test_international_student_without_guardian_rejected(self, api, admin_headers):
        """PRD §3.2: "An international student must be created with a
        `guardian_id` (its absence is `ERR_GUARDIAN_REQUIRED`)".

        Design: Corner/validations/intl_student_without_guardian_rejected
        """
        parent = make_parent()
        payload = create_student_payload(
            parent["id"], legal_name="Stu Y", grade=9, gender="MALE",
            is_international=True)
        payload.pop("guardian_id", None)
        res = api.create_student(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_GUARDIAN_REQUIRED)


class TestRoleBasedAccess:
    def test_student_cannot_create_dorm_forbidden(self, api, admin_headers):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        list, or that violates the ownership and scoping rules below, is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /reslife/dorms is authorized for SchoolAdmin only.

        Design: Corner/rbac/student_cannot_create_dorm_forbidden
        """
        student = make_student(make_parent()["id"], grade=10, gender="MALE",
                               legal_name="Stu AF")
        res = api.create_dorm(create_dorm_payload(name="Rogue Hall"),
                              make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
