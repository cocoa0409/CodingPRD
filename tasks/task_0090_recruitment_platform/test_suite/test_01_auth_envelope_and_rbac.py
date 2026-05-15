"""Authentication, response envelope, RBAC, and validation ordering (PRD §2.1, §2.2, §2.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    blacklist_company_payload,
    create_candidate_payload,
    create_company_payload,
    create_job_posting_payload,
    create_verified_company,
    create_live_posting,
    validate_error,
    validate_success,
)


# ===========================================================================
# Auth header presence (PRD §2.1, validation priority 1)
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header_returns_auth_missing(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING."

        Claim: omitting X-User-ID yields ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/recruitment/job-postings",
            headers={"X-User-Role": "HrUser"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_header_returns_auth_missing(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING."

        Claim: omitting X-User-Role yields ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/recruitment/job-postings",
            headers={"X-User-ID": "user-1"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_id_header_returns_auth_missing(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING."

        Claim: empty X-User-ID is treated as missing.
        """
        resp = api._request(
            "GET", "/recruitment/job-postings",
            headers={"X-User-ID": "", "X-User-Role": "HrUser"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_role_header_returns_auth_missing(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING."

        Claim: empty X-User-Role is treated as missing.
        """
        resp = api._request(
            "GET", "/recruitment/job-postings",
            headers={"X-User-ID": "u-1", "X-User-Role": ""},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# Auth role validity (PRD §2.1, validation priority 2)
# ===========================================================================
class TestAuthRoleValidity:

    def test_unknown_role_returns_invalid_role(self, api):
        """PRD §2.1: "If X-User-Role is set to a value that is not one of
        the seven roles enumerated below, the request is rejected with
        ERR_AUTH_INVALID_ROLE."

        Claim: an undeclared role string yields ERR_AUTH_INVALID_ROLE.
        """
        resp = api._request(
            "GET", "/recruitment/job-postings",
            headers={"X-User-ID": "u-1", "X-User-Role": "Robot"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)

    @pytest.mark.parametrize("role", [
        "HrUser", "HiringManager", "HrApprover", "FinanceApprover",
        "Candidate", "HeadhunterUser", "PlatformAdmin",
    ])
    def test_each_declared_role_accepted_for_listing(self, api, role):
        """PRD §2.1: "The seven roles, spelled exactly as the X-User-Role
        header must carry them, are: HrUser, HiringManager, HrApprover,
        FinanceApprover, Candidate, HeadhunterUser, and PlatformAdmin."

        Claim: every declared role string passes the role-validity check
        (not ERR_AUTH_INVALID_ROLE) when accessing a GET endpoint open
        to at least one role.
        """
        resp = api._request(
            "GET", "/recruitment/job-postings",
            headers={"X-User-ID": "u-1", "X-User-Role": role},
        )
        # We don't assert success; we just confirm it isn't tagged as an
        # invalid-role error.
        if resp.status_code >= 400:
            body = resp.json()
            error_id = body.get("data", {}).get("error_id")
            assert error_id != ApiErrorId.ERR_AUTH_INVALID_ROLE.value, (
                f"Role {role!r} should be recognised, got "
                f"ERR_AUTH_INVALID_ROLE"
            )


# ===========================================================================
# RBAC — role not permitted (PRD §2.1, validation priority 3)
# ===========================================================================
class TestRoleForbidden:

    def test_candidate_cannot_create_company(self, api, candidate_fallback_headers):
        """PRD §2.1: "If the role is recognised but the operation is not
        permitted for that role, the rejection code is ERR_FORBIDDEN."
        PRD §4: POST /recruitment/companies is authorised for HrUser only.

        Claim: a Candidate creating a Company yields ERR_FORBIDDEN.
        """
        resp = api.create_company(
            create_company_payload(), candidate_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_hr_user_cannot_approve_verification(self, api, hr_user_fallback_headers):
        """PRD §2.1: "If the role is recognised but the operation is not
        permitted for that role, the rejection code is ERR_FORBIDDEN."
        PRD §4: POST /recruitment/companies/{id}/approve-verification is
        authorised for PlatformAdmin only.

        Claim: an HrUser approving verification yields ERR_FORBIDDEN.
        """
        resp = api.approve_verification(NON_EXISTENT_UUID, hr_user_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_hr_user_cannot_blacklist_company(self, api, hr_user_fallback_headers):
        """PRD §4: POST /recruitment/companies/{id}/blacklist is authorised
        for PlatformAdmin only.

        Claim: an HrUser blacklisting a Company yields ERR_FORBIDDEN.
        """
        resp = api.blacklist_company(
            NON_EXISTENT_UUID, blacklist_company_payload(), hr_user_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_platform_admin_cannot_create_job_posting(self, api, platform_admin_headers):
        """PRD §4: POST /recruitment/job-postings is authorised for HrUser only.

        Claim: a PlatformAdmin creating a JobPosting yields ERR_FORBIDDEN.
        """
        resp = api.create_job_posting(
            create_job_posting_payload(company_id=NON_EXISTENT_UUID),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_hr_user_cannot_create_candidate(self, api, hr_user_fallback_headers):
        """PRD §4: POST /recruitment/candidates is authorised for Candidate only.

        Claim: an HrUser registering a Candidate yields ERR_FORBIDDEN.
        """
        resp = api.create_candidate(
            create_candidate_payload(), hr_user_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_candidate_cannot_run_settlement_sweep(self, api, candidate_fallback_headers):
        """PRD §4: POST /recruitment/_settlement-sweep/run is authorised
        for PlatformAdmin only.

        Claim: a Candidate triggering the sweep yields ERR_FORBIDDEN.
        """
        resp = api.run_settlement_sweep(candidate_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Validation ordering — auth header missing wins over RBAC (PRD §2.7)
# ===========================================================================
class TestValidationOrdering:

    def test_missing_role_returns_auth_missing_not_forbidden(self, api):
        """PRD §2.7: "Authentication header presence — missing or empty
        X-User-Role or X-User-ID yields ERR_AUTH_MISSING (401)."
        PRD §2.7: "Authentication role validity — X-User-Role not in the
        seven-role list yields ERR_AUTH_INVALID_ROLE (401)."
        PRD §2.7: "RBAC — the acting role lacks permission for this
        operation yields ERR_FORBIDDEN (403)."

        Claim: header presence (priority 1) is checked before role
        permission (priority 3) — missing-role header yields
        ERR_AUTH_MISSING, not ERR_FORBIDDEN.
        """
        resp = api._request(
            "POST", "/recruitment/companies",
            payload=create_company_payload(),
            headers={"X-User-ID": "u-1"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_invalid_role_returns_invalid_role_not_forbidden(self, api):
        """PRD §2.7: "Authentication role validity — X-User-Role not in
        the seven-role list yields ERR_AUTH_INVALID_ROLE (401)."

        Claim: role-validity check (priority 2) fires before RBAC
        (priority 3) — an unknown role yields ERR_AUTH_INVALID_ROLE,
        not ERR_FORBIDDEN.
        """
        resp = api._request(
            "POST", "/recruitment/companies",
            payload=create_company_payload(),
            headers={"X-User-ID": "u-1", "X-User-Role": "Wizard"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)


# ===========================================================================
# Response envelope (PRD §2.2)
# ===========================================================================
class TestResponseEnvelope:

    def test_success_response_carries_envelope(self, api, hr_user_fallback_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body."

        Claim: a successful list call returns the standard envelope with
        meta + response_type + data.
        """
        resp = api.list_job_postings(hr_user_fallback_headers)
        # The list endpoint is open to HrUser per PRD §4.
        validate_success(resp, expected_status=200)
        body = resp.json()
        assert "meta" in body and "data" in body
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id 'starts with req_'"
        )
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "array", (
            "PRD §2.2: response_type is 'array' for a list response"
        )

    def test_error_response_carries_envelope(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format."

        Claim: an error response wraps error_id + message inside the
        standard envelope.
        """
        resp = api._request(
            "GET", "/recruitment/job-postings",
            headers={"X-User-Role": "HrUser"},  # missing X-User-ID
        )
        body = resp.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert body["data"]["error_id"] == ApiErrorId.ERR_AUTH_MISSING.value


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
class TestPagination:

    def test_listing_returns_pagination_meta(self, api, platform_admin_headers):
        """PRD §2.3: "The `meta` block on a list response carries `limit`,
        `offset`, `total_count` (the total number of rows matching the
        filter, ignoring pagination), and `has_more` (true when more
        rows exist beyond the returned window)."

        Claim: list endpoints return the four pagination fields on meta.
        """
        # Create a few postings first.
        company, hr_user = create_verified_company()
        for _ in range(3):
            create_live_posting(company["id"], hr_user["id"])
        resp = api.list_job_postings(platform_admin_headers, params={"limit": 2})
        validate_success(resp, expected_status=200)
        meta = resp.json()["meta"]
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"Pagination meta missing {key!r}"
        assert meta["limit"] == 2
        assert meta["total_count"] >= 3
        assert meta["has_more"] is True

    def test_limit_above_max_yields_validation_error(self, api, platform_admin_headers):
        """PRD §2.3: "`limit` defaults to 10 when omitted, has a minimum
        of 1, and a maximum of 100; any value outside that range yields
        ERR_VALIDATION."

        Claim: limit=101 yields ERR_VALIDATION.
        """
        resp = api.list_job_postings(platform_admin_headers, params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_negative_offset_yields_validation_error(self, api, platform_admin_headers):
        """PRD §2.3: "`offset` defaults to 0 and may not be negative."

        Claim: offset=-1 yields ERR_VALIDATION.
        """
        resp = api.list_job_postings(platform_admin_headers, params={"offset": -1})
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
