"""Student intake defaults, requirement configuration, listing and pagination."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_instants_equal,
    assert_student,
    create_mmr_requirement,
    create_student,
    create_student_payload,
    create_vaccine_requirement_payload,
    get_compliance,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStudentIntake:

    def test_student_creation_applies_defaults(self):
        """PRD section 3.1: "Every student begins life in the `ENROLLED_PROVISIONAL`
        status: state rules grant families a provisional window of 30 days from
        enrollment to produce complete records. At creation the system computes the
        student's `provisional_deadline` as the `enrollment_date` plus 30 days, and
        immediately runs its first requirement evaluation, populating the student's
        `deficiency_vaccine_codes` with the vaccine codes of every applicable
        requirement that is not currently satisfied under LOCAL_RECORDS."
        PRD section 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/entities/student_creation_applies_defaults
        """
        create_mmr_requirement(doses_required=1)
        resp = api_client.create_student(
            create_student_payload(
                legal_name="Lee Default",
                school_code="SCH-D1",
                enrollment_date="2026-08-01T00:00:00Z",
            ),
            TEST_USERS["clerk_headers"],
        )
        body = resp.json()
        data = validate_success(resp, 201)
        assert_student(data)
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert data["status"] == "ENROLLED_PROVISIONAL"
        assert_instants_equal(
            data["provisional_deadline"], "2026-08-31T00:00:00Z",
            "provisional_deadline must be enrollment_date + 30 days",
        )
        assert isinstance(data["version"], int)
        assert data["deficiency_vaccine_codes"] == ["MMR"], (
            "the one applicable unsatisfied requirement must be listed as deficient"
        )

    def test_student_get_not_found_returns_404(self, clerk_headers):
        """PRD section 2.7: "an unresolvable identifier yields the corresponding
        not-found error: `ERR_STUDENT_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`,
        `ERR_EXEMPTION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or
        `ERR_SNAPSHOT_NOT_FOUND`."

        Design: Corner/entities/student_get_not_found_returns_404
        """
        resp = api_client.get_student(NON_EXISTENT_UUID, clerk_headers)
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND)

    def test_student_missing_required_grade_returns_400(self, clerk_headers):
        """PRD section 2.7: "10. **Request-body schema** — required fields present,
        enum members valid, types well-formed; failure yields `ERR_VALIDATION`."
        PRD section 3.1: "A `HealthClerk` registers a student by supplying the
        student's `legal_name`, `date_of_birth` (normalized to midnight UTC),
        current `grade`, the `school_code` of the enrolling school, and the
        `enrollment_date`."

        Design: Corner/entities/student_missing_required_grade_returns_400
        """
        payload = create_student_payload(legal_name="No Grade", school_code="SCH-D1")
        del payload["grade"]
        resp = api_client.create_student(payload, clerk_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_student_invalid_grade_enum_returns_400(self, clerk_headers):
        """PRD section 3.1: "Grade values are drawn from the fixed set `PK`, `K`,
        `G1`, `G2`, `G3`, `G4`, `G5`, `G6`, `G7`, `G8`, `G9`, `G10`, `G11`, `G12`."
        PRD section 2.7: "10. **Request-body schema** — required fields present,
        enum members valid, types well-formed; failure yields `ERR_VALIDATION`."

        Design: Corner/entities/student_invalid_grade_enum_returns_400
        """
        payload = create_student_payload(
            legal_name="Bad Grade", grade="G13", school_code="SCH-D1"
        )
        resp = api_client.create_student(payload, clerk_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_students_list_pagination_envelope(self, nurse_headers):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned; it defaults to 10, accepts a minimum of 1, and is capped at a
        maximum of 100. The `offset` parameter specifies how many items to skip and
        defaults to 0."
        PRD section 2.3: "List responses carry the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/students_list_pagination_envelope
        """
        for name in ("P One", "P Two", "P Three"):
            create_student("SCH-P", legal_name=name)

        page1, meta1 = validate_paginated(
            api_client.list_students(
                nurse_headers, params={"school_code": "SCH-P", "limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api_client.list_students(
                nurse_headers, params={"school_code": "SCH-P", "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_withdraw_twice_rejected(self, clerk_headers):
        """PRD section 3.1: "Withdrawal is a terminal act performed by a
        `HealthClerk`. A student may be withdrawn from `ENROLLED_PROVISIONAL`,
        `ENROLLED_COMPLIANT`, `NON_COMPLIANT`, or `EXCLUDED`; in every case the
        student's `status` becomes `WITHDRAWN` and the student's `version` is
        incremented."
        PRD section 3.1: "Once a student is `WITHDRAWN`, dose entry, exemption
        submission, and appointment booking against that student are all rejected
        with `ERR_STUDENT_NOT_ACTIVE`."

        Design: Corner/state_machines/withdraw_twice_rejected
        """
        student = create_student("SCH-SM", legal_name="Will Draw")
        first = validate_success(
            api_client.withdraw_student(student["id"], clerk_headers), 200
        )
        assert first["status"] == "WITHDRAWN"
        resp = api_client.withdraw_student(student["id"], clerk_headers)
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_ACTIVE)


class TestVaccineRequirements:

    def test_duplicate_requirement_config_rejected(self, officer_headers):
        """PRD section 3.2: "The combination of `vaccine_code` and `school_year` is
        unique: configuring a second requirement for a pair that already exists is
        rejected with `ERR_DUPLICATE_REQUIREMENT`."

        Design: Corner/validations/duplicate_requirement_config_rejected
        """
        first = validate_success(
            api_client.create_vaccine_requirement(
                create_vaccine_requirement_payload(doses_required=2), officer_headers
            ),
            201,
        )
        assert first["vaccine_code"] == "MMR"
        resp = api_client.create_vaccine_requirement(
            create_vaccine_requirement_payload(
                applies_to_grades=["G1"], doses_required=1
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REQUIREMENT)

    def test_requirement_grade_filtering(self, nurse_headers):
        """PRD section 3.2: "A requirement applies when the student's `grade` is
        among its `applies_to_grades` and its `school_year` equals the academic-year
        label of the current logical clock (August through July, per §2.4)."
        PRD section 3.1: "the student's full compliance posture can be read through
        the computed per-requirement compliance view, which returns the student's
        `student_status` together with a `requirements` array — one row per
        applicable requirement showing both evaluation variants and the next-dose
        due date."

        Design: Corner/calculations/requirement_grade_filtering
        """
        create_mmr_requirement(applies_to_grades=["PK"], doses_required=1)
        created = validate_success(
            api_client.create_student(
                create_student_payload(legal_name="Grade Filter", school_code="SCH-G1"),
                TEST_USERS["clerk_headers"],
            ),
            201,
        )
        assert created["deficiency_vaccine_codes"] == [], (
            "a PK-only requirement must not apply to a grade-K student"
        )
        compliance = get_compliance(created["id"])
        assert compliance["student_status"] == "ENROLLED_PROVISIONAL"
        assert compliance["requirements"] == [], (
            "no requirement row may appear when none applies to the student's grade"
        )
