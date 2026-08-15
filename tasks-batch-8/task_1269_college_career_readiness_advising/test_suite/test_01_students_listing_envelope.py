"""Student creation, listing, response envelope, and selector consistency.

PRD §2.1–§2.4 (headers, envelope, pagination, common fields), §3.1 (student
enrollment and the advisor selector).
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS, ApiErrorId, assert_error_envelope,
    assert_student, assert_three_fraction_digits, create_advisor,
    create_student, create_student_payload, validate_error,
    validate_paginated, validate_success,
)


def district_headers() -> dict:
    return TEST_USERS["district_admin_headers"]


class TestStudentCreation:
    def test_student_creation_defaults_and_system_fields(self, api):
        """PRD §3.1: "The new student enters in `ENROLLED` status with
        `graduated_at` unset." PRD §3.1: "an optional `first_generation` flag
        that defaults to false when omitted." PRD §2.4: "The `id` is a
        server-minted UUID used for identity only; it carries no type prefix.
        The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps
        with three fractional digits". PRD §2.4: "The `version` is an integer
        that starts at 1 when the resource is created".

        Design: Corner/entities/student_creation_defaults_and_system_fields
        """
        advisor = create_advisor(max_caseload=10)
        resp = api.create_student(
            create_student_payload(student_ref="ES1", grade_level=9,
                                   advisor_id=advisor["id"]),
            district_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert_student(data)
        assert data["status"] == "ENROLLED"
        assert data["first_generation"] is False
        assert data["version"] == 1
        assert data["graduated_at"] in (None,)
        assert data["assigned_advisor_id"] == advisor["id"]
        assert_three_fraction_digits(data["created_at"])
        assert_three_fraction_digits(data["updated_at"])

    def test_student_create_missing_required_returns_400(self, api):
        """PRD §2.6: "Required fields are present, no unknown fields appear,
        enum members are valid, and numeric ranges hold ... Failure yields
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/student_create_missing_required_returns_400
        """
        advisor = create_advisor(max_caseload=10)
        payload = {"student_ref": "ES2", "full_name": "No Group",
                   "grade_level": 10, "advisor_id": advisor["id"]}
        resp = api.create_student(payload, district_headers())
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_student_create_invalid_enum_rejected(self, api):
        """PRD §2.6: "enum members are valid, and numeric ranges hold —
        `grade_level` between 9 and 12 inclusive ... Failure yields
        `ERR_VALIDATION` (HTTP 400)." PRD §3.1: "the equity-monitoring
        `demographic_group` (one of `GROUP_A`, `GROUP_B`, `GROUP_C`, or
        `GROUP_D`)".

        Design: Corner/entities/student_create_invalid_enum_rejected
        """
        advisor = create_advisor(max_caseload=10)
        bad_enum = api.create_student(
            {"student_ref": "ES3", "full_name": "Bad Enum", "grade_level": 10,
             "demographic_group": "GROUP_Z", "advisor_id": advisor["id"]},
            district_headers(),
        )
        validate_error(bad_enum, ApiErrorId.ERR_VALIDATION)
        bad_grade = api.create_student(
            {"student_ref": "ES4", "full_name": "Bad Grade", "grade_level": 13,
             "demographic_group": "GROUP_A", "advisor_id": advisor["id"]},
            district_headers(),
        )
        validate_error(bad_grade, ApiErrorId.ERR_VALIDATION)

    def test_advisor_get_nonexistent_returns_404(self, api):
        """PRD §2.6: "Path identifiers are validated left to right — the
        student first, then the nested resource — and body-referenced foreign
        keys must point at existing records. Failure yields `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/advisor_get_nonexistent_returns_404
        """
        create_advisor(full_name="Ghost Anchor", max_caseload=10)
        resp = api.get_advisor(NON_EXISTENT_UUID, district_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_student_list_pagination_and_filters(self, api):
        """PRD §3.7: "The student list endpoint supports caseload and cohort
        views through its `advisor_id`, `status`, and `demographic_group`
        filters alongside the standard `limit` and `offset` windowing". PRD
        §2.3: "The `meta` object of every list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/student_list_pagination_and_filters
        """
        advisor = create_advisor(max_caseload=10)
        for ref, group, grade in (("LP1", "GROUP_A", 9), ("LP2", "GROUP_A", 9),
                                  ("LP3", "GROUP_A", 10),
                                  ("LP4", "GROUP_B", 10),
                                  ("LP5", "GROUP_B", 10)):
            create_student(student_ref=ref, demographic_group=group,
                           grade_level=grade, advisor_id=advisor["id"])

        page1 = api.list_students(
            district_headers(),
            params={"demographic_group": "GROUP_A", "limit": 2, "offset": 0},
        )
        data, meta = validate_paginated(page1)
        assert len(data) == 2
        assert all(s["demographic_group"] == "GROUP_A" for s in data)
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        page2 = api.list_students(
            district_headers(),
            params={"demographic_group": "GROUP_A", "limit": 2, "offset": 2},
        )
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1
        assert meta2["has_more"] is False


class TestErrorEnvelope:
    def test_error_envelope_shape_on_4xx(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." PRD §2.2: "The
        `error_id` is a unique, machine-readable string that identifies the
        specific error. The `message` provides a human-readable explanation of
        what went wrong."

        Design: Corner/errors/error_envelope_shape_on_4xx
        """
        resp = api.get_student(NON_EXISTENT_UUID, district_headers())
        body = resp.json()
        assert_error_envelope(body)
        assert body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND.value


class TestSelectorConsistency:
    def test_immediate_visibility_in_same_request(self, api):
        """PRD §3.1: "If `advisor_id` is omitted, the deterministic selector
        of §2.9 chooses the advisor". PRD §2.2: "operations that create or
        modify a resource will return the created or updated resource object
        in the data field."

        Design: Corner/consistency_model/immediate_visibility_in_same_request
        """
        advisor = create_advisor(max_caseload=10)
        resp = api.create_student(
            create_student_payload(student_ref="IM1", grade_level=9),
            district_headers(),
        )
        created = validate_success(resp, expected_status=201)
        assert created["assigned_advisor_id"] == advisor["id"]
        assert created["status"] == "ENROLLED"

        reread = validate_success(api.get_student(created["id"],
                                                  district_headers()))
        assert reread["assigned_advisor_id"] == advisor["id"]
        assert reread["status"] == "ENROLLED"

    def test_selector_tie_break_by_created_at(self, api):
        """PRD §2.9: "the advisor auto-assignment selector builds an
        eligibility pool of advisors whose `status` is `ACTIVE` and whose
        `active_caseload_count` is strictly below their `max_caseload`, ranks
        the pool by `active_caseload_count` ascending, breaks ties by
        `created_at` ascending, and assigns the first advisor in that order."

        Design: Corner/consistency_model/selector_tie_break_by_created_at
        """
        first = create_advisor(full_name="First", max_caseload=10)
        second = create_advisor(full_name="Second", max_caseload=10)

        s1 = validate_success(api.create_student(
            create_student_payload(student_ref="TB1", grade_level=9),
            district_headers()), expected_status=201)
        assert s1["assigned_advisor_id"] == first["id"], (
            "tie at load 0 must be broken by created_at ascending"
        )

        s2 = validate_success(api.create_student(
            create_student_payload(student_ref="TB2", grade_level=9,
                                   demographic_group="GROUP_B"),
            district_headers()), expected_status=201)
        assert s2["assigned_advisor_id"] == second["id"], (
            "after the first assignment, load 0 beats load 1"
        )

    def test_student_create_with_no_advisor_pool_returns_409(self, api):
        """PRD §3.1: "If `advisor_id` is omitted, the deterministic selector
        of §2.9 chooses the advisor, and an empty eligibility pool fails the
        enrollment with `ERR_NO_ADVISOR_AVAILABLE`."

        Design: Corner/validations/student_create_with_no_advisor_pool_returns_409
        """
        resp = api.create_student(
            create_student_payload(student_ref="NA9", grade_level=9),
            district_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ADVISOR_AVAILABLE)
