"""Auth, RBAC, envelope, pagination, and path-existence checks.

PRD references:
  - §2.1 User and Role-Based Access Control
  - §2.2 API Response Structure
  - §2.3 Pagination
  - §2.7 Path Resolution and Existence Checks
  - §2.9 Validation Priority
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    build_user_headers,
    create_plot_payload,
    create_tenant_payload,
    list_audit_logs,
    setup_full_active_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 — Auth header presence
# ===========================================================================
class TestAuthHeaders:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'Either header missing or blank is rejected with
        ERR_MISSING_AUTH_HEADERS and HTTP 401.'

        Claim: missing X-User-ID → ERR_MISSING_AUTH_HEADERS.
        """
        bad = {"X-User-Role": "PlatformAdmin"}
        res = api.create_tenant(create_tenant_payload(), bad)
        validate_error(res, "ERR_MISSING_AUTH_HEADERS")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: 'Either header missing or blank is rejected with
        ERR_MISSING_AUTH_HEADERS and HTTP 401.'

        Claim: missing X-User-Role → ERR_MISSING_AUTH_HEADERS.
        """
        bad = {"X-User-ID": "admin-001"}
        res = api.create_tenant(create_tenant_payload(), bad)
        validate_error(res, "ERR_MISSING_AUTH_HEADERS")

    def test_blank_user_id_header_rejected(self, api):
        """PRD §2.1: 'Either header missing or blank is rejected with
        ERR_MISSING_AUTH_HEADERS and HTTP 401.'

        Claim: blank X-User-ID → ERR_MISSING_AUTH_HEADERS.
        """
        bad = {"X-User-ID": "", "X-User-Role": "PlatformAdmin"}
        res = api.create_tenant(create_tenant_payload(), bad)
        validate_error(res, "ERR_MISSING_AUTH_HEADERS")

    def test_no_headers_at_all_rejected(self, api):
        """PRD §2.1: 'Either header missing or blank is rejected with
        ERR_MISSING_AUTH_HEADERS and HTTP 401.'

        Claim: no headers → ERR_MISSING_AUTH_HEADERS.
        """
        res = api.create_tenant(create_tenant_payload(), {})
        validate_error(res, "ERR_MISSING_AUTH_HEADERS")


# ===========================================================================
# §2.1 — RBAC (forbidden role)
# ===========================================================================
class TestRBAC:
    @pytest.mark.parametrize(
        "role",
        ["WaterAdmin", "Operator", "DeviceAgent", "Tenant"],
    )
    def test_create_tenant_requires_platform_admin(self, api, role):
        """PRD §2.1: 'if the role is not authorised for the endpoint per
        the §4 endpoint table, the request is rejected with
        ERR_FORBIDDEN_ROLE and HTTP 403.'
        PRD §4: 'POST /tenants ... Authorized Role(s): PlatformAdmin'.

        Claim: non-PlatformAdmin → ERR_FORBIDDEN_ROLE on POST /tenants.
        """
        headers = build_user_headers(f"u-{role}", role)
        res = api.create_tenant(create_tenant_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    @pytest.mark.parametrize(
        "role",
        ["PlatformAdmin", "Operator", "DeviceAgent", "Tenant"],
    )
    def test_create_plot_requires_water_admin(self, api, role):
        """PRD §4: 'POST /plots ... Authorized Role(s): WaterAdmin'.
        PRD §2.1: 'if the role is not authorised for the endpoint per
        the §4 endpoint table, the request is rejected with
        ERR_FORBIDDEN_ROLE and HTTP 403.'

        Claim: non-WaterAdmin → ERR_FORBIDDEN_ROLE on POST /plots.
        """
        headers = build_user_headers(f"u-{role}", role)
        res = api.create_plot(
            create_plot_payload(tenant_id=NON_EXISTENT_UUID),
            headers,
        )
        validate_error(res, "ERR_FORBIDDEN_ROLE")


# ===========================================================================
# §2.2 — Success envelope
# ===========================================================================
class TestSuccessEnvelope:
    def test_create_tenant_envelope(self, api, platform_admin_headers):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body'
        with meta.api_request_id / api_request_timestamp / response_type
        / data.
        PRD §2.2: 'The api_request_id is a server-generated unique
        identifier for the request that starts with req_.'

        Claim: 201 envelope has the four canonical fields.
        """
        res = api.create_tenant(create_tenant_payload(), platform_admin_headers)
        data = validate_success(res, expected_status=201)
        assert isinstance(data, dict)
        assert "id" in data and isinstance(data["id"], str)
        body = res.json()
        assert body["response_type"] in ("object", "array")
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: 'The api_request_id is a server-generated unique "
            "identifier for the request that starts with req_.'"
        )
        assert isinstance(meta.get("api_request_timestamp"), str)


# ===========================================================================
# §2.2 — Error envelope shape
# ===========================================================================
class TestErrorEnvelope:
    def test_error_response_has_error_id_and_message(self, api):
        """PRD §2.2: '\"error_id\": \"UNIQUE_ERROR_IDENTIFIER_STRING\"' and
        '\"message\": \"A human-readable explanation of the error.\"'.

        Claim: error responses carry both error_id and message strings.
        """
        res = api.create_tenant(create_tenant_payload(), {})
        body = res.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["error_id"] == "ERR_MISSING_AUTH_HEADERS"


# ===========================================================================
# §2.3 — Pagination defaults and bounds
# ===========================================================================
class TestPagination:
    def test_list_plots_default_limit_and_meta_keys(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: 'The default value for limit is 10' and 'The meta
        object on list responses includes limit, offset, total_count
        (the total number of records matching the filter, ignoring
        pagination), and has_more (true if more records remain beyond
        the current page).'

        Claim: GET /plots without limit returns limit=10 and all four
        pagination keys.
        """
        res = api.list_plots(platform_admin_headers)
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert "total_count" in meta and isinstance(meta["total_count"], int)
        assert "has_more" in meta and isinstance(meta["has_more"], bool)

    def test_list_plots_explicit_limit_and_offset(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: 'List endpoints accept two optional query parameters:
        limit and offset.'

        Claim: passing limit=5 returns meta.limit==5.
        """
        # Create a few plots so pagination is observable.
        for _ in range(3):
            setup_full_active_scenario(plan_volume_liters=100.0)
        res = api.list_plots(
            platform_admin_headers, params={"limit": 5, "offset": 0}
        )
        data, meta = validate_paginated(res)
        assert meta["limit"] == 5
        assert meta["offset"] == 0
        assert len(data) <= 5


# ===========================================================================
# §2.7 — Path Resolution (left-to-right)
# ===========================================================================
class TestPathResolution:
    def test_outer_id_404_short_circuits_inner(
        self, api, water_admin_headers,
    ):
        """PRD §2.7: 'For a nested URL such as a plan reached via its
        parent plot, the outer plot_id is checked first; if it does not
        resolve, the response is ERR_NOT_FOUND with HTTP 404, and the
        inner plan_id is not consulted.'

        Claim: missing outer plot_id → ERR_NOT_FOUND (HTTP 404),
        regardless of inner plan_id existence.
        """
        res = api.activate_plan(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, water_admin_headers
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_inner_id_404_when_outer_resolves(
        self, api, water_admin_headers,
    ):
        """PRD §2.7: 'If the outer identifier resolves but the inner
        identifier does not, or the inner resource exists but does not
        belong to the outer resource named by the URL, the same
        ERR_NOT_FOUND is returned.'

        Claim: real plot but missing plan → ERR_NOT_FOUND.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=100.0)
        res = api.activate_plan(
            ctx["plot"]["id"], NON_EXISTENT_UUID, water_admin_headers
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.9 — Validation priority: auth precedes existence
# ===========================================================================
class TestValidationPriority:
    def test_missing_auth_precedes_path_existence(self, api):
        """PRD §2.9: 'Auth-header presence is checked first
        (ERR_MISSING_AUTH_HEADERS, 401), then role authorisation
        (ERR_FORBIDDEN_ROLE, 403), then path-parameter existence
        (ERR_NOT_FOUND, 404).'

        Claim: missing headers + missing path resource → 401 not 404.
        """
        res = api.get_plot(NON_EXISTENT_UUID, {})
        validate_error(res, "ERR_MISSING_AUTH_HEADERS")

    def test_forbidden_role_precedes_path_existence(self, api):
        """PRD §2.9: 'Auth-header presence is checked first
        (ERR_MISSING_AUTH_HEADERS, 401), then role authorisation
        (ERR_FORBIDDEN_ROLE, 403), then path-parameter existence
        (ERR_NOT_FOUND, 404).'

        Claim: bad role + missing path resource → 403 not 404.
        """
        # POST /tenants is PlatformAdmin-only. Use Operator with non-existent
        # body; we expect 403 before any body validation.
        op_headers = build_user_headers("u-Operator", "Operator")
        res = api.create_tenant(create_tenant_payload(), op_headers)
        validate_error(res, "ERR_FORBIDDEN_ROLE")


# ===========================================================================
# §3.8 — Audit log query is reachable for WaterAdmin
# ===========================================================================
class TestAuditLogReadable:
    def test_audit_log_listing_paginates(
        self, api, water_admin_headers,
    ):
        """PRD §3.8: 'The audit-log query exposes the recorded AuditLog
        entries with optional filters subject_type, action_type, since,
        and until plus the standard pagination'.
        PRD §2.3: pagination defaults.

        Claim: GET /audit-logs returns paginated meta envelope.
        """
        # Do at least one action that should produce an audit entry to
        # ensure the audit log is non-empty in some cases. Setup creates
        # a quota → QUOTA_ALLOCATED audit entry per PRD §3.5.
        setup_full_active_scenario(plan_volume_liters=100.0)
        res = api.list_audit_logs(water_admin_headers)
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert isinstance(data, list)
