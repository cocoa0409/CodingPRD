"""Auth, RBAC, response envelope, pagination, and NotFound.

These exercise the cross-cutting checks defined in PRD §2.1 (auth /
role), §2.2 (envelope), §2.3 (pagination), §2.8 (path validation)
which apply across every endpoint.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    build_user_headers,
    create_district,
    create_district_payload,
    create_iep_payload,
    create_student,
    create_student_payload,
    is_iso8601_timestamp,
    setup_active_iep,
    setup_eligible_student,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing / invalid role / forbidden
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the
        request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: a POST with neither header set →
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        res = api.create_district(
            create_district_payload(state_code="NY"),
            headers={},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the
        request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: omitting X-User-ID while supplying X-User-Role →
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        res = api.create_district(
            create_district_payload(state_code="NY"),
            headers={"X-User-Role": "DistrictAdmin"},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the
        request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: omitting X-User-Role while supplying X-User-ID →
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        res = api.create_district(
            create_district_payload(state_code="NY"),
            headers={"X-User-ID": "admin-001"},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the
        request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: empty X-User-ID →
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        res = api.create_district(
            create_district_payload(state_code="NY"),
            headers={"X-User-ID": "",
                     "X-User-Role": "DistrictAdmin"},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_unauthorized_role_for_endpoint(self, api):
        """PRD §2.1: "If the role declared in X-User-Role is not
        permitted to invoke the requested operation, the request is
        rejected with ERR_INSUFFICIENT_PERMISSIONS."

        Claim: SchoolPsychologist calling POST /districts (which is
        DistrictAdmin-only per PRD §4) → ERR_INSUFFICIENT_PERMISSIONS.
        """
        res = api.create_district(
            create_district_payload(state_code="NY"),
            headers=build_user_headers("psych-1", "SchoolPsychologist"),
        )
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")

    def test_teacher_cannot_activate_related_service(self, api):
        """PRD §4 endpoint table: "PUT .../related-services/{serviceId}
        /activate ... RelatedServiceProvider".
        PRD §2.1: "If the role declared in X-User-Role is not
        permitted to invoke the requested operation, the request is
        rejected with ERR_INSUFFICIENT_PERMISSIONS."

        Claim: SpecialEducationTeacher attempting to PUT activate on a
        related service → ERR_INSUFFICIENT_PERMISSIONS (provider-only).
        """
        from test_helpers import (
            create_related_service_consent_approved,
            propose_related_service,
        )
        district, student, _eval, iep, _goal = setup_active_iep()
        service = propose_related_service(
            district["id"], student["id"], iep["id"],
        )
        consent = create_related_service_consent_approved(
            district["id"], student["id"], service["id"],
            parent_user_id=student["parent_user_id"],
        )
        # Use teacher headers — should be rejected.
        res = api.activate_related_service(
            district["id"], student["id"], iep["id"], service["id"],
            {"consent_id": consent["id"]},
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2."""

    def test_success_envelope_shape(self, api, admin_headers):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The api_request_timestamp is a server-generated ISO
        8601 UTC timestamp with three fractional digits."

        Claim: a successful POST returns the documented envelope shape.
        """
        body = api.create_district(
            create_district_payload(state_code="NY"), admin_headers,
        ).json()
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
            f"api_request_timestamp must be ISO 8601, got "
            f"{meta['api_request_timestamp']!r}"
        )
        assert body["response_type"] in {"object", "array"}

    def test_error_envelope_shape(self, api, admin_headers):
        """PRD §2.2: "All error API responses (4xx status codes)
        follow this standard envelope format ... data: { error_id,
        message }."

        Claim: a 404 NotFound carries the documented error envelope.
        """
        res = api.get_district(NON_EXISTENT_UUID, admin_headers)
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_DISTRICT_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"]


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3."""

    def test_default_pagination_limit(self, api, admin_headers):
        """PRD §2.3: "when omitted it defaults to 10".

        Claim: a list endpoint without `limit` returns at most 10
        items and `meta.limit == 10`.
        """
        district = create_district()
        # Create 12 students so the list has more than the default 10.
        for i in range(12):
            create_student(
                district["id"],
                external_student_number=f"STU-{i:04d}",
            )
        data, meta = validate_paginated(
            api.list_students(district["id"], admin_headers),
        )
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT
        assert len(data) <= PAGINATION_DEFAULT_LIMIT

    def test_pagination_meta_fields_present(self, api, admin_headers):
        """PRD §2.3: "Every list response includes `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the
        envelope."
        """
        district = create_district()
        create_student(district["id"])
        data, meta = validate_paginated(
            api.list_students(
                district["id"], admin_headers, params={"limit": 1},
            ),
        )
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"meta missing field {field!r}"
        assert isinstance(meta["limit"], int)
        assert isinstance(meta["offset"], int)
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    def test_pagination_max_limit(self, api, admin_headers):
        """PRD §2.3: "the maximum is 100".

        Claim: requesting `limit=101` is rejected as ERR_INVALID_REQUEST
        or capped at 100; we assert capping or explicit error.
        """
        district = create_district()
        res = api.list_students(
            district["id"], admin_headers,
            params={"limit": PAGINATION_MAX_LIMIT + 1},
        )
        # Implementation may either reject as invalid or cap at 100;
        # either is consistent with "the maximum is 100". We accept the
        # explicit-error variant; do not assert success here.
        if res.status_code >= 400:
            validate_error(res, "ERR_INVALID_REQUEST")
        else:
            body = res.json()
            assert body["meta"]["limit"] <= PAGINATION_MAX_LIMIT


# ===========================================================================
# §2.8 Path validation and NotFound resolution
# ===========================================================================
class TestPathValidation:
    """PRD §2.8: "The system validates each path segment from left to
    right and rejects the request at the first segment that does not
    resolve."
    """

    def test_unknown_district_returns_district_not_found(
        self, api, admin_headers,
    ):
        """PRD §2.8: "A request for an IEP under a non-existent
        student therefore returns ERR_STUDENT_NOT_FOUND, not
        ERR_IEP_NOT_FOUND. The specific 404 returned identifies the
        first missing segment: ERR_DISTRICT_NOT_FOUND ..."

        Claim: GET on a non-existent district →
        ERR_DISTRICT_NOT_FOUND.
        """
        res = api.get_district(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_DISTRICT_NOT_FOUND")

    def test_unknown_student_returns_student_not_found(
        self, api, admin_headers,
    ):
        """PRD §2.8: "The specific 404 returned identifies the first
        missing segment: ERR_DISTRICT_NOT_FOUND, ERR_STUDENT_NOT_FOUND,
        ..."

        Claim: GET student under a valid district but unknown
        student id → ERR_STUDENT_NOT_FOUND.
        """
        district = create_district()
        res = api.get_student(
            district["id"], NON_EXISTENT_UUID, admin_headers,
        )
        validate_error(res, "ERR_STUDENT_NOT_FOUND")

    def test_iep_under_unknown_student_returns_student_not_found(
        self, api, teacher_headers,
    ):
        """PRD §2.8: "A request for an IEP under a non-existent
        student therefore returns ERR_STUDENT_NOT_FOUND, not
        ERR_IEP_NOT_FOUND."

        Claim: GET an IEP whose parent student does not exist →
        ERR_STUDENT_NOT_FOUND (left-to-right path validation).
        """
        district = create_district()
        res = api.get_iep(
            district["id"], NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            teacher_headers,
        )
        validate_error(res, "ERR_STUDENT_NOT_FOUND")

    def test_unknown_iep_returns_iep_not_found(
        self, api, teacher_headers,
    ):
        """PRD §2.8: "ERR_IEP_NOT_FOUND" is the appropriate 404 when
        the district and student resolve but the iep id does not.

        Claim: GET on a valid district + valid student + unknown iep
        → ERR_IEP_NOT_FOUND.
        """
        _district, student, _evaluation = setup_eligible_student()
        # The district id is on the student row.
        res = api.get_iep(
            student["district_id"], student["id"], NON_EXISTENT_UUID,
            teacher_headers,
        )
        validate_error(res, "ERR_IEP_NOT_FOUND")
