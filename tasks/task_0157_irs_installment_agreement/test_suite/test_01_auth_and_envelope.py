"""Authentication, RBAC, and response envelope shape.

PRD §2.1 (auth/roles), §2.2 (envelope), §2.3 (pagination).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_taxpayer,
    create_taxpayer_payload,
    create_tax_liability,
    make_taxpayer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:

    def test_missing_both_headers_returns_auth_required(self, api):
        """PRD §2.1: "Any request that omits either header, presents an
        unrecognized role, or carries a malformed identifier is
        rejected with ERR_AUTH_REQUIRED."

        Claim: a request with no auth headers → ERR_AUTH_REQUIRED.
        """
        resp = api._request("GET", "/collections/taxpayers", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_returns_auth_required(self, api):
        """PRD §2.1: "Any request that omits either header, presents an
        unrecognized role, or carries a malformed identifier is
        rejected with ERR_AUTH_REQUIRED."
        """
        resp = api._request(
            "GET", "/collections/taxpayers",
            headers={"X-User-Role": "IRSOfficer"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_returns_auth_required(self, api):
        """PRD §2.1: "Any request that omits either header, presents an
        unrecognized role, or carries a malformed identifier is
        rejected with ERR_AUTH_REQUIRED."
        """
        resp = api._request(
            "GET", "/collections/taxpayers",
            headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_returns_auth_required(self, api):
        """PRD §2.1: "Any request that omits either header, presents an
        unrecognized role, or carries a malformed identifier is
        rejected with ERR_AUTH_REQUIRED."

        Claim: a role string outside {Taxpayer, IRSOfficer, OICOfficer}
        is rejected with ERR_AUTH_REQUIRED.
        """
        bad_headers = build_user_headers("user-x", "Janitor")
        resp = api._request(
            "GET", "/collections/taxpayers", headers=bad_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    @pytest.mark.parametrize("role", [
        "Taxpayer", "IRSOfficer", "OICOfficer",
    ])
    def test_each_declared_role_is_recognized(self, api, role):
        """PRD §2.1: "Three roles are recognized, and their names must
        appear exactly as written: Taxpayer, IRSOfficer, and OICOfficer."

        Claim: each declared role clears the auth gate (response is NOT
        ERR_AUTH_REQUIRED).
        """
        headers = build_user_headers(f"user-{role.lower()}", role)
        resp = api._request(
            "GET", "/collections/taxpayers", headers=headers,
        )
        body = resp.json().get("data", {}) or {}
        err = body.get("error_id") if isinstance(body, dict) else None
        assert err != ApiErrorId.ERR_AUTH_REQUIRED.value, (
            f"role {role!r} should clear the auth gate"
        )


class TestRoleAuthorization:

    def test_taxpayer_cannot_register_another_taxpayer(self, api,
                                                       taxpayer_headers):
        """PRD §4: "POST /collections/taxpayers — Authorized Role(s):
        IRSOfficer."
        PRD §2.1: "A request whose headers are well-formed but whose
        role lacks permission for the endpoint ... is rejected with
        ERR_FORBIDDEN."

        Claim: a Taxpayer attempting to register a taxpayer →
        ERR_FORBIDDEN.
        """
        resp = api.create_taxpayer(create_taxpayer_payload(), taxpayer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_oic_officer_cannot_register_taxpayer(self, api,
                                                  oic_officer_headers):
        """PRD §4: "POST /collections/taxpayers — Authorized Role(s):
        IRSOfficer."
        """
        resp = api.create_taxpayer(
            create_taxpayer_payload(), oic_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_oic_officer_cannot_create_tax_liability(self, api,
                                                     oic_officer_headers):
        """PRD §4: "POST /collections/tax-liabilities — Authorized
        Role(s): IRSOfficer."
        """
        taxpayer = create_taxpayer()
        resp = api.create_tax_liability(
            {
                "taxpayer_id": taxpayer["id"],
                "tax_year": 2019,
                "assessment_date": "2020-01-01T00:00:00.000Z",
                "original_assessed_amount_cents": 100_000,
            },
            oic_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_taxpayer_acting_on_another_taxpayer_resource_forbidden(self, api):
        """PRD §2.1: "A request whose headers are well-formed but whose
        role lacks permission for the endpoint — or whose caller is
        acting on a resource it does not own — is rejected with
        ERR_FORBIDDEN."

        Claim: Taxpayer A GETting Taxpayer B's record → ERR_FORBIDDEN.
        """
        a = create_taxpayer()
        b = create_taxpayer()
        a_headers = make_taxpayer_headers(a["id"])
        resp = api.get_taxpayer(b["id"], a_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestResponseEnvelope:

    def test_success_envelope_shape(self, api, irs_officer_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body."

        Claim: a 2xx response carries meta + response_type + data.
        """
        resp = api.create_taxpayer(
            create_taxpayer_payload(), irs_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        # response_type and meta are checked inside validate_success.
        assert "id" in data

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format."

        Claim: a 4xx response carries data.error_id + data.message.
        """
        resp = api._request("GET", "/collections/taxpayers", headers={})
        err = validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)
        assert isinstance(err.get("message"), str)
        assert len(err["message"]) > 0


class TestNotFound:

    def test_get_nonexistent_taxpayer_returns_not_found(self, api,
                                                       irs_officer_headers):
        """PRD §2.5: "Path parameters are validated left-to-right. If a
        referenced resource at the leftmost path position does not
        exist, the request is rejected with ERR_NOT_FOUND before any
        deeper segment is examined."

        Claim: GET on an unknown taxpayer id → ERR_NOT_FOUND.
        """
        resp = api.get_taxpayer(NON_EXISTENT_UUID, irs_officer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_liability_returns_not_found(self, api,
                                                          irs_officer_headers):
        """PRD §2.5: "If a referenced resource at the leftmost path
        position does not exist, the request is rejected with
        ERR_NOT_FOUND."
        """
        resp = api.get_tax_liability(NON_EXISTENT_UUID, irs_officer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_agreement_returns_not_found(self, api,
                                                          irs_officer_headers):
        """PRD §2.5: "Path parameters are validated left-to-right."
        """
        resp = api.get_installment_agreement(
            NON_EXISTENT_UUID, irs_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestPagination:

    def test_list_taxpayers_default_pagination(self, api,
                                               irs_officer_headers):
        """PRD §2.3: "All list endpoints accept two query parameters:
        limit and offset. The default limit is 10, the minimum is 1,
        and the maximum is 100; the default offset is 0."

        Claim: list response carries meta with limit, offset,
        total_count, has_more.
        """
        # Seed at least one taxpayer.
        create_taxpayer()
        resp = api.list_taxpayers(irs_officer_headers)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert "total_count" in meta
        assert "has_more" in meta
