"""Envelope, auth, role, pagination, and 404 probes.

These tests do not depend on domain workflow state. They probe the
cross-cutting rules from PRD §2.1 (auth + role), §2.2 (response
envelope), §2.3 (pagination), §2.5 (left-to-right path lookup).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_plan_payload,
    setup_active_plan_with_open_period,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth headers — PRD §2.1
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: "Every request to the API must carry two mandatory
    headers: `X-User-ID`, which identifies the acting principal, and
    `X-User-Role`, which declares the operational capacity in which
    that principal is acting. A request missing or carrying an empty
    value for either header is rejected with `ERR_AUTH_REQUIRED`."
    """

    def test_missing_x_user_id_is_rejected(self, api):
        """PRD §2.1: "A request missing or carrying an empty value for
        either header is rejected with `ERR_AUTH_REQUIRED`."

        Claim: missing X-User-ID -> ERR_AUTH_REQUIRED (HTTP 401).
        """
        resp = api.list_plans({"X-User-Role": "PlanAdministrator"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_x_user_role_is_rejected(self, api):
        """PRD §2.1: "A request missing or carrying an empty value for
        either header is rejected with `ERR_AUTH_REQUIRED`."

        Claim: missing X-User-Role -> ERR_AUTH_REQUIRED.
        """
        resp = api.list_plans({"X-User-ID": "admin-1"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_x_user_id_is_rejected(self, api):
        """PRD §2.1: "A request missing or carrying an empty value for
        either header is rejected with `ERR_AUTH_REQUIRED`."

        Claim: empty X-User-ID -> ERR_AUTH_REQUIRED.
        """
        resp = api.list_plans(
            {"X-User-ID": "", "X-User-Role": "PlanAdministrator"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_x_user_role_is_rejected(self, api):
        """PRD §2.1: "A request missing or carrying an empty value for
        either header is rejected with `ERR_AUTH_REQUIRED`."

        Claim: empty X-User-Role -> ERR_AUTH_REQUIRED.
        """
        resp = api.list_plans(
            {"X-User-ID": "admin-1", "X-User-Role": ""},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_value_is_rejected(self, api):
        """PRD §2.1: "A request carrying an `X-User-Role` value outside
        the recognized set is rejected with `ERR_AUTH_INVALID_ROLE`."

        Claim: unknown role string -> ERR_AUTH_INVALID_ROLE.
        """
        resp = api.list_plans(
            {"X-User-ID": "admin-1", "X-User-Role": "Wizard"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)


# ===========================================================================
# Role authorization — PRD §2.1 + §4 endpoint table
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "Once headers parse, the system checks whether the
    named role is permitted to invoke the requested operation per the
    role matrix below; a role mismatch is rejected with `ERR_FORBIDDEN`."
    """

    def test_participant_cannot_create_plan(self, api, participant_headers):
        """PRD §4: "POST /plans" is restricted to PlanAdministrator.
        PRD §2.1: "a role mismatch is rejected with `ERR_FORBIDDEN`."

        Claim: Participant POST /plans -> ERR_FORBIDDEN.
        """
        resp = api.create_plan(create_plan_payload(), participant_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_payroll_agent_cannot_run_purchase(
        self, api, payroll_agent_headers,
    ):
        """PRD §4 endpoint table restricts run-purchase to
        PlanAdministrator; PRD §2.1 says role mismatch yields
        `ERR_FORBIDDEN`.

        Claim: PayrollAgent POST run-purchase -> ERR_FORBIDDEN.
        """
        resp = api.run_purchase(NON_EXISTENT_UUID, payroll_agent_headers)
        # Authorization is checked before existence per PRD §2.4
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_tax_authority_cannot_create_disposition(
        self, api, tax_authority_headers,
    ):
        """PRD §4: "POST /dispositions" is restricted to Participant.
        PRD §2.1: TaxAuthority "is a read-only auditor ... no write
        capability anywhere in the API."

        Claim: TaxAuthority POST /dispositions -> ERR_FORBIDDEN.
        """
        resp = api.create_disposition(
            {
                "purchase_id": NON_EXISTENT_UUID,
                "disposition_date": "2025-01-01T00:00:00.000Z",
                "shares_disposed": 1,
                "sale_price_per_share_cents": 100,
            },
            tax_authority_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Path-id lookup — PRD §2.5
# ===========================================================================
class TestPathIdentifierLookup:
    """PRD §2.5: "The request is rejected immediately with `ERR_NOT_FOUND`
    against the first identifier in the path that fails to resolve to
    an existing row."
    """

    def test_get_unknown_plan_returns_not_found(
        self, api, plan_admin_headers,
    ):
        """PRD §2.5: ERR_NOT_FOUND against the first failing identifier.

        Claim: GET /plans/{non-existent} -> ERR_NOT_FOUND (HTTP 404).
        """
        resp = api.get_plan(NON_EXISTENT_UUID, plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_unknown_offering_period_returns_not_found(
        self, api, plan_admin_headers,
    ):
        """PRD §2.5: ERR_NOT_FOUND against the first failing identifier.

        Claim: GET /offering-periods/{non-existent} -> ERR_NOT_FOUND.
        """
        resp = api.get_offering_period(
            NON_EXISTENT_UUID, plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_unknown_purchase_returns_not_found(
        self, api, plan_admin_headers,
    ):
        """PRD §2.5: ERR_NOT_FOUND against the first failing identifier.

        Claim: GET /purchases/{non-existent} -> ERR_NOT_FOUND.
        """
        resp = api.get_purchase(NON_EXISTENT_UUID, plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_grant_fmv_on_unknown_plan_returns_not_found(
        self, api, plan_admin_headers,
    ):
        """PRD §2.5: "The API validates these identifiers strictly
        left-to-right: the system first resolves `plan_id`, then
        `offering_period_id` ..."

        Claim: POST grant-fmv with bad plan_id -> ERR_NOT_FOUND.
        """
        resp = api.record_grant_fmv(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            {"grant_date_fmv_cents": 1000},
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_offering_period_child_under_wrong_plan_is_not_found(
        self, api, plan_admin_headers,
    ):
        """PRD §2.5: "A nested resource that does exist but does not
        belong to the parent named earlier in the path is treated as a
        non-existent child under that parent and likewise yields
        `ERR_NOT_FOUND` against the child identifier."

        Claim: grant-fmv where op_id does not belong to plan_id ->
        ERR_NOT_FOUND.
        """
        # Build two distinct plans with their own op1.
        plan_a, op_a = setup_active_plan_with_open_period(
            initial_clock_iso="2023-01-01T00:00:00.000Z",
            effective_date="2023-06-01T00:00:00.000Z",
        )
        plan_b, op_b = setup_active_plan_with_open_period(
            initial_clock_iso="2023-01-01T00:00:00.000Z",
            effective_date="2023-06-01T00:00:00.000Z",
        )
        resp = api.record_grant_fmv(
            plan_a["id"], op_b["id"],   # mismatched parent
            {"grant_date_fmv_cents": 1000},
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: success envelope carries meta.api_request_id (req_
    prefix), meta.api_request_timestamp (ISO 8601 UTC w/ 3 fractional
    digits), response_type ('object' | 'array'), and data."""

    def test_success_envelope_shape(self, api, plan_admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Claim: 2xx response has meta.api_request_id starting with 'req_'
        and meta.api_request_timestamp is present.
        """
        resp = api.get_clock(plan_admin_headers)
        body = resp.json()
        meta = body["meta"]
        assert "api_request_id" in meta
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert "api_request_timestamp" in meta
        assert body["response_type"] in ("object", "array")
        assert "data" in body

    def test_error_envelope_shape(self, api, plan_admin_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format ... `response_type`: 'error' ...
        `error_id`: ... `message`: A human-readable explanation."

        Claim: 4xx response has response_type='error' and data.error_id +
        data.message present.
        """
        resp = api.get_plan(NON_EXISTENT_UUID, plan_admin_headers)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND.value
        assert isinstance(body["data"].get("message"), str)
        assert "meta" in body
        assert body["meta"]["api_request_id"].startswith("req_")


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:
    """PRD §2.3 pagination defaults and bounds."""

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": -1},
            {"limit": 101},
            {"offset": -1},
        ],
    )
    def test_invalid_pagination_rejected(
        self, api, plan_admin_headers, params,
    ):
        """PRD §2.3: "The `limit` parameter sets the maximum number of
        items to return; when omitted, it defaults to 10, with a minimum
        of 1 and a maximum of 100. The `offset` parameter sets the
        number of items to skip from the start of the result set; when
        omitted, it defaults to 0. Values outside these bounds are
        rejected with `ERR_PAGINATION_INVALID`."

        Claim: out-of-bound limit/offset -> ERR_PAGINATION_INVALID.
        """
        resp = api.list_plans(plan_admin_headers, params=params)
        validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)

    def test_default_limit_and_offset(self, api, plan_admin_headers):
        """PRD §2.3: "Every paginated response includes the following
        fields in the envelope's `meta` object: `limit`, `offset`,
        `total_count`, and `has_more`."

        Claim: list endpoint responds with paginated envelope carrying
        limit/offset/total_count/has_more.
        """
        resp = api.list_plans(plan_admin_headers)
        data, meta = validate_paginated(resp)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert meta["limit"] == 10  # PRD §2.3 default
        assert meta["offset"] == 0
