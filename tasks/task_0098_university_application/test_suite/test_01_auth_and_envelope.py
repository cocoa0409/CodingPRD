"""Authentication, role-validation, and response-envelope tests.

Covers PRD §2.1 (X-User-ID / X-User-Role headers and role validity),
§2.2 (response envelope), §2.3 (pagination), §2.7 priority ordering of
auth checks.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_applicant,
    create_university,
    get_success_data,
    setup_university_with_program,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Auth header presence (PRD §2.1)
# ---------------------------------------------------------------------------
class TestAuthHeaderPresence:
    """PRD §2.1: 'Every request must carry two headers: X-User-ID,
    identifying the calling principal, and X-User-Role, naming the
    principal's role. Both must be present and non-empty; otherwise
    the request is rejected with ERR_AUTH_MISSING.'"""

    def test_missing_both_headers_yields_err_auth_missing(self, api):
        """PRD §2.1: "Both must be present and non-empty; otherwise the
        request is rejected with ERR_AUTH_MISSING."

        Claim: a request with no auth headers → ERR_AUTH_MISSING / 401.
        """
        res = api._request("GET", "/applications", headers={})
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_yields_err_auth_missing(self, api):
        """PRD §2.1: "Both must be present and non-empty; otherwise the
        request is rejected with ERR_AUTH_MISSING.\""""
        res = api._request(
            "GET", "/applications",
            headers={"X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_yields_err_auth_missing(self, api):
        """PRD §2.1: "Both must be present and non-empty; otherwise the
        request is rejected with ERR_AUTH_MISSING.\""""
        res = api._request(
            "GET", "/applications",
            headers={"X-User-ID": "platform-admin-001"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_id_yields_err_auth_missing(self, api):
        """PRD §2.1: "Both must be present and non-empty; otherwise the
        request is rejected with ERR_AUTH_MISSING.\""""
        res = api._request(
            "GET", "/applications",
            headers={"X-User-ID": "", "X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)


# ---------------------------------------------------------------------------
# Role validity (PRD §2.1)
# ---------------------------------------------------------------------------
class TestRoleValidity:
    """PRD §2.1: 'The X-User-Role value must be one of the five declared
    roles below; any other string yields ERR_AUTH_INVALID_ROLE.'"""

    def test_unknown_role_yields_err_auth_invalid_role(self, api):
        """PRD §2.1: "The X-User-Role value must be one of the five
        declared roles below; any other string yields
        ERR_AUTH_INVALID_ROLE.\""""
        res = api._request(
            "GET", "/applications",
            headers={"X-User-ID": "u-1", "X-User-Role": "Hacker"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)


# ---------------------------------------------------------------------------
# RBAC enforcement (PRD §2.1, §4)
# ---------------------------------------------------------------------------
class TestRBACEnforcement:
    """PRD §2.1: 'Even with a valid role, attempting an operation the
    role is not permitted to invoke (per §4 and the workflows in §3)
    yields ERR_FORBIDDEN.'"""

    def test_applicant_cannot_register_university(self, api, applicant_headers_fallback):
        """PRD §4 endpoint table: POST /universities is authorized for
        PlatformAdmin only. PRD §2.1: "attempting an operation the
        role is not permitted to invoke ... yields ERR_FORBIDDEN."
        """
        # No real applicant needed — the role-permission check should
        # reject BEFORE any path entity resolution.
        from test_helpers import create_university_payload
        res = api.create_university(
            create_university_payload(),
            applicant_headers_fallback,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_admissions_officer_cannot_run_clock_advance(self, api, admissions_officer_headers):
        """PRD §4 endpoint table: POST /_clock/advance is authorized for
        PlatformAdmin only. PRD §3.11: "The capability is administrator-only."
        """
        res = api.advance_clock(60, admissions_officer_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_admissions_officer_cannot_create_applicant(self, api, admissions_officer_headers):
        """PRD §4 endpoint table: POST /applicants is authorized for
        Applicant and PlatformAdmin only.
        """
        from test_helpers import create_applicant_payload
        res = api.create_applicant(
            create_applicant_payload(),
            admissions_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_financial_aid_officer_cannot_decide_application(
        self, api, financial_aid_officer_headers,
    ):
        """PRD §4 endpoint table: POST /applications/{id}/decide is
        authorized for AdmissionsOfficer only.
        """
        # The role permission check should fire before path resolution
        # in priority order (PRD §2.7).
        res = api.decide_application(
            "any-id-value",
            {"decision": "ADMIT"},
            financial_aid_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Response envelope structure (PRD §2.2)
# ---------------------------------------------------------------------------
class TestResponseEnvelope:
    """PRD §2.2: success responses carry meta.api_request_id,
    meta.api_request_timestamp, response_type, data."""

    def test_success_envelope_has_required_meta(self, api, platform_admin_headers):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."
        """
        from test_helpers import create_applicant_payload
        res = api.create_applicant(
            create_applicant_payload(),
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert "id" in data

    def test_success_envelope_api_request_id_prefix(
        self, api, platform_admin_headers,
    ):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."
        """
        from test_helpers import create_applicant_payload
        res = api.create_applicant(
            create_applicant_payload(),
            platform_admin_headers,
        )
        body = res.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', "
            f"got {body['meta']['api_request_id']!r}"
        )

    def test_success_envelope_response_type_object(
        self, api, platform_admin_headers,
    ):
        """PRD §2.2: 'The response_type is either "object" for a single
        resource or "array" for a list of resources.'
        """
        from test_helpers import create_applicant_payload
        res = api.create_applicant(
            create_applicant_payload(),
            platform_admin_headers,
        )
        body = res.json()
        assert body["response_type"] == "object", (
            f"single-resource POST must have response_type=object, "
            f"got {body['response_type']!r}"
        )

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: error responses carry data.error_id and data.message."""
        res = api._request("GET", "/applications", headers={})
        body = res.json()
        assert body["response_type"] == "error", (
            f"error response must have response_type=error, "
            f"got {body['response_type']!r}"
        )
        assert "error_id" in body["data"]
        assert "message" in body["data"]


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
class TestPagination:
    """PRD §2.3: limit default 10, min 1, max 100; offset default 0;
    list responses surface limit/offset/total_count/has_more in meta."""

    def test_list_applications_meta_has_pagination_fields(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: "List responses surface the four pagination fields
        limit, offset, total_count, and has_more inside meta."
        """
        res = api.list_applications(platform_admin_headers)
        data, meta = validate_paginated(res)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta must include '{key}'"
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    def test_invalid_limit_zero_yields_err_validation(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: "the minimum is 1, the maximum is 100; values
        outside that range fail input validation with ERR_VALIDATION."
        """
        res = api.list_applications(
            platform_admin_headers, params={"limit": 0},
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_invalid_limit_too_high_yields_err_validation(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: "the minimum is 1, the maximum is 100; values
        outside that range fail input validation with ERR_VALIDATION."
        """
        res = api.list_applications(
            platform_admin_headers, params={"limit": 101},
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_negative_offset_yields_err_validation(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: "negative offsets fail input validation."
        """
        res = api.list_applications(
            platform_admin_headers, params={"offset": -1},
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)
