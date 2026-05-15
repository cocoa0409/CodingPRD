"""Auth, response envelope, and RBAC tests (PRD §2.1, §2.2, §2.8)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_facility_payload,
    create_institution_payload,
    create_region_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Header presence — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header_returns_auth_required(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_AUTH_REQUIRED."

        Claim: omitting X-User-ID → ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/epi/audit-logs",
            headers={"X-User-Role": "CDCSupervisor"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_header_returns_auth_required(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_AUTH_REQUIRED."

        Claim: omitting X-User-Role → ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/epi/audit-logs",
            headers={"X-User-ID": "someone-1"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_both_headers_missing_returns_auth_required(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_AUTH_REQUIRED."

        Claim: omitting both X-User-ID and X-User-Role → ERR_AUTH_REQUIRED.
        """
        resp = api._request("GET", "/epi/audit-logs", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Role permission — PRD §2.1 + §4 endpoint table
# ===========================================================================
class TestRoleForbidden:

    def test_press_officer_cannot_create_region(self, api,
                                                press_officer_headers):
        """PRD §2.1: "A request whose declared role is not permitted for
        the targeted endpoint is rejected with ERR_FORBIDDEN."
        PRD §4: POST /epi/regions is restricted to CDCSupervisor.

        Claim: PressOfficer creating a region → ERR_FORBIDDEN.
        """
        resp = api.create_region(
            create_region_payload(district_code="D-FORBID"),
            press_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_supply_manager_cannot_create_facility(self, api,
                                                    supply_manager_headers):
        """PRD §2.1: "A request whose declared role is not permitted for
        the targeted endpoint is rejected with ERR_FORBIDDEN."
        PRD §4: POST /epi/facilities is restricted to CDCSupervisor.

        Claim: SupplyManager creating a facility → ERR_FORBIDDEN.
        """
        resp = api.create_facility(
            create_facility_payload(district_code="D-FORBID"),
            supply_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_supervisor_cannot_approve_risk_decision(self, api,
                                                      supervisor_headers):
        """PRD §2.1: "A request whose declared role is not permitted for
        the targeted endpoint is rejected with ERR_FORBIDDEN."
        PRD §4: POST /epi/risk-decisions/{id}/approve is restricted to
        RiskExpert.

        Claim: CDCSupervisor approving → ERR_FORBIDDEN even on a missing
        path (auth-then-role fires before NotFound per PRD §2.8).
        """
        resp = api.approve_risk_decision(
            NON_EXISTENT_UUID,
            {"final_tier": "HIGH", "expert_reviewer_id": "exp-1"},
            supervisor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# PRD §2.8 validation priority (header before role before NotFound)
# ===========================================================================
class TestValidationOrdering:

    def test_missing_role_returns_auth_required_not_forbidden(self, api):
        """PRD §2.8: "the server evaluates checks in a fixed priority
        order: header presence first (yielding ERR_AUTH_REQUIRED), then
        role authorization (ERR_FORBIDDEN)."

        Claim: header-presence check fires before role check.
        """
        resp = api._request(
            "POST", "/epi/regions",
            payload=create_region_payload(district_code="D-ORDER"),
            headers={"X-User-ID": "someone-1"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_forbidden_returns_before_not_found(self, api,
                                                 risk_expert_headers):
        """PRD §2.8: "role authorization (ERR_FORBIDDEN), then path-resource existence (ERR_NOT_FOUND)."

        Claim: a forbidden role on a non-existent resource still trips
        ERR_FORBIDDEN — the role check comes before the existence
        check.
        """
        resp = api.create_region(
            create_region_payload(district_code="D-ORDER-2"),
            risk_expert_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_shape_on_create_region(self, api,
                                                     supervisor_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body"
        with meta.api_request_id (starting with req_),
        meta.api_request_timestamp (ISO 8601 UTC with three fractional
        digits), response_type "object", and data.

        Claim: a 201 create response carries the documented envelope.
        """
        payload = create_region_payload(district_code="D-ENV-1")
        resp = api.create_region(payload, supervisor_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert "meta" in body and "data" in body
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_"), (
            f"PRD §2.2 requires api_request_id to start with 'req_', "
            f"got {meta['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict)

    def test_error_envelope_shape_on_missing_auth(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format" with meta.api_request_id /
        meta.api_request_timestamp, response_type "error", and
        data.error_id + data.message.

        Claim: a 401 response carries the documented error envelope.
        """
        resp = api._request("GET", "/epi/audit-logs", headers={})
        assert resp.status_code == 401
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"
        assert isinstance(body["data"]["message"], str)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPaginationBounds:

    @pytest.mark.parametrize("limit", [0, -1, 101])
    def test_invalid_limit_returns_pagination_error(self, api,
                                                     supervisor_headers,
                                                     limit):
        """PRD §2.3: "The limit parameter defaults to 10, with a minimum
        of 1 and a maximum of 100; the offset parameter defaults to 0
        with a minimum of 0. Values outside those bounds are rejected
        with ERR_INVALID_PAGINATION."

        Claim: limit < 1 or > 100 → ERR_INVALID_PAGINATION.
        """
        resp = api.list_audit_logs(
            supervisor_headers, params={"limit": limit},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_negative_offset_returns_pagination_error(self, api,
                                                      supervisor_headers):
        """PRD §2.3: "Values outside those bounds are rejected with
        ERR_INVALID_PAGINATION."

        Claim: offset < 0 → ERR_INVALID_PAGINATION.
        """
        resp = api.list_audit_logs(
            supervisor_headers, params={"offset": -1},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)


# ===========================================================================
# NotFound — PRD §2.6 + §5
# ===========================================================================
class TestPathNotFound:

    def test_get_nonexistent_region(self, api, supervisor_headers):
        """PRD §2.6: "The first path identifier that does not resolve
        produces ERR_NOT_FOUND before any further check runs."

        Claim: GET /epi/regions/{unknown-id} → ERR_NOT_FOUND.
        """
        resp = api.get_region(NON_EXISTENT_UUID, supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_institution(self, api, supervisor_headers):
        """PRD §2.6: "The first path identifier that does not resolve
        produces ERR_NOT_FOUND before any further check runs."

        Claim: GET /epi/institutions/{unknown-id} → ERR_NOT_FOUND.
        """
        resp = api.get_institution(NON_EXISTENT_UUID, supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
