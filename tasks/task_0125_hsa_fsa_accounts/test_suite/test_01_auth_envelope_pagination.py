"""Authentication, role validation, response envelope, and pagination.

Coverage targets (PRD §2.1, §2.2, §2.3, §2.6):
- Missing X-User-ID or X-User-Role header -> ERR_MISSING_AUTH (401).
- Role recognized but lacks endpoint permission -> ERR_FORBIDDEN (403).
- Success / error response envelope shape.
- Pagination parameters limit / offset bounds and meta fields.
- Path-segment NOT_FOUND resolution left-to-right.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_account_holder_payload,
    setup_active_plan_year,
    setup_holder_and_account,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing headers — PRD §2.1
# ===========================================================================
class TestAuthMissing:

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_MISSING_AUTH."

        Claim: omitting both auth headers -> ERR_MISSING_AUTH / 401.
        """
        resp = api._request("GET", "/_clock", headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_MISSING_AUTH."

        Claim: only X-User-ID present -> ERR_MISSING_AUTH.
        """
        resp = api._request(
            "GET", "/_clock", headers={"X-User-ID": "anything"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_MISSING_AUTH."

        Claim: only X-User-Role present -> ERR_MISSING_AUTH.
        """
        resp = api._request(
            "GET", "/_clock",
            headers={"X-User-Role": "PlanAdministrator"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


# ===========================================================================
# RBAC enforcement — PRD §2.1, §4
# ===========================================================================
class TestRbacForbidden:
    """PRD §2.1: 'A request whose X-User-Role is not authorized for the
    target endpoint is rejected with ERR_FORBIDDEN.'"""

    def test_auditor_cannot_create_account_holder(self, api,
                                                  auditor_headers):
        """PRD §4 table: "POST /account-holders ... Authorized Role(s):
        PlanAdministrator." PRD §2.1: "A request whose X-User-Role is
        not authorized for the target endpoint is rejected with
        ERR_FORBIDDEN."

        Claim: Auditor cannot POST /account-holders.
        """
        resp = api.create_account_holder(
            create_account_holder_payload(), auditor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_adjudicator_cannot_create_account_holder(
        self, api, adjudicator_headers,
    ):
        """PRD §4 table: "POST /account-holders ... Authorized Role(s):
        PlanAdministrator." PRD §2.1: "A request whose X-User-Role is
        not authorized for the target endpoint is rejected with
        ERR_FORBIDDEN."

        Claim: ClaimAdjudicator cannot POST /account-holders.
        """
        resp = api.create_account_holder(
            create_account_holder_payload(), adjudicator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_auditor_cannot_freeze_account(self, api, auditor_headers):
        """PRD §4 table: "POST /accounts/{accountId}/freeze ... Authorized
        Role(s): PlanAdministrator." PRD §2.1: "A request whose
        X-User-Role is not authorized for the target endpoint is rejected
        with ERR_FORBIDDEN."

        Claim: Auditor cannot POST /accounts/{id}/freeze.
        """
        _, acct = setup_holder_and_account()
        resp = api.freeze_account(acct["id"], auditor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_account_holder_cannot_create_account(
        self, api, account_holder_fallback_headers,
    ):
        """PRD §4 table: "POST /accounts ... Authorized Role(s):
        PlanAdministrator." PRD §2.1: "A request whose X-User-Role is
        not authorized for the target endpoint is rejected with
        ERR_FORBIDDEN."

        Claim: AccountHolder cannot POST /accounts (admin-exclusive
        per the PRD endpoint table).
        """
        resp = api.create_account(
            {
                "account_holder_id": NON_EXISTENT_UUID,
                "account_type": "HSA",
                "coverage_tier": "SELF_ONLY",
                "year_end_policy": "NONE",
                "account_holder_birth_date": "1980-01-01",
            },
            account_holder_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Success envelope shape — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: success bodies carry meta, response_type, data."""

    def test_get_clock_envelope_shape(self, api, auditor_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body".

        Claim: GET /_clock returns the standard success envelope, with
        meta.api_request_id starting with req_ and response_type
        present.
        """
        resp = api.get_clock(auditor_headers)
        body = resp.json()
        assert body.get("response_type") in {"object", "array"}, (
            f"response_type must be 'object' or 'array', got "
            f"{body.get('response_type')!r}"
        )
        meta = body.get("meta", {})
        api_req_id = meta.get("api_request_id")
        assert isinstance(api_req_id, str), (
            f"api_request_id missing or non-string: {api_req_id!r}"
        )
        assert api_req_id.startswith("req_"), (
            f"api_request_id must start with 'req_', got {api_req_id!r}"
        )
        validate_success(resp, expected_status=200)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:
    """PRD §2.3: limit defaults to 10, min 1, max 100; offset defaults
    to 0; the meta block carries limit, offset, total_count, has_more."""

    def test_list_qualified_expenses_returns_paginated_meta(
        self, api, plan_admin_headers,
    ):
        """PRD §2.3: "The response envelope's meta block populates
        limit, offset, total_count, and has_more for every list
        endpoint."

        Claim: list endpoint returns paginated meta fields.
        """
        resp = api.list_qualified_expenses(plan_admin_headers)
        data, meta = validate_paginated(resp)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, (
                f"meta missing {key}; got keys: {list(meta)}"
            )

    def test_pagination_limit_above_max_rejected(self, api,
                                                 plan_admin_headers):
        """PRD §2.3: "limit defaults to 10, with a minimum of 1 and a
        maximum of 100; requests outside these bounds are rejected with
        ERR_BAD_REQUEST."

        Claim: limit > 100 -> ERR_BAD_REQUEST.
        """
        resp = api.list_qualified_expenses(
            plan_admin_headers, params={"limit": 101},
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_pagination_limit_below_min_rejected(self, api,
                                                 plan_admin_headers):
        """PRD §2.3: "limit defaults to 10, with a minimum of 1 and a
        maximum of 100; requests outside these bounds are rejected with
        ERR_BAD_REQUEST."

        Claim: limit < 1 -> ERR_BAD_REQUEST.
        """
        resp = api.list_qualified_expenses(
            plan_admin_headers, params={"limit": 0},
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_pagination_limit_max_accepted(self, api, plan_admin_headers):
        """PRD §2.3: "limit defaults to 10, with a minimum of 1 and a
        maximum of 100".

        Claim: limit = 100 is accepted (boundary inclusive).
        """
        resp = api.list_qualified_expenses(
            plan_admin_headers, params={"limit": 100},
        )
        _data, _meta = validate_paginated(resp)


# ===========================================================================
# Path-segment NOT_FOUND resolution — PRD §2.6
# ===========================================================================
class TestPathResolution:
    """PRD §2.6: 'Path parameters are resolved left to right'."""

    def test_get_account_unknown_id_returns_not_found(
        self, api, plan_admin_headers,
    ):
        """PRD §2.6: "the outermost identifier (accountId,
        accountHolderId) is checked first, and if it does not resolve
        to an existing row the response is ERR_NOT_FOUND without
        examining the inner segments."

        Claim: GET /accounts/{unknown} -> ERR_NOT_FOUND.
        """
        resp = api.get_account(NON_EXISTENT_UUID, plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_plan_year_with_unknown_account_returns_not_found(
        self, api, plan_admin_headers,
    ):
        """PRD §2.6: "the outermost identifier ... is checked first,
        and if it does not resolve to an existing row the response is
        ERR_NOT_FOUND without examining the inner segments."

        Claim: outer accountId unresolved -> ERR_NOT_FOUND even with
        plausible inner planYearId.
        """
        resp = api.get_plan_year(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_plan_year_with_unknown_inner_returns_not_found(
        self, api, plan_admin_headers,
    ):
        """PRD §2.6: "If the outermost row exists but the inner
        identifier (planYearId, claimId, contributionId, dependentId)
        either does not exist or does not belong to the outer parent,
        the same ERR_NOT_FOUND is returned."

        Claim: outer accountId resolves, inner planYearId is bogus ->
        ERR_NOT_FOUND.
        """
        _, acct, _ = setup_active_plan_year()
        resp = api.get_plan_year(
            acct["id"], NON_EXISTENT_UUID, plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# AccountHolder ownership scoping — PRD §2.1, §2.6
# ===========================================================================
class TestAccountHolderScope:
    """PRD §2.1: 'access to any resource whose owning AccountHolder.id
    does not equal X-User-ID is rejected with ERR_NOT_FOUND'."""

    def test_holder_seeing_other_holders_account_returns_not_found(
        self, api,
    ):
        """PRD §2.1: "access to any resource whose owning
        AccountHolder.id does not equal X-User-ID is rejected with
        ERR_NOT_FOUND (the system does not distinguish 'exists but not
        yours' from 'does not exist' for this role)."

        Claim: an AccountHolder asking about another holder's account
        -> ERR_NOT_FOUND, not ERR_FORBIDDEN.
        """
        from test_helpers import make_account_holder_headers

        _, victim_acct = setup_holder_and_account()
        # A different holder asks for victim's account.
        intruder, _ = setup_holder_and_account()
        intruder_headers = make_account_holder_headers(intruder["id"])
        resp = api.get_account(victim_acct["id"], intruder_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
