"""Request context, response envelope, and role-based access control."""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    create_customer_payload,
    set_clock, create_period, get_period,
)
from test_helpers.assertions import assert_customer


class TestMissingContextHeader:
    @pytest.mark.parametrize("headers", [
        pytest.param({}, id="no-headers"),
        pytest.param({"X-User-Role": "RevenueAccountant", "Content-Type": "application/json"}, id="no-user-id"),
        pytest.param({"X-User-ID": "acct-1", "Content-Type": "application/json"}, id="no-role"),
        pytest.param({"X-User-ID": "acct-1", "X-User-Role": "SuperUser", "Content-Type": "application/json"}, id="undeclared-role"),
    ])
    def test_missing_or_invalid_context_header_rejected(self, api, headers):
        """PRD §2.1: "A request whose headers are missing or empty, or whose
        `X-User-Role` does not name one of the five declared roles, is rejected
        with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.create_customer(
            create_customer_payload(legal_name="NoHdr Co", external_ref="NOHDR-1"),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER, 400)

    def test_missing_headers_nothing_persisted(self, api, manager_headers):
        """PRD §2.1: "A request whose headers are missing or empty, or whose
        `X-User-Role` does not name one of the five declared roles, is rejected
        with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.create_customer(
            create_customer_payload(legal_name="NoHdr Co", external_ref="NOHDR-2"), {}
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER, 400)
        listed = validate_paginated(api.list_contracts(manager_headers))[0]
        assert all(c.get("contract_ref") != "C-NOHDR" for c in listed)


class TestResponseEnvelope:
    def test_success_envelope_shape_on_create(self, api, accountant_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" with `meta`
        carrying `api_request_id` and `api_request_timestamp`, `response_type`
        of "object" for a single resource, and `data` containing the resource.

        Design: Corner/endpoints/response_envelope_shape_on_create
        """
        resp = api.create_customer(
            create_customer_payload(legal_name="Env Co", external_ref="ENV-1"),
            accountant_headers,
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "api_request_id" in body["meta"], "meta.api_request_id missing"
        assert "api_request_timestamp" in body["meta"], "meta.api_request_timestamp missing"
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict) and body["data"].get("id")
        assert_customer(body["data"])

    def test_error_envelope_shape_on_not_found(self, api, accountant_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with `response_type` "error" and `data`
        carrying `error_id` plus a human-readable `message`.
        PRD §2.9: "The first identifier that does not resolve to an existing
        resource rejects the request with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/endpoints/response_envelope_shape_on_create
        """
        resp = api.get_customer("00000000-0000-4000-8000-000000000000", accountant_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"]


class TestRoleDenials:
    def test_reviewer_cannot_create_customer(self, api, reviewer_headers):
        """PRD §4: the `POST /revrec/customers` row names only RevenueAccountant
        as its authorized role.
        PRD §2.1: "A request whose role is not permitted on the targeted endpoint
        is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/reviewer_cannot_create_customer
        """
        resp = api.create_customer(
            create_customer_payload(legal_name="X", external_ref="X-1"),
            reviewer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

    def test_system_admin_cannot_close_period(self, api, admin_headers):
        """PRD §2.1: "A `SystemAdmin` operates the test harness's logical clock
        and nothing else — no business operations, no business reads."
        PRD §4: the `POST /revrec/accounting-periods/{period_id}/close` row names
        only Controller as its authorized role.

        Design: Corner/rbac/system_admin_cannot_close_period
        """
        period = create_period()
        resp = api.close_accounting_period(period["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
        assert get_period(period["id"])["status"] == "OPEN"

    def test_accountant_cannot_finalize_pack(self, api, accountant_headers):
        """PRD §4: the `POST /revrec/disclosure-packs/{pack_id}/finalize` row
        names only Controller as its authorized role.
        PRD §2.1: "A request whose role is not permitted on the targeted endpoint
        is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/accountant_cannot_finalize_pack
        """
        set_clock()
        period = create_period()
        pack = validate_success(api.create_disclosure_pack(period["id"], accountant_headers), 201)
        validate_success(api.assemble_disclosure_pack(pack["id"], accountant_headers))
        validate_success(api.close_accounting_period(period["id"], TEST_USERS["controller_headers"]))
        resp = api.finalize_disclosure_pack(pack["id"], accountant_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


class TestRoleAllowances:
    @pytest.mark.parametrize("headers", [
        pytest.param(TEST_USERS["accountant_headers"], id="accountant"),
        pytest.param(TEST_USERS["manager_headers"], id="manager"),
        pytest.param(TEST_USERS["reviewer_headers"], id="reviewer"),
        pytest.param(TEST_USERS["controller_headers"], id="controller"),
    ])
    def test_all_business_roles_can_read(self, api, headers):
        """PRD §4: "a role cell reading "All business roles" admits
        `RevenueAccountant`, `RevenueManager`, `ContractReviewer`, and
        `Controller`; `SystemAdmin` is excluded from every business endpoint."

        Design: Corner/rbac/reviewer_cannot_create_customer
        """
        customer_resp = api.create_customer(
            create_customer_payload(), TEST_USERS["accountant_headers"]
        )
        customer = validate_success(customer_resp, 201)
        resp = api.get_customer(customer["id"], headers)
        assert validate_success(resp)["id"] == customer["id"]

    def test_system_admin_excluded_from_business_reads(self, api, admin_headers):
        """PRD §4: "`SystemAdmin` is excluded from every business endpoint."
        PRD §2.1: "A request whose role is not permitted on the targeted endpoint
        is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/system_admin_cannot_close_period
        """
        customer = validate_success(
            api.create_customer(create_customer_payload(), TEST_USERS["accountant_headers"]), 201
        )
        resp = api.get_customer(customer["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

    def test_system_admin_can_set_logical_clock(self, api, admin_headers):
        """PRD §2.5: "A `SystemAdmin`-only test-driving capability, mounted
        outside the business prefix at `/_clock/set_current_utc`, advances the
        logical clock to a supplied `to_iso8601` instant and answers with the
        server's `current_utc`."

        Design: Corner/rbac/system_admin_cannot_close_period
        """
        resp = api.set_clock({"to_iso8601": "2026-06-15T00:00:00Z"}, admin_headers)
        data = validate_success(resp)
        assert data["current_utc"].startswith("2026-06-15"), (
            f"clock did not advance: {data}"
        )
