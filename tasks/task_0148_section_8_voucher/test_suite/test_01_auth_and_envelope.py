"""Authentication, role-based access control, and the response envelope.

PRD §2.1 (auth), §2.2 (envelope), §2.3 (pagination), §5 (error catalog).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    API_PREFIX,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:

    def test_missing_both_headers_returns_auth_required(self, api):
        """PRD §2.1: "If either header is missing, the request is
        rejected with ERR_AUTH_REQUIRED at HTTP 401."

        Claim: a request carrying no X-User-ID and no X-User-Role yields
        ERR_AUTH_REQUIRED.
        """
        resp = api._request("GET", f"{API_PREFIX}/vouchers", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_returns_auth_required(self, api):
        """PRD §2.1: "If either header is missing, the request is
        rejected with ERR_AUTH_REQUIRED at HTTP 401."
        """
        resp = api._request(
            "GET", f"{API_PREFIX}/vouchers",
            headers={"X-User-Role": "PHAAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_returns_auth_required(self, api):
        """PRD §2.1: "If either header is missing, the request is
        rejected with ERR_AUTH_REQUIRED at HTTP 401."
        """
        resp = api._request(
            "GET", f"{API_PREFIX}/vouchers",
            headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_returns_forbidden_role(self, api):
        """PRD §2.1: "If X-User-Role is not one of the six configured
        roles — Applicant, Landlord, Inspector, CaseWorker,
        PortabilityCoordinator, or PHAAdmin — or if the named role is
        not permitted to invoke the requested endpoint per the §4
        authorization matrix, the request is rejected with
        ERR_FORBIDDEN_ROLE at HTTP 403."
        """
        bad_headers = build_user_headers("user-x", "Janitor")
        resp = api._request(
            "GET", f"{API_PREFIX}/vouchers", headers=bad_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    @pytest.mark.parametrize("role", [
        "Applicant", "Landlord", "Inspector", "CaseWorker",
        "PortabilityCoordinator", "PHAAdmin",
    ])
    def test_each_of_six_roles_clears_auth_gate(self, api, role):
        """PRD §2.1: "X-User-Role is not one of the six configured roles
        — Applicant, Landlord, Inspector, CaseWorker,
        PortabilityCoordinator, or PHAAdmin".

        Claim: each of the six accepted role values clears the auth gate.
        A 401 (if any) MUST NOT be ERR_AUTH_REQUIRED for these values.
        """
        headers = build_user_headers(f"user-{role.lower()}", role)
        resp = api._request(
            "GET", f"{API_PREFIX}/vouchers", headers=headers,
        )
        if resp.status_code == 401:
            body = resp.json().get("data", {}) or {}
            assert body.get("error_id") != (
                ApiErrorId.ERR_AUTH_REQUIRED.value
            ), f"role {role!r} should not trip ERR_AUTH_REQUIRED"


class TestRoleAuthorization:

    def test_applicant_cannot_create_voucher(self, api, applicant_headers):
        """PRD §4: POST /vouchers — Authorized Role(s): CaseWorker.
        PRD §2.1: "if the named role is not permitted to invoke the
        requested endpoint per the §4 authorization matrix, the request
        is rejected with ERR_FORBIDDEN_ROLE at HTTP 403."

        Claim: Applicant POST /vouchers → ERR_FORBIDDEN_ROLE.
        """
        resp = api.create_voucher(
            {
                "applicant_id": "00000000-0000-0000-0000-000000000000",
                "zone": "ZONE_A",
                "administering_pha_id": "PHA_001",
            },
            applicant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_landlord_cannot_create_payment_standard(
        self, api, landlord_headers,
    ):
        """PRD §4: POST /payment-standards — Authorized Role(s): PHAAdmin.
        PRD §2.1: "if the named role is not permitted to invoke the
        requested endpoint per the §4 authorization matrix, the request
        is rejected with ERR_FORBIDDEN_ROLE at HTTP 403."

        Claim: Landlord POST /payment-standards → ERR_FORBIDDEN_ROLE.
        """
        resp = api.create_payment_standard(
            {
                "zone": "ZONE_A",
                "bedroom_size": 2,
                "standard_amount_cents": 120_000,
                "mobility_amount_cents": 132_000,
                "effective_from": "2020-01-01T00:00:00.000Z",
            },
            landlord_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_caseworker_cannot_advance_clock(
        self, api, case_worker_headers,
    ):
        """PRD §4: POST /_clock/advance — Authorized Role(s): PHAAdmin.
        PRD §2.1: "if the named role is not permitted to invoke the
        requested endpoint per the §4 authorization matrix, the request
        is rejected with ERR_FORBIDDEN_ROLE at HTTP 403."

        Claim: CaseWorker POST /_clock/advance → ERR_FORBIDDEN_ROLE.
        """
        resp = api.advance_clock(
            {"to_timestamp": "2030-01-01T00:00:00.000Z"},
            case_worker_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_inspector_cannot_create_payment_standard(
        self, api, inspector_headers,
    ):
        """PRD §4: POST /payment-standards — Authorized Role(s): PHAAdmin.
        PRD §2.1: "if the named role is not permitted to invoke the
        requested endpoint per the §4 authorization matrix, the request
        is rejected with ERR_FORBIDDEN_ROLE at HTTP 403."

        Claim: Inspector POST /payment-standards → ERR_FORBIDDEN_ROLE.
        """
        resp = api.create_payment_standard(
            {
                "zone": "ZONE_A",
                "bedroom_size": 2,
                "standard_amount_cents": 120_000,
                "mobility_amount_cents": 132_000,
                "effective_from": "2020-01-01T00:00:00.000Z",
            },
            inspector_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


class TestSuccessEnvelope:

    def test_list_vouchers_envelope_structure(
        self, api, pha_admin_headers,
    ):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body".
        PRD §2.3: "The pagination meta block on list responses carries
        limit, offset, total_count, and has_more".

        Claim: list endpoint returns the meta + response_type + data
        envelope, and meta carries the four pagination fields.
        """
        resp = api.list_vouchers(pha_admin_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta missing {key!r}"


class TestPaginationValidation:

    def test_limit_below_minimum_is_rejected(self, api, pha_admin_headers):
        """PRD §2.3: "limit defaults to 10, has a minimum of 1, and a
        maximum of 100; a request that exceeds the maximum or falls
        below the minimum is rejected as a validation failure
        (ERR_VALIDATION)."
        """
        resp = api.list_vouchers(pha_admin_headers, params={"limit": 0})
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_limit_above_maximum_is_rejected(self, api, pha_admin_headers):
        """PRD §2.3: "limit defaults to 10, has a minimum of 1, and a
        maximum of 100; a request that exceeds the maximum or falls
        below the minimum is rejected as a validation failure
        (ERR_VALIDATION)."
        """
        resp = api.list_vouchers(
            pha_admin_headers, params={"limit": 101},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
