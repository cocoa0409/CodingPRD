"""Authentication, role validation, response envelope, and pagination.

Coverage targets (PRD §2.1, §2.2, §2.3, §2.5):
- Missing / malformed auth headers -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
- Disallowed role -> ERR_FORBIDDEN_ROLE.
- Left-to-right path resolution -> first non-existent identifier governs.
- Pagination defaults and bounds on list endpoints.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_customer,
    create_vehicle,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing / malformed auth headers — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Missing or malformed headers are rejected at the
        front door with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: omitting both X-User-ID and X-User-Role -> 400 with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        resp = api._request("GET", "/vehicles", headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "Missing or malformed headers are rejected at the
        front door with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: missing X-User-Role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        resp = api._request(
            "GET", "/vehicles", headers={"X-User-ID": "x"},
        )
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Missing or malformed headers are rejected at the
        front door with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: missing X-User-ID -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        resp = api._request(
            "GET", "/vehicles",
            headers={"X-User-Role": "PlatformAdmin"},
        )
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )


# ===========================================================================
# Disallowed role — PRD §2.1
# ===========================================================================
class TestForbiddenRole:

    def test_customer_cannot_register_vehicle(self, api):
        """PRD §2.1: "When the headers are well-formed but the named
        role is not permitted to invoke the requested operation, the
        request is rejected with ERR_FORBIDDEN_ROLE."

        Claim: Customer role calling POST /vehicles (PlatformAdmin
        exclusive per PRD §4) -> ERR_FORBIDDEN_ROLE / 403.
        """
        # Use the fallback Customer header — this test does NOT
        # exercise ownership; it asserts role rejection before any
        # ownership check would run.
        resp = api_client.create_vehicle(
            {"vin": "X" * 17, "model": "M",
             "msrp_cents": 1000, "residual_factor_bps": 5000},
            TEST_USERS["customer_fallback_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_finance_manager_cannot_create_loan_contract(self, api):
        """PRD §2.1: "the request is rejected with ERR_FORBIDDEN_ROLE."

        Claim: FinanceManager role calling POST loan-contracts (which
        PRD §4 marks as LoanOfficer exclusive) -> ERR_FORBIDDEN_ROLE.
        """
        # Customer + vehicle just so the path resolves; the role check
        # should fire first per PRD §2.11 priority 2.
        customer = create_customer()
        vehicle = create_vehicle()
        resp = api_client.create_loan_contract(
            customer["id"],
            {"vehicle_id": vehicle["id"],
             "down_payment_cents": 150_000, "term_months": 36},
            TEST_USERS["finance_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Left-to-right path validation — PRD §2.5
# ===========================================================================
class TestPathResolution:

    def test_payment_under_missing_customer_returns_customer_not_found(self, api):
        """PRD §2.5: "The first identifier that does not resolve to an
        existing row determines the error: a request for a payment
        under a non-existent customer returns ERR_CUSTOMER_NOT_FOUND,
        never ERR_PAYMENT_NOT_FOUND."

        Claim: GET payment under non-existent customer -> ERR_CUSTOMER_NOT_FOUND.
        """
        resp = api_client.get_payment(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)

    def test_assessment_under_missing_customer_returns_customer_not_found(self, api):
        """PRD §2.5: "The first identifier that does not resolve to an
        existing row determines the error".

        Claim: settle assessment under non-existent customer ->
        ERR_CUSTOMER_NOT_FOUND.
        """
        resp = api_client.settle_assessment(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            TEST_USERS["customer_fallback_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)

    def test_missing_vehicle_returns_vehicle_not_found(self, api):
        """PRD §2.5: "and to vehicles when looked up directly
        (ERR_VEHICLE_NOT_FOUND)."

        Claim: GET /vehicles/{unknown} -> ERR_VEHICLE_NOT_FOUND.
        """
        resp = api_client.get_vehicle(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_FOUND.value)

    def test_missing_contract_returns_contract_not_found(self, api):
        """PRD §2.5: "The same principle applies to lease contracts and
        loan contracts (ERR_CONTRACT_NOT_FOUND)."

        Claim: GET loan-contract under valid customer but unknown
        contract id -> ERR_CONTRACT_NOT_FOUND.
        """
        customer = create_customer()
        resp = api_client.get_loan_contract(
            customer["id"], NON_EXISTENT_UUID,
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_list_vehicles_default_limit(self, api):
        """PRD §2.3: "if omitted it defaults to 10".

        Claim: list /vehicles without limit -> meta.limit == 10.
        """
        # Seed a couple of vehicles so the list is well-formed.
        create_vehicle()
        create_vehicle()
        resp = api_client.list_vehicles(
            TEST_USERS["platform_admin_headers"],
        )
        data, meta = validate_paginated(resp)
        assert meta.get("limit") == PAGINATION_DEFAULT_LIMIT, (
            f"default limit must be 10 per PRD §2.3; got {meta.get('limit')}"
        )
        assert meta.get("offset") == 0
        assert "total_count" in meta and "has_more" in meta

    def test_list_vehicles_explicit_limit_and_offset(self, api):
        """PRD §2.3: "Every list response's meta object carries the
        four pagination fields limit, offset, total_count, and has_more."

        Claim: list with explicit limit + offset returns matching meta.
        """
        for _ in range(3):
            create_vehicle()
        resp = api_client.list_vehicles(
            TEST_USERS["platform_admin_headers"],
            params={"limit": 2, "offset": 1},
        )
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 2
        assert meta["offset"] == 1
        assert len(data) <= 2

    def test_success_envelope_carries_meta_and_response_type(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body".

        Claim: a 200 GET returns the envelope: meta, response_type,
        data.
        """
        veh = create_vehicle()
        resp = api_client.get_vehicle(
            veh["id"], TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(resp)
        assert data["id"] == veh["id"]

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error. The message provides a
        human-readable explanation of what went wrong."

        Claim: a 4xx response carries data.error_id and data.message.
        """
        resp = api_client.get_vehicle(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        body = resp.json() if hasattr(resp, "json") else None
        assert body is not None, "expected JSON body"
        assert body.get("response_type") == "error"
        assert "data" in body
        assert "error_id" in body["data"]
        assert "message" in body["data"]
