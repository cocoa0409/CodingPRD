"""Auth headers, role enforcement, response envelope, pagination.

PRD §2.1, §2.2, §2.3, §2.10 priority 1–2.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_customer,
    create_customer_payload,
    create_evidence,
    create_customer_with_balance,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Header presence (priority 1 / §2.1)
# ===========================================================================
class TestAuthHeadersRequired:
    """PRD §2.1: 'Every request must include two mandatory authentication
    headers: X-User-ID, which carries the caller's user identifier, and
    X-User-Role, which carries the caller's operational capacity. Missing
    or empty headers are rejected with ERR_AUTH_REQUIRED.'
    """

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: 'Missing or empty headers are rejected with
        ERR_AUTH_REQUIRED.'"""
        res = api.create_customer(create_customer_payload(), {})
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'Missing or empty headers are rejected with
        ERR_AUTH_REQUIRED.'"""
        res = api.create_customer(
            create_customer_payload(),
            {"X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: 'Missing or empty headers are rejected with
        ERR_AUTH_REQUIRED.'"""
        res = api.create_customer(
            create_customer_payload(),
            {"X-User-ID": "some-id"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_id_header_rejected(self, api):
        """PRD §2.1: 'Missing or empty headers are rejected with
        ERR_AUTH_REQUIRED.'"""
        res = api.create_customer(
            create_customer_payload(),
            {"X-User-ID": "", "X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Role authorisation (priority 2 / §2.1)
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: 'Once authenticated, the caller must hold the role
    permitted by the target endpoint's role list (see §4); a mismatch
    is rejected with ERR_PERMISSION_DENIED.'
    """

    def test_customer_cannot_bootstrap_customer(self, api):
        """PRD §4: 'POST /customers ... Authorized Role(s): PlatformAdmin'.
        PRD §2.1: 'a mismatch is rejected with ERR_PERMISSION_DENIED.'"""
        res = api.create_customer(
            create_customer_payload(),
            TEST_USERS["customer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PERMISSION_DENIED.value)

    def test_customer_cannot_run_sweep(self, api):
        """PRD §4: '/_sweep/run ... Authorized Role(s): PlatformAdmin'."""
        res = api.run_sweep(TEST_USERS["customer_headers"])
        validate_error(res, ApiErrorId.ERR_PERMISSION_DENIED.value)

    def test_customer_cannot_revoke_certificate(self, api):
        """PRD §4: 'POST /certificates/{id}/revoke ... PlatformAdmin'."""
        res = api.revoke_certificate(
            NON_EXISTENT_UUID, TEST_USERS["customer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PERMISSION_DENIED.value)

    def test_notary_cannot_create_judicial_package(self, api):
        """PRD §4: 'POST /judicial-packages ... JudicialOfficer'."""
        from test_helpers import create_judicial_package_payload
        res = api.create_judicial_package(
            create_judicial_package_payload(evidence_id=NON_EXISTENT_UUID),
            TEST_USERS["notary_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PERMISSION_DENIED.value)

    def test_customer_cannot_list_audit_logs(self, api):
        """PRD §4: 'GET /audit-logs ... PlatformAdmin'."""
        res = api.list_audit_logs(TEST_USERS["customer_headers"])
        validate_error(res, ApiErrorId.ERR_PERMISSION_DENIED.value)


# ===========================================================================
# Customer ownership (priority 3 / §2.1, §2.10)
# ===========================================================================
class TestCustomerOwnershipGuard:
    """PRD §2.10 priority 3: 'When the caller's X-User-Role is Customer,
    ownership of the targeted resource: for POST /evidences/{id}/submit,
    POST /evidences/{id}/resubmit, POST /batches, POST /batches/{id}/submit,
    POST /recharges, and POST /invoices ..., X-User-ID must equal the
    resource's or body's customer_id. Mismatches return
    ERR_PERMISSION_DENIED.'
    """

    def test_recharge_with_wrong_customer_id_rejected(self, api):
        """PRD §2.10 priority 3: ownership mismatch on POST /recharges
        returns ERR_PERMISSION_DENIED."""
        customer = create_customer()
        other_headers = build_user_headers(
            "different-customer-x", "Customer",
        )
        from test_helpers import create_recharge_payload
        res = api.create_recharge(
            create_recharge_payload(
                customer_id=customer["id"], amount_cents=10_000,
            ),
            other_headers,
        )
        validate_error(res, ApiErrorId.ERR_PERMISSION_DENIED.value)

    def test_evidence_create_with_wrong_customer_id_rejected(self, api):
        """PRD §2.10 priority 3: 'POST /evidences ... when the body's
        scope owner is keyed by customer_id, X-User-ID must equal the
        resource's or body's customer_id.'"""
        customer = create_customer()
        other_headers = build_user_headers(
            "stranger-customer", "Customer",
        )
        from test_helpers import create_evidence_payload
        res = api.create_evidence(
            create_evidence_payload(customer_id=customer["id"]),
            other_headers,
        )
        validate_error(res, ApiErrorId.ERR_PERMISSION_DENIED.value)


# ===========================================================================
# Path resource existence (priority 4)
# ===========================================================================
class TestNotFound:
    """PRD §2.10 priority 4: 'Path resource existence, validated
    left-to-right (ERR_NOT_FOUND).'"""

    def test_get_nonexistent_evidence(self, api, admin_headers):
        res = api.get_evidence(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_batch(self, api, admin_headers):
        res = api.get_batch(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_certificate(self, api, admin_headers):
        res = api.get_certificate(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_judicial_package(self, api, judicial_headers):
        res = api.get_judicial_package(
            NON_EXISTENT_UUID, judicial_headers,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_customer(self, api, admin_headers):
        res = api.get_customer(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Body customer_id existence (priority 5)
# ===========================================================================
class TestCustomerNotFoundInBody:
    """PRD §2.10 priority 5: 'Customer.id referenced inside the request
    body exists, on POST /evidences, POST /batches, POST /recharges,
    and POST /invoices (ERR_CUSTOMER_NOT_FOUND).'"""

    def test_recharge_nonexistent_customer(self, api):
        from test_helpers import create_recharge_payload
        headers = make_customer_headers(NON_EXISTENT_UUID)
        res = api.create_recharge(
            create_recharge_payload(
                customer_id=NON_EXISTENT_UUID, amount_cents=10_000,
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)

    def test_evidence_nonexistent_customer(self, api):
        from test_helpers import create_evidence_payload
        headers = make_customer_headers(NON_EXISTENT_UUID)
        res = api.create_evidence(
            create_evidence_payload(customer_id=NON_EXISTENT_UUID),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


# ===========================================================================
# Success-envelope and pagination (§2.2, §2.3)
# ===========================================================================
class TestEnvelopeAndPagination:
    """PRD §2.2 and §2.3."""

    def test_success_envelope_shape(self, api, admin_headers):
        """PRD §2.2: 'All successful API responses ... follow this
        standard envelope format ... meta ... response_type ... data'."""
        res = api.create_customer(create_customer_payload(), admin_headers)
        body = res.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]

    def test_error_envelope_shape(self, api):
        """PRD §2.2: error envelope shape with error_id + message."""
        res = api.create_customer(create_customer_payload(), {})
        body = res.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert body["data"]["error_id"] == ApiErrorId.ERR_AUTH_REQUIRED.value

    def test_list_evidences_pagination(self, api):
        """PRD §2.3: 'limit defaults to 10, with a minimum of 1 and a
        maximum of 100; offset defaults to 0'. Pagination block has
        limit, offset, total_count, has_more."""
        customer = create_customer_with_balance(balance_cents=0)
        # Create a few evidences for this customer.
        for _ in range(3):
            create_evidence(customer)

        headers = make_customer_headers(customer["id"])
        rows, meta = validate_paginated(
            api.list_evidences(headers, params={"customer_id": customer["id"]}),
        )
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] >= 3
        assert "has_more" in meta

    def test_list_evidences_limit_and_offset(self, api):
        """PRD §2.3: limit and offset honored, has_more reflects
        remainder."""
        customer = create_customer_with_balance(balance_cents=0)
        for _ in range(4):
            create_evidence(customer)
        headers = make_customer_headers(customer["id"])

        rows, meta = validate_paginated(api.list_evidences(
            headers, params={"customer_id": customer["id"], "limit": 2},
        ))
        assert len(rows) == 2
        assert meta["limit"] == 2
        assert meta["has_more"] is True

        rows, meta = validate_paginated(api.list_evidences(
            headers, params={
                "customer_id": customer["id"], "limit": 2, "offset": 1000,
            },
        ))
        assert len(rows) == 0
        assert meta["has_more"] is False
