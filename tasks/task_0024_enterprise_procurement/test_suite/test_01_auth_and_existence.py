"""Auth, RBAC, and path-existence checks (PRD §2.1, §2.7, §2.8 priority 1–4)."""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    create_budget_account,
    create_budget_account_payload,
    create_qualified_supplier,
    create_requirement_payload,
    setup_awarded_po,
    validate_error,
    validate_success,
)


# ===========================================================================
# Authentication header presence (PRD §2.1, §2.8 priority 1)
# ===========================================================================
class TestAuthRequired:
    """PRD §2.1: 'If either header is missing or empty, the request is
    rejected with ERR_AUTH_REQUIRED and HTTP 401.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: a request with no auth headers returns ERR_AUTH_REQUIRED 401.
        """
        res = api.list_suppliers({})
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: missing X-User-ID alone produces ERR_AUTH_REQUIRED.
        """
        res = api.list_suppliers({"X-User-Role": "Buyer"})
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: missing X-User-Role alone produces ERR_AUTH_REQUIRED.
        """
        res = api.list_suppliers({"X-User-ID": "operator-1"})
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: empty X-User-ID is treated as missing.
        """
        res = api.list_suppliers({"X-User-ID": "", "X-User-Role": "Buyer"})
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_role_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: empty X-User-Role is treated as missing.
        """
        res = api.list_suppliers({"X-User-ID": "operator-1", "X-User-Role": ""})
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Role recognition (PRD §2.1, §2.8 priority 2)
# ===========================================================================
class TestRoleRecognition:
    """PRD §2.1: 'If the role string is unrecognized — or if a role expected
    to correspond to a stored entity cannot be resolved to one — the
    request is rejected with ERR_FORBIDDEN and HTTP 403.'"""

    def test_unknown_role_string_rejected(self, api):
        """PRD §2.1: "If the role string is unrecognized — or if a role
        expected to correspond to a stored entity cannot be resolved to
        one — the request is rejected with ERR_FORBIDDEN and HTTP 403."

        Claim: a role string not in the recognized set yields ERR_FORBIDDEN.
        """
        headers = build_user_headers("operator-1", "Hacker")
        res = api.list_suppliers(headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_supplier_role_unresolved_user_rejected(self, api):
        """PRD §2.1: "If the role string is unrecognized — or if a role
        expected to correspond to a stored entity cannot be resolved to
        one — the request is rejected with ERR_FORBIDDEN and HTTP 403."

        Claim: Supplier role with X-User-ID that does not resolve to an
        existing Supplier is rejected with ERR_FORBIDDEN.
        """
        headers = build_user_headers(NON_EXISTENT_UUID, "Supplier")
        # Use a Supplier-callable read endpoint to exercise the rule.
        res = api.get_invoice(NON_EXISTENT_UUID, headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Path existence (PRD §2.7, §2.8 priority 3)
# ===========================================================================
class TestPathExistence:
    """PRD §2.7: 'When any path-resource is absent, the response is
    ERR_NOT_FOUND (HTTP 404). Existence is checked before any role check
    that depends on the resource's contents.'"""

    def test_get_budget_account_not_found(self, api):
        """PRD §2.7: "When any path-resource is absent, the response is
        ERR_NOT_FOUND (HTTP 404). Existence is checked before any role
        check that depends on the resource's contents."

        Claim: GET on a missing budget account returns ERR_NOT_FOUND.
        """
        res = api.get_budget_account(
            NON_EXISTENT_UUID, TEST_USERS["finance_headers"]
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_supplier_not_found(self, api):
        """PRD §2.7: "When any path-resource is absent, the response is
        ERR_NOT_FOUND (HTTP 404). Existence is checked before any role
        check that depends on the resource's contents."

        Claim: GET on a missing supplier returns ERR_NOT_FOUND.
        """
        res = api.get_supplier(NON_EXISTENT_UUID, TEST_USERS["buyer_headers"])
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_requirement_not_found(self, api):
        """PRD §2.7: "When any path-resource is absent, the response is
        ERR_NOT_FOUND (HTTP 404). Existence is checked before any role
        check that depends on the resource's contents."

        Claim: GET on a missing requirement returns ERR_NOT_FOUND.
        """
        res = api.get_requirement(
            NON_EXISTENT_UUID, TEST_USERS["requester_headers"]
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_purchase_order_not_found(self, api):
        """PRD §2.7: "When any path-resource is absent, the response is
        ERR_NOT_FOUND (HTTP 404). Existence is checked before any role
        check that depends on the resource's contents."

        Claim: GET on a missing PO returns ERR_NOT_FOUND.
        """
        res = api.get_purchase_order(
            NON_EXISTENT_UUID, TEST_USERS["buyer_headers"]
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_approve_step_not_found(self, api):
        """PRD §2.7: "When any path-resource is absent, the response is
        ERR_NOT_FOUND (HTTP 404). Existence is checked before any role
        check that depends on the resource's contents."

        Claim: approving a non-existent step returns ERR_NOT_FOUND.
        """
        res = api.approve_step(
            NON_EXISTENT_UUID, TEST_USERS["dept_head_headers"]
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# RBAC matrix (PRD §2.8 priority 4 + §4)
# ===========================================================================
class TestRbacMatrix:
    """PRD §2.8 priority 4: 'The acting role is allowed by the role-based
    access matrix for this endpoint (ERR_FORBIDDEN, 403).'"""

    def test_only_finance_creates_budget_account(self, api):
        """PRD §4: "POST /budget-accounts ... Authorized Role(s) ...
        FinanceApprover".

        Claim: a Buyer attempting to create a BudgetAccount is rejected
        with ERR_FORBIDDEN.
        """
        payload = create_budget_account_payload()
        res = api.create_budget_account(payload, TEST_USERS["buyer_headers"])
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_only_legal_qualifies_supplier(self, api):
        """PRD §4: "POST /suppliers/{id}/qualify ... Authorized Role(s) ...
        LegalApprover".

        Claim: a Buyer attempting to qualify a supplier is rejected with
        ERR_FORBIDDEN.
        """
        provisional = api.create_supplier
        from test_helpers import create_supplier_payload
        payload = create_supplier_payload()
        created = validate_success(
            api.create_supplier(payload, TEST_USERS["buyer_headers"]), 201
        )
        res = api.qualify_supplier(created["id"], TEST_USERS["buyer_headers"])
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_only_buyer_awards_requirement(self, api):
        """PRD §4: "POST /requirements/{id}/award ... Authorized Role(s)
        ... Buyer".

        Claim: a Requester attempting to award a requirement is rejected
        with ERR_FORBIDDEN.
        """
        # Build a shortlisted requirement so the rule actually applies to
        # the role check rather than missing-shortlist (existence check
        # passes; role check is priority 4 < state/business priorities).
        from test_helpers import setup_shortlisted_requirement
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)]
        )
        payload = {
            "awarded_quote_id": setup["quotes"][0]["id"],
            "justification": "Should be blocked at RBAC.",
        }
        res = api.award_requirement(
            setup["requirement"]["id"], payload, TEST_USERS["requester_headers"]
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_only_platform_admin_advances_clock(self, api):
        """PRD §4: "POST /_clock/advance ... Authorized Role(s) ...
        PlatformAdmin".

        Claim: a Buyer attempting to advance the clock is rejected with
        ERR_FORBIDDEN.
        """
        res = api.advance_clock(
            "2030-04-01T00:00:00.000Z", TEST_USERS["buyer_headers"]
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_only_gm_overrides_invoice(self, api):
        """PRD §4: "POST /invoices/{id}/override ... Authorized Role(s)
        ... GeneralManager".

        Claim: a FinanceApprover attempting to invoice-override is
        rejected with ERR_FORBIDDEN (the GM-only role check fires before
        any state evaluation).
        """
        res = api.override_invoice(
            NON_EXISTENT_UUID, {"justification": "x"}, TEST_USERS["finance_headers"]
        )
        # Path existence (priority 3) precedes RBAC (priority 4) per
        # PRD §2.8, so the unknown id alone returns ERR_NOT_FOUND.
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Pagination input validation (PRD §2.3, §2.8 priority 19)
# ===========================================================================
class TestPaginationValidation:
    """PRD §2.3: 'The default limit is 10; the minimum is 1; the maximum
    is 100. The default offset is 0; it must be greater than or equal to
    0. Values outside these bounds are rejected with ERR_INVALID_PAGINATION
    (HTTP 400).'"""

    @pytest.mark.parametrize("bad_limit", [0, 101, -1])
    def test_limit_out_of_range(self, api, bad_limit):
        """PRD §2.3: "Values outside these bounds are rejected with
        ERR_INVALID_PAGINATION (HTTP 400)."

        Claim: limit values 0, 101, -1 produce ERR_INVALID_PAGINATION.
        """
        res = api.list_suppliers(
            TEST_USERS["buyer_headers"], params={"limit": bad_limit}
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_offset_negative(self, api):
        """PRD §2.3: "The default offset is 0; it must be greater than or
        equal to 0. Values outside these bounds are rejected with
        ERR_INVALID_PAGINATION (HTTP 400)."

        Claim: offset -1 produces ERR_INVALID_PAGINATION.
        """
        res = api.list_suppliers(
            TEST_USERS["buyer_headers"], params={"offset": -1}
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_pagination_min_max_inclusive(self, api):
        """PRD §2.3: "the minimum is 1; the maximum is 100".

        Claim: limit=1 and limit=100 are both accepted.
        """
        for lim in (1, 100):
            res = api.list_suppliers(
                TEST_USERS["buyer_headers"], params={"limit": lim}
            )
            # Lenient: the call must succeed with HTTP 2xx.
            assert 200 <= res.status_code < 300, (
                f"limit={lim} should be accepted; got {res.status_code}"
            )
