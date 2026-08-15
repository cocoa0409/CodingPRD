"""Student registration: field defaults, request-shape validation, uniqueness,
path existence, and the paginated list envelope (PRD §2.2, §2.3, §2.7, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_student,
    create_student_payload,
    register_student,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["aid_officer_headers"]

SSN_A = "555667777"
SSN_B = "444556666"


class TestStudentCreationDefaults:
    def test_student_creation_applies_documented_defaults(self, api):
        """PRD §3.2: "Four academic inputs carry defaults: `cumulative_attempted_credits` and `cumulative_completed_credits` default to 0, `max_timeframe_credits` defaults to 180 (one hundred fifty percent of a typical program length), and `gpa_hundredths` — the cumulative GPA multiplied by one hundred, so 250 means 2.50 — defaults to 0; the completed figure may never exceed the attempted figure (`ERR_FIELD_CONSTRAINT`). A student's `sap_status` begins at `NOT_EVALUATED`."

        Design: Corner/entities/student_creation_applies_defaults
        """
        resp = api.create_student(create_student_payload(SSN_A), OFFICER)
        student = validate_success(resp, 201)
        assert_student(student)
        assert student["cumulative_attempted_credits"] == 0
        assert student["cumulative_completed_credits"] == 0
        assert student["max_timeframe_credits"] == 180
        assert student["gpa_hundredths"] == 0
        assert student["sap_status"] == "NOT_EVALUATED"


class TestStudentRequestShape:
    def test_missing_ssn_rejected_as_invalid_request(self, api, aid_officer_headers):
        """PRD §2.7 (rung 9): "required fields are present and well-typed, strings required to be non-empty are non-empty, enum values are members of their declared sets, and integers are in range — otherwise `ERR_INVALID_REQUEST` (400)."
        PRD §3.2: "An `AidOfficer` registers each applicant as a Student with a nine-digit `ssn` stored as nine digits with no separators, a `full_name`, a unique notification `email`, a `residency` of `IN_STATE` or `OUT_OF_STATE` (which selects the cost-of-attendance figure used in need analysis), a `dependency_status` of `DEPENDENT` or `INDEPENDENT` as reported on the FAFSA, an `enrollment_status` of `FULL_TIME`, `THREE_QUARTER`, `HALF_TIME`, or `LESS_THAN_HALF`, and an integer `grade_level` from 1 to 5 that drives the Stafford caps of §3.6."

        Design: Corner/entities/student_missing_required_field_returns_invalid_request
        """
        payload = create_student_payload(SSN_A)
        del payload["ssn"]
        resp = api.create_student(payload, aid_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_unknown_residency_enum_rejected(self, api, aid_officer_headers):
        """PRD §2.7 (rung 9): "required fields are present and well-typed, strings required to be non-empty are non-empty, enum values are members of their declared sets, and integers are in range — otherwise `ERR_INVALID_REQUEST` (400)."
        PRD §3.2: "a `residency` of `IN_STATE` or `OUT_OF_STATE` (which selects the cost-of-attendance figure used in need analysis)".

        Design: Corner/entities/student_invalid_enum_rejected
        """
        payload = create_student_payload(SSN_A, residency="MID_STATE")
        resp = api.create_student(payload, aid_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestStudentLookup:
    def test_get_student_unknown_id_returns_not_found(self, api, aid_officer_headers):
        """PRD §2.7 (rung 3): "every identifier in the path references an existing entity, validated left-to-right (aid year, then student, then package, then line, then child resource) — otherwise `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/student_get_not_found
        """
        resp = api.get_student(NON_EXISTENT_UUID, aid_officer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_duplicate_ssn_rejected(self, api, aid_officer_headers):
        """PRD §3.2: "Registering a duplicate `ssn` or `email` fails with `ERR_DUPLICATE`."
        PRD §2.7 (rung 11): "`ssn` unique across students, `email` unique across students, `fund_code` unique within an aid year, the (`student_id`, `aid_year_id`, `transaction_number`) triple unique across ISIR records, and at most one AwardPackage per (`student_id`, `aid_year_id`) — otherwise `ERR_DUPLICATE` (409)."

        Design: Corner/entities/student_duplicate_ssn_rejected
        """
        register_student(SSN_A, email="first@example.edu")
        resp = api.create_student(
            create_student_payload(SSN_A, full_name="Second",
                                   email="second@example.edu"),
            aid_officer_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestStudentListPagination:
    def test_list_students_pagination_envelope(self, api, aid_officer_headers):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

        Design: Corner/entities/list_pagination_envelope_shape
        """
        register_student(SSN_A, full_name="Page One", email="p1@example.edu")
        register_student(SSN_B, full_name="Page Two", email="p2@example.edu")

        resp = api.list_students(aid_officer_headers,
                                 params={"limit": 1, "offset": 1})
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert len(data) == 1, f"limit=1 must return exactly one row, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["limit"] == 1
        assert meta["offset"] == 1
        assert meta["has_more"] is False
