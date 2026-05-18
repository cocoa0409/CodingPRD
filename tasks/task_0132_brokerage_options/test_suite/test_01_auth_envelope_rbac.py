"""Authentication, role validation, ownership, response envelope, RBAC.

Coverage targets (PRD §2.1, §2.2, §2.3, §4):
- Missing X-User-ID or X-User-Role -> ERR_AUTH_MISSING (401).
- Unrecognised X-User-Role -> ERR_AUTH_INVALID_ROLE (401).
- Recognised role lacking endpoint permission -> ERR_FORBIDDEN (403).
- Customer accessing another customer's resource ->
  ERR_OWNERSHIP_VIOLATION (403).
- Success / error response envelope shape (meta + response_type + data).
- Pagination meta on list endpoints.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_customer,
    create_customer_payload,
    make_customer_headers,
    setup_approved_customer_and_account,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing / empty headers — PRD §2.1
# ===========================================================================
class TestAuthMissing:
    """PRD §2.1: 'If either header is missing or empty, the request is
    rejected with ERR_AUTH_MISSING at HTTP 401.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING at HTTP 401."

        Claim: omitting both X-User-ID and X-User-Role -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "POST", "/brokerage/customers",
            create_customer_payload(), headers={},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING at HTTP 401."

        Claim: only X-User-ID present -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "POST", "/brokerage/customers",
            create_customer_payload(),
            headers={"X-User-ID": "anything",
                     "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING at HTTP 401."

        Claim: only X-User-Role present -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "POST", "/brokerage/customers",
            create_customer_payload(),
            headers={"X-User-Role": "PlatformAdmin",
                     "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING at HTTP 401."

        Claim: empty X-User-Role -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "POST", "/brokerage/customers",
            create_customer_payload(),
            headers={"X-User-Role": "", "X-User-ID": "x",
                     "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING at HTTP 401."

        Claim: empty X-User-ID -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "POST", "/brokerage/customers",
            create_customer_payload(),
            headers={"X-User-Role": "PlatformAdmin", "X-User-ID": "",
                     "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# Unrecognised role — PRD §2.1
# ===========================================================================
class TestAuthInvalidRole:
    """PRD §2.1: 'If X-User-Role is present but is not one of the three
    recognised roles ... the request is rejected with
    ERR_AUTH_INVALID_ROLE at HTTP 401.'"""

    @pytest.mark.parametrize(
        "bogus_role", ["BorrowerX", "admin", "customer", "operator",
                       "SuperUser"],
    )
    def test_unrecognized_role_rejected(self, api, bogus_role):
        """PRD §2.1: "If X-User-Role is present but is not one of the
        three recognised roles — Customer, ComplianceOfficer, or
        PlatformAdmin — the request is rejected with
        ERR_AUTH_INVALID_ROLE at HTTP 401."

        Claim: any role not in {Customer, ComplianceOfficer,
        PlatformAdmin} -> ERR_AUTH_INVALID_ROLE.
        """
        resp = api._request(
            "POST", "/brokerage/customers", create_customer_payload(),
            headers={"X-User-Role": bogus_role,
                     "X-User-ID": "anything",
                     "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)


# ===========================================================================
# RBAC forbidden — PRD §2.1 + §4
# ===========================================================================
class TestRbacForbidden:
    """PRD §2.1: 'If the role is recognised but is not authorised for
    the endpoint per the RBAC table in §4, the request is rejected with
    ERR_FORBIDDEN at HTTP 403.'"""

    def test_compliance_cannot_create_account(
        self, api, compliance_headers,
    ):
        """PRD §4: "POST /brokerage/accounts — Authorized Role(s):
        Customer".
        PRD §2.1: "If the role is recognised but is not authorised for
        the endpoint per the RBAC table in §4, the request is rejected
        with ERR_FORBIDDEN at HTTP 403."

        Claim: ComplianceOfficer cannot POST /brokerage/accounts.
        """
        resp = api.create_account(
            {"customer_id": "any-id", "account_type": "CASH"},
            compliance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_compliance_cannot_create_order(
        self, api, compliance_headers,
    ):
        """PRD §4: "POST /brokerage/orders — Authorized Role(s):
        Customer".
        PRD §2.1: "If the role is recognised but is not authorised for
        the endpoint per the RBAC table in §4, the request is rejected
        with ERR_FORBIDDEN at HTTP 403."

        Claim: ComplianceOfficer cannot POST /brokerage/orders.
        """
        resp = api.create_order(
            {"account_id": "any-id", "symbol": "AAPL",
             "instrument_type": "EQUITY", "side": "BUY",
             "order_type": "MARKET", "quantity": 1,
             "limit_price_cents": 100},
            compliance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_customer_cannot_decide_kyc(
        self, api, customer_fallback_headers,
    ):
        """PRD §4: "POST /brokerage/customers/{customer_id}/kyc/decision
        — Authorized Role(s): ComplianceOfficer".
        PRD §2.1: "If the role is recognised but is not authorised for
        the endpoint per the RBAC table in §4, the request is rejected
        with ERR_FORBIDDEN at HTTP 403."

        Claim: Customer cannot POST KYC decision.
        """
        resp = api.kyc_decision(
            "any-customer-id", {"decision": "VERIFY"},
            customer_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_customer_cannot_fill_order(
        self, api, customer_fallback_headers,
    ):
        """PRD §4: "POST /brokerage/orders/{id}/fill — Authorized
        Role(s): PlatformAdmin".
        PRD §2.1: "If the role is recognised but is not authorised for
        the endpoint per the RBAC table in §4, the request is rejected
        with ERR_FORBIDDEN at HTTP 403."

        Claim: Customer cannot POST /brokerage/orders/{id}/fill.
        """
        resp = api.fill_order(
            "any-order-id", {"execution_price_cents": 100},
            customer_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_customer_cannot_advance_clock(
        self, api, customer_fallback_headers,
    ):
        """PRD §4: "POST /brokerage/_clock/advance — Authorized
        Role(s): PlatformAdmin".
        PRD §2.1: "If the role is recognised but is not authorised for
        the endpoint per the RBAC table in §4, the request is rejected
        with ERR_FORBIDDEN at HTTP 403."

        Claim: Customer cannot POST /brokerage/_clock/advance.
        """
        resp = api.clock_advance(
            {"seconds": 60}, customer_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_compliance_cannot_cancel_order(
        self, api, compliance_headers,
    ):
        """PRD §4: "DELETE /brokerage/orders/{id} — Authorized
        Role(s): Customer".
        PRD §2.1: "If the role is recognised but is not authorised for
        the endpoint per the RBAC table in §4, the request is rejected
        with ERR_FORBIDDEN at HTTP 403."

        Claim: ComplianceOfficer cannot DELETE /brokerage/orders/{id}.
        """
        resp = api.cancel_order("any-id", compliance_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Ownership — PRD §2.1
# ===========================================================================
class TestOwnershipViolation:
    """PRD §2.1: 'A customer who attempts to read or mutate a resource
    that does not chain back to their own Customer.id is rejected with
    ERR_OWNERSHIP_VIOLATION at HTTP 403.'"""

    def test_other_customer_cannot_read_account(
        self, api, customer_other_headers,
    ):
        """PRD §2.1: "A customer who attempts to read or mutate a
        resource that does not chain back to their own Customer.id is
        rejected with ERR_OWNERSHIP_VIOLATION at HTTP 403."

        Claim: a Customer-role caller whose X-User-ID does not equal
        Account.customer_id (chained from Customer.id) is rejected with
        ERR_OWNERSHIP_VIOLATION.
        """
        customer, account = setup_approved_customer_and_account()
        # customer_other_headers has X-User-ID != customer["id"].
        resp = api.get_account(account["id"], customer_other_headers)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value)

    def test_other_customer_cannot_create_order_on_foreign_account(
        self, api, customer_other_headers,
    ):
        """PRD §2.1: "A customer who attempts to read or mutate a
        resource that does not chain back to their own Customer.id is
        rejected with ERR_OWNERSHIP_VIOLATION at HTTP 403."

        Claim: POST /brokerage/orders by a Customer that does not own
        the target Account -> ERR_OWNERSHIP_VIOLATION.
        """
        customer, account = setup_approved_customer_and_account(
            account_type="CASH",
        )
        from test_helpers import create_order_payload
        resp = api.create_order(
            create_order_payload(
                account_id=account["id"],
                instrument_type="EQUITY",
                side="BUY", order_type="LIMIT",
                quantity=1, limit_price_cents=100,
            ),
            customer_other_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value)


# ===========================================================================
# Existence — PRD §2.8
# ===========================================================================
class TestExistence:
    """PRD §2.8: 'A request whose customer_id segment does not resolve
    is rejected with ERR_CUSTOMER_NOT_FOUND (HTTP 404) ... an
    unresolvable account_id yields ERR_ACCOUNT_NOT_FOUND (404) ...'."""

    def test_get_nonexistent_customer(self, api):
        """PRD §2.8: "A request whose customer_id segment does not
        resolve is rejected with ERR_CUSTOMER_NOT_FOUND (HTTP 404)
        before any account, options-approval, order, or ACAT-transfer
        lookup is attempted."

        Claim: unresolvable customer_id -> ERR_CUSTOMER_NOT_FOUND / 404.
        """
        resp = api.get_customer(
            NON_EXISTENT_UUID, TEST_USERS["compliance_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)

    def test_get_nonexistent_account(self, api):
        """PRD §2.8: "Likewise an unresolvable account_id yields
        ERR_ACCOUNT_NOT_FOUND (404)".

        Claim: unresolvable account_id -> ERR_ACCOUNT_NOT_FOUND / 404.
        """
        resp = api.get_account(
            NON_EXISTENT_UUID, TEST_USERS["compliance_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)

    def test_get_nonexistent_options_approval(self, api):
        """PRD §2.8: "an unresolvable options-approval id yields
        ERR_OPTIONS_APPROVAL_NOT_FOUND (404)".

        Claim: unresolvable options-approval id ->
        ERR_OPTIONS_APPROVAL_NOT_FOUND / 404.
        """
        resp = api.get_options_approval(
            NON_EXISTENT_UUID, TEST_USERS["compliance_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_OPTIONS_APPROVAL_NOT_FOUND.value,
        )

    def test_get_nonexistent_order(self, api):
        """PRD §2.8: "an unresolvable order id yields
        ERR_ORDER_NOT_FOUND (404)".

        Claim: unresolvable order id -> ERR_ORDER_NOT_FOUND / 404.
        """
        resp = api.get_order(
            NON_EXISTENT_UUID, TEST_USERS["compliance_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)

    def test_get_nonexistent_acat_transfer(self, api):
        """PRD §2.8: "an unresolvable ACAT-transfer id yields
        ERR_TRANSFER_NOT_FOUND (404)".

        Claim: unresolvable acat-transfer id -> ERR_TRANSFER_NOT_FOUND
        / 404.
        """
        resp = api.get_acat_transfer(
            NON_EXISTENT_UUID, TEST_USERS["compliance_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_FOUND.value)


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2 standard success / error envelope shape."""

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body".

        Claim: a 2xx response carries meta + response_type + data, with
        meta.api_request_id and meta.api_request_timestamp populated.
        """
        customer = create_customer()
        resp = api.get_customer(
            customer["id"], TEST_USERS["platform_admin_headers"],
        )
        # validate_success internally checks the envelope shape.
        data = validate_success(resp, expected_status=200)
        assert data["id"] == customer["id"]
        body = resp.json()
        assert body["response_type"] in ("object", "array")
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format".

        Claim: a 4xx response carries response_type='error' with
        data.error_id and data.message.
        """
        resp = api.get_customer(
            NON_EXISTENT_UUID, TEST_USERS["compliance_headers"],
        )
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip()


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:
    """PRD §2.3 pagination contract."""

    def test_list_accounts_default_pagination_envelope(self, api):
        """PRD §2.3: "The pagination state echoed back in meta carries
        exactly four fields: limit, offset, total_count, and has_more."

        Claim: GET /brokerage/accounts returns meta with the four
        pagination fields.
        """
        customer, account = setup_approved_customer_and_account()
        resp = api.list_accounts(make_customer_headers(customer["id"]))
        data, meta = validate_paginated(resp)
        assert "limit" in meta and "offset" in meta
        assert "total_count" in meta and "has_more" in meta

    def test_list_orders_limit_capped_at_max(self, api):
        """PRD §2.3: "The default value of limit is 10, its minimum is
        1, and its maximum is 100; any request exceeding these bounds
        is rejected with ERR_VALIDATION at HTTP 422."

        Claim: limit > 100 -> ERR_VALIDATION / 422.
        """
        customer, account = setup_approved_customer_and_account()
        resp = api.list_orders(
            make_customer_headers(customer["id"]),
            params={"limit": 101},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_list_orders_offset_negative_rejected(self, api):
        """PRD §2.3: "The default value of offset is 0, and values
        below 0 are likewise rejected."

        Claim: offset < 0 -> ERR_VALIDATION / 422.
        """
        customer, account = setup_approved_customer_and_account()
        resp = api.list_orders(
            make_customer_headers(customer["id"]),
            params={"offset": -1},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
