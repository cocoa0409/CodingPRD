"""Auth headers, role-based access control, response envelope shape.

PRD §2.1 (auth) and §2.2 (envelope) and §2.3 (pagination).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    build_user_headers,
    create_owner,
    create_vehicle,
    create_vehicle_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:

    def test_missing_both_headers_returns_auth_required(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_REQUIRED at HTTP 401."

        Claim: GET with no headers → ERR_AUTH_REQUIRED.
        """
        resp = api._request("GET", "/vehicles", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_returns_auth_required(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_REQUIRED at HTTP 401."
        """
        resp = api._request(
            "GET", "/vehicles",
            headers={"X-User-Role": "PlatformAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_returns_auth_required(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_REQUIRED at HTTP 401."
        """
        resp = api._request(
            "GET", "/vehicles",
            headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_returns_invalid_role(self, api):
        """PRD §2.1: "A request whose X-User-Role is not one of the
        declared roles below is rejected with ERR_INVALID_ROLE at HTTP
        403."

        Claim: a role string outside the nine-value catalog yields
        ERR_INVALID_ROLE.
        """
        bad_headers = build_user_headers("user-x", "Janitor")
        resp = api._request("GET", "/vehicles", headers=bad_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_ROLE.value)

    @pytest.mark.parametrize("role", [
        "Applicant", "VinVerifier", "TaxAssessor", "PlateIssuer",
        "SalvageOfficer", "EmissionsInspector", "LienClerk",
        "RealIDReviewer", "PlatformAdmin",
    ])
    def test_each_of_nine_roles_is_recognized(self, api, role):
        """PRD §2.1: "The nine roles are spelled exactly as follows:
        Applicant, VinVerifier, TaxAssessor, PlateIssuer,
        SalvageOfficer, EmissionsInspector, LienClerk, RealIDReviewer,
        and PlatformAdmin."

        Claim: each declared role clears the role-recognition gate —
        the response is NOT ERR_INVALID_ROLE / ERR_AUTH_REQUIRED.
        """
        headers = build_user_headers(f"user-{role.lower()}", role)
        resp = api._request("GET", "/vehicles", headers=headers)
        body = resp.json().get("data", {}) or {}
        err = body.get("error_id") if isinstance(body, dict) else None
        assert err != ApiErrorId.ERR_AUTH_REQUIRED.value, (
            f"role {role!r} should clear auth gate"
        )
        assert err != ApiErrorId.ERR_INVALID_ROLE.value, (
            f"role {role!r} should be recognized"
        )


class TestRoleAuthorization:

    def test_applicant_cannot_create_vehicle(self, api, applicant_headers):
        """PRD §4: "POST /vehicles" — Authorized Role(s): VinVerifier,
        PlatformAdmin.
        PRD §2.1: "A request whose role is declared but is not
        authorized to invoke the called endpoint (per the role/endpoint
        matrix implied by §4) is rejected with ERR_ROLE_FORBIDDEN."

        Claim: Applicant POST /vehicles → ERR_ROLE_FORBIDDEN.
        """
        resp = api.create_vehicle(create_vehicle_payload(), applicant_headers)
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)

    def test_emissions_inspector_cannot_create_vehicle(self, api,
                                                       emissions_inspector_headers):
        """PRD §4: "POST /vehicles" — Authorized Role(s): VinVerifier,
        PlatformAdmin.
        """
        resp = api.create_vehicle(
            create_vehicle_payload(), emissions_inspector_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)

    def test_applicant_cannot_post_salvage_event(self, api,
                                                 applicant_headers):
        """PRD §4: "POST /vehicles/{vehicle_id}/salvage-event" —
        Authorized Role(s): SalvageOfficer."""
        resp = api.post_salvage_event(
            NON_EXISTENT_UUID, {"severity": "PARTIAL"}, applicant_headers,
        )
        # 403 fires before 404 because PRD §2.8 priority 3 (auth) precedes
        # priority 4 (existence).
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)

    def test_vin_verifier_cannot_run_assess_fees(self, api,
                                                 vin_verifier_headers):
        """PRD §4: "POST /transfer-applications/{id}/assess-fees" —
        Authorized Role(s): TaxAssessor.
        """
        resp = api.assess_fees(NON_EXISTENT_UUID, vin_verifier_headers)
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)

    def test_tax_assessor_cannot_issue_plate(self, api, tax_assessor_headers):
        """PRD §4: "POST /transfer-applications/{id}/issue-plate" —
        Authorized Role(s): PlateIssuer."""
        resp = api.issue_plate(
            NON_EXISTENT_UUID, {"plate_number": "ABC123"},
            tax_assessor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)


class TestSuccessEnvelope:

    def test_create_vehicle_returns_success_envelope(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" — meta, response_type, data.
        """
        resp = api.create_vehicle(
            create_vehicle_payload(),
            TEST_USERS["vin_verifier_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert isinstance(data, dict)
        assert "id" in data and "vin" in data

    def test_envelope_meta_contains_request_id_and_timestamp(self, api):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_. The
        api_request_timestamp is a server-generated ISO 8601 UTC
        timestamp with three fractional digits."
        """
        resp = api.create_vehicle(
            create_vehicle_payload(),
            TEST_USERS["vin_verifier_headers"],
        )
        body = resp.json()
        assert "meta" in body
        meta = body["meta"]
        assert "api_request_id" in meta
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
        )
        assert "api_request_timestamp" in meta


class TestErrorEnvelope:

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: "data: { error_id: UNIQUE_ERROR_IDENTIFIER_STRING,
        message: A human-readable explanation of the error. }"
        """
        resp = api.get_vehicle(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        data = body["data"]
        assert data["error_id"] == ApiErrorId.ERR_RESOURCE_NOT_FOUND.value
        assert isinstance(data.get("message"), str)


class TestPagination:

    def test_list_vehicles_default_limit_is_ten(self, api):
        """PRD §2.3: "limit defaults to 10 when omitted."

        Claim: listing with no limit returns meta.limit == 10.
        """
        # Seed at least one entity so the list isn't empty
        create_vehicle()
        resp = api.list_vehicles(TEST_USERS["platform_admin_headers"])
        data, meta = validate_paginated(resp)
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT, (
            f"default limit should be 10, got {meta['limit']}"
        )
        assert meta["offset"] == 0

    def test_list_vehicles_explicit_pagination(self, api):
        """PRD §2.3: "The meta block of a list response includes limit,
        offset, total_count, and has_more."
        """
        for _ in range(3):
            create_vehicle()
        resp = api.list_vehicles(
            TEST_USERS["platform_admin_headers"],
            params={"limit": 2, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert "total_count" in meta
        assert "has_more" in meta

    def test_list_vehicles_limit_too_large_rejected(self, api):
        """PRD §2.3: "its minimum is 1 and its maximum is 100."

        Claim: limit=101 → ERR_VALIDATION.
        """
        resp = api.list_vehicles(
            TEST_USERS["platform_admin_headers"],
            params={"limit": PAGINATION_MAX_LIMIT + 1},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_list_vehicles_limit_zero_rejected(self, api):
        """PRD §2.3: "its minimum is 1 and its maximum is 100."

        Claim: limit=0 → ERR_VALIDATION.
        """
        resp = api.list_vehicles(
            TEST_USERS["platform_admin_headers"],
            params={"limit": 0},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestNotFound:

    def test_get_vehicle_unknown_id_returns_not_found(self, api):
        """PRD §2.8 priority 4: "every path-resolved resource id must
        exist (ERR_RESOURCE_NOT_FOUND), resolved left-to-right."
        """
        resp = api.get_vehicle(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_get_owner_unknown_id_returns_not_found(self, api):
        """PRD §2.8 priority 4: "every path-resolved resource id must
        exist (ERR_RESOURCE_NOT_FOUND)."""
        resp = api.get_owner(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)
