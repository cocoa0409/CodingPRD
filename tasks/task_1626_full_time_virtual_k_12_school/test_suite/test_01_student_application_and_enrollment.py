"""Student application, residency verification, enrollment, and re-enrollment."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_enrollment_term,
    assert_student,
    create_district,
    create_student,
    create_student_payload,
    enroll_student,
    list_enrollment_terms,
    request_reenrollment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_student,
    withdraw_student,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENROLLMENT = TEST_USERS["enrollment_officer_headers"]


class TestStudentCreation:
    def test_create_student_with_required_fields_returns_201(self, api):
        """PRD §3.2: "A fresh application lands in `APPLIED` status:
        `residency_verified_at` is null, `funding_days_claimed` and
        `funding_claim_cents` are zero, and the truancy counters
        `truancy_unexcused_count` and `truancy_flag` start at zero and false."
        PRD §4: "Operations that create a new resource return a `201 Created`
        status code."

        Design: Corner/entities/create_student_with_required_fields_returns_201
        """
        district = create_district(district_code="D-100", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=100)
        resp = api.create_student(
            create_student_payload(district["id"], legal_name="Yara",
                                   date_of_birth="2012-01-01T00:00:00Z",
                                   grade_level=7),
            ENROLLMENT,
        )
        student = validate_success(resp, 201)
        assert_student(student)
        assert student["enrollment_status"] == "APPLIED"
        assert student["special_education_flag"] is False
        assert student["residency_verified_at"] is None
        assert student["funding_days_claimed"] == 0
        assert student["funding_claim_cents"] == 0
        assert student["truancy_unexcused_count"] == 0
        assert student["truancy_flag"] is False

    def test_create_student_with_default_special_education_flag(self, api):
        """PRD §3.2: "a `special_education_flag` may be supplied and defaults
        to `false` when omitted."

        Design: Corner/entities/create_student_with_default_special_education_flag
        """
        district = create_district(district_code="D-101", state_code="TX",
                                   funding_rate_cents=400, enrollment_cap=50)
        resp = api.create_student(
            create_student_payload(district["id"], legal_name="Zack",
                                   date_of_birth="2011-02-02T00:00:00Z",
                                   grade_level=8),
            ENROLLMENT,
        )
        student = validate_success(resp, 201)
        assert "special_education_flag" not in create_student_payload(district["id"])
        assert student["special_education_flag"] is False

    def test_get_student_not_found_returns_404(self, api):
        """PRD §2.7: "Every identifier in the path must resolve to an existing
        entity, validated left to right; otherwise `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_student_not_found_returns_404
        """
        resp = api.get_student(NON_EXISTENT_UUID, ENROLLMENT)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_students_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return: if not provided it defaults to 10, and it accepts a
        minimum of 1 and a maximum of 100. The `offset` parameter specifies how
        many items to skip and defaults to 0."
        PRD §2.3: "List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."

        Design: Corner/entities/list_students_pagination_defaults
        """
        district = create_district(district_code="D-102", state_code="WA",
                                   funding_rate_cents=400, enrollment_cap=50)
        for i in range(3):
            create_student(district["id"], legal_name=f"A{i + 1}",
                           date_of_birth=f"2012-01-0{i + 1}T00:00:00Z")
        resp = api.list_students(ENROLLMENT)
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "array"
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3

    @pytest.mark.parametrize("bad_grade", [13, -1])
    def test_create_student_grade_level_out_of_range(self, api, bad_grade):
        """PRD §3.2: "Grade placement runs from 0, meaning kindergarten,
        through 12, and anything outside that range is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_student_grade_level_out_of_range
        """
        district = create_district(district_code="D-103", state_code="OR",
                                   funding_rate_cents=400, enrollment_cap=50)
        resp = api.create_student(
            create_student_payload(district["id"], legal_name="Bad",
                                   grade_level=bad_grade),
            ENROLLMENT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    @pytest.mark.parametrize(
        "missing_field",
        ["legal_name", "date_of_birth", "grade_level", "district_of_residence_id"],
    )
    def test_create_student_missing_required_field(self, api, missing_field):
        """PRD §3.2: "An `EnrollmentOfficer` — or a `PlatformAdmin` acting in
        that capacity — opens a student application with the child's
        `legal_name`, `date_of_birth` (an ISO 8601 date at midnight UTC),
        `grade_level`, and `district_of_residence_id`"
        PRD §2.7: "Only after all of the above pass does the server validate
        structural input: required fields present, enum values within their
        declared sets, and numeric ranges honored. Violations yield
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_student_missing_required_field
        """
        district = create_district(district_code="D-104", state_code="OR",
                                   funding_rate_cents=400, enrollment_cap=50)
        payload = create_student_payload(district["id"])
        del payload[missing_field]
        resp = api.create_student(payload, ENROLLMENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestEnrollmentLifecycle:
    def test_student_initial_state_is_applied(self, api):
        """PRD §3.2: "A fresh application lands in `APPLIED` status:
        `residency_verified_at` is null, `funding_days_claimed` and
        `funding_claim_cents` are zero, and the truancy counters
        `truancy_unexcused_count` and `truancy_flag` start at zero and false."

        Design: Corner/state_machines/student_initial_state_is_applied
        """
        district = create_district(district_code="D-110", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        student = create_student(district["id"], legal_name="Init",
                                 date_of_birth="2011-03-03T00:00:00Z")
        assert student["enrollment_status"] == "APPLIED"

    def test_enrollment_creates_active_term(self, api):
        """PRD §3.2: "A successful enrollment opens a new **enrollment term**:
        an `EnrollmentTerm` is created for the student with `term_start_date`
        set to the current logical-clock date and `term_status` set to
        `ACTIVE`; `term_end_date` and `proration_mode` remain null while the
        term is open, and `claimable_days` starts at zero."

        Design: Corner/endpoints/enrollment_term_created_on_enroll
        """
        district = create_district(district_code="D-140", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        student = create_student(district["id"], legal_name="ET")
        student = verify_student(student["id"])
        set_clock("2026-08-03T08:00:00Z")
        student = enroll_student(student)
        assert student["enrollment_status"] == "ENROLLED"

        terms, meta = list_enrollment_terms(student["id"])
        assert meta["total_count"] == 1, "exactly one EnrollmentTerm exists"
        term = terms[0]
        assert_enrollment_term(term)
        assert term["term_status"] == "ACTIVE"
        assert term["term_start_date"].startswith("2026-08-03"), (
            f"term_start_date must be the current logical-clock date, got "
            f"{term['term_start_date']!r}")
        assert term["term_end_date"] is None
        assert term["proration_mode"] is None
        assert term["claimable_days"] == 0

    def test_enroll_with_stale_student_version_rejected(self, api):
        """PRD §3.2: "Enrollment is one of the two optimistic-concurrency-guarded
        writes in the system (§2.9): the request must carry
        `expected_student_version` matching the student's current `version`,
        and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_student_version_on_enroll_rejected
        """
        district = create_district(district_code="D-131", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        student = create_student(district["id"], legal_name="Z2")
        verified = verify_student(student["id"])
        stale_version = verified["version"]
        set_clock("2026-08-03T08:00:00Z")
        student = enroll_student(verified)
        set_clock("2026-08-10T08:00:00Z")
        withdraw_student(student["id"], "HOMESCHOOL")
        student = request_reenrollment(student["id"])
        assert student["version"] != stale_version, (
            "setup must advance the student version past the captured one")

        resp = api.enroll_student(student["id"], stale_version, ENROLLMENT)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_student_version_increments_on_each_mutation(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        increments with every modification to the resource — including the
        state transitions and derived-field recomputations described
        throughout §3."
        PRD §3.2: "On success the server stamps `residency_verified_at` with
        the current logical-clock time and increments the student's `version`."
        PRD §3.2: "Entering `ENROLLED` also resets the student's rolling
        truancy window — `truancy_unexcused_count` returns to zero and
        `truancy_flag` clears — and the student's `version` increments."

        Design: Corner/cross_cutting_layers/occ_version_increments_on_student_mutation
        """
        district = create_district(district_code="D-172", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        student = create_student(district["id"], legal_name="V")
        v0 = student["version"]
        verified = verify_student(student["id"])
        assert verified["version"] == v0 + 1, (
            f"verify-residency must increment version: {v0} -> "
            f"{verified['version']}")
        set_clock("2026-08-03T08:00:00Z")
        enrolled = enroll_student(verified)
        assert enrolled["version"] == verified["version"] + 1, (
            f"enroll must increment version: {verified['version']} -> "
            f"{enrolled['version']}")


class TestWithdrawReenrollCycle:
    def _complete_cycle(self):
        """Enrolled 2026-08-03, withdrawn 2026-08-10, re-enrollment requested,
        then enrolled again on 2026-08-17."""
        district = create_district(district_code="D-020", state_code="OR",
                                   funding_rate_cents=400, enrollment_cap=10)
        student = create_student(district["id"], legal_name="Frank",
                                 date_of_birth="2011-11-11T00:00:00Z",
                                 grade_level=8)
        student = verify_student(student["id"])
        set_clock("2026-08-03T08:00:00Z")
        student = enroll_student(student)
        set_clock("2026-08-10T08:00:00Z")
        student = withdraw_student(student["id"], "HOMESCHOOL")
        assert student["enrollment_status"] == "WITHDRAWN"
        student = request_reenrollment(student["id"])
        assert student["enrollment_status"] == "REENROLL_PENDING"
        set_clock("2026-08-17T08:00:00Z")
        return student

    def test_withdrawn_student_can_reenroll_to_enrolled(self, api):
        """PRD §3.2: "A subsequent enrollment call then moves the student from
        `REENROLL_PENDING` back to `ENROLLED` under exactly the same three
        gates as a first enrollment, opening a fresh `ACTIVE` term. Prior
        terms remain on the student's record and continue to contribute their
        computed days to the funding totals described next."

        Design: Difficulty/non_linear_state_machine/student_enrollment_withdrawal_reenrollment_cycle
        """
        pending = self._complete_cycle()
        student = enroll_student(pending)
        assert student["enrollment_status"] == "ENROLLED"
        terms, meta = list_enrollment_terms(student["id"])
        assert meta["total_count"] == 2, (
            f"re-enrollment must open a second term; got {meta['total_count']}")

    def test_reenrollment_opens_fresh_active_term_prior_term_withdrawn(self, api):
        """PRD §3.2: "A subsequent enrollment call then moves the student from
        `REENROLL_PENDING` back to `ENROLLED` under exactly the same three
        gates as a first enrollment, opening a fresh `ACTIVE` term. Prior
        terms remain on the student's record and continue to contribute their
        computed days to the funding totals described next."
        PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by their creation timestamp in ascending order."

        Design: Difficulty/non_linear_state_machine/student_enrollment_withdrawal_reenrollment_cycle
        """
        pending = self._complete_cycle()
        student = enroll_student(pending)
        terms, meta = list_enrollment_terms(student["id"])
        assert meta["total_count"] == 2
        first, second = terms[0], terms[1]
        assert first["term_status"] == "WITHDRAWN"
        assert second["term_status"] == "ACTIVE"
        assert second["term_start_date"].startswith("2026-08-17")
        assert first["term_end_date"] is not None
        assert second["term_end_date"] is None
