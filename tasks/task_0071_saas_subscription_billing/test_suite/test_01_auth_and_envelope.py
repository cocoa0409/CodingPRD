"""Auth headers, role enforcement, response envelope, pagination, and
cross-tenant isolation.

PRD §2.1, §2.2, §2.3, §2.7, §2.11 priorities 1–4.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PA, BO,
    TEST_USERS,
    create_tenant,
    create_tenant_payload,
    create_jurisdiction,
    create_package,
    make_tenant_admin_headers,
    setup_active_subscription,
    setup_tenant_with_jurisdiction,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth header presence (PRD §2.1)
# ===========================================================================
class TestAuthHeadersRequired:
    """PRD §2.1: 'The X-User-Role header declares which role the request
    is acting under, and must be one of PlatformAdmin, BillingOperator,
    or TenantAdmin — any other value, or a missing header, is rejected
    with ERR_AUTH_MISSING_ROLE (HTTP 401). The X-User-ID header
    identifies the specific principal acting under that role and is
    likewise mandatory; absence yields ERR_AUTH_MISSING_USER (HTTP 401).'
    """

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: 'any other value, or a missing header, is rejected
        with ERR_AUTH_MISSING_ROLE (HTTP 401).'"""
        res = api.create_tenant(
            create_tenant_payload(),
            {"X-User-ID": "some-id"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING_ROLE.value)

    def test_unrecognized_role_rejected(self, api):
        """PRD §2.1: 'must be one of PlatformAdmin, BillingOperator, or
        TenantAdmin — any other value, or a missing header, is rejected
        with ERR_AUTH_MISSING_ROLE (HTTP 401).'"""
        res = api.create_tenant(
            create_tenant_payload(),
            {"X-User-ID": "ghost", "X-User-Role": "Sysadmin"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING_ROLE.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'The X-User-ID header... is likewise mandatory;
        absence yields ERR_AUTH_MISSING_USER (HTTP 401).'"""
        res = api.create_tenant(
            create_tenant_payload(),
            {"X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING_USER.value)


# ===========================================================================
# Role authorization (PRD §2.1, §4)
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: 'When both headers are present but the declared role is
    not permitted to invoke the requested endpoint per the RBAC matrix
    in §4, the system rejects with ERR_FORBIDDEN (HTTP 403).'
    """

    def test_billing_operator_cannot_create_tenant(self, api):
        """PRD §4: 'POST /tenants — Create a tenant — PlatformAdmin'."""
        res = api.create_tenant(create_tenant_payload(), BO)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_tenant_admin_cannot_create_tenant(self, api):
        """PRD §4: 'POST /tenants — Create a tenant — PlatformAdmin'."""
        res = api.create_tenant(
            create_tenant_payload(),
            TEST_USERS["tenant_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_billing_operator_cannot_create_package(self, api):
        """PRD §4: 'POST /packages — Define a new PackageVersion —
        PlatformAdmin'."""
        res = api.create_package(
            {"package_code": "X", "version_number": 1,
             "package_type": "TIERED",
             "effective_from": "2030-01-01T00:00:00.000Z",
             "base_price_cents": 100, "currency": "USD",
             "billing_cycle": "MONTHLY", "pricing_model": "PREPAID",
             "included_quotas": {}, "tiered_brackets": [],
             "overage_rates": {}, "addons": []},
            BO,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Cross-tenant isolation (PRD §2.1, §2.6)
# ===========================================================================
class TestCrossTenantIsolation:
    """PRD §2.1: 'A TenantAdmin therefore cannot read or mutate any
    tenant other than its own, regardless of any other authorization
    rule.'
    """

    def test_tenant_admin_with_wrong_id_rejected_on_get(self, api):
        """PRD §2.1: 'ownership checks on any tenant-scoped resource
        compare the path's tenant_id to X-User-ID, and a mismatch yields
        ERR_CROSS_TENANT_ACCESS (HTTP 403).'"""
        t = create_tenant()
        other = create_tenant()
        # TenantAdmin headers carrying a DIFFERENT tenant id than the path
        wrong_headers = make_tenant_admin_headers(other["id"])
        res = api.get_tenant(t["id"], wrong_headers)
        validate_error(res, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value)

    def test_tenant_admin_with_matching_id_succeeds(self, api):
        """PRD §2.1: 'ownership checks on any tenant-scoped resource
        compare the path's tenant_id to X-User-ID' — matching id passes."""
        t = create_tenant()
        res = api.get_tenant(t["id"], make_tenant_admin_headers(t["id"]))
        data = validate_success(res, 200)
        assert data["id"] == t["id"]


# ===========================================================================
# Existence (PRD §2.7)
# ===========================================================================
class TestExistenceErrors:
    """PRD §2.7: 'Routes that nest resources under a parent ... validate
    path parameters left-to-right. The tenant referenced by tenant_id is
    resolved first; a missing tenant yields ERR_TENANT_NOT_FOUND (HTTP
    404). Only then is the inner resource resolved: a missing or
    cross-tenant subscription yields ERR_SUBSCRIPTION_NOT_FOUND, a
    missing or cross-tenant invoice yields ERR_INVOICE_NOT_FOUND.'
    """

    def test_get_nonexistent_tenant_returns_not_found(self, api):
        """PRD §2.7: 'a missing tenant yields ERR_TENANT_NOT_FOUND
        (HTTP 404).'"""
        res = api.get_tenant(NON_EXISTENT_UUID, PA)
        validate_error(res, ApiErrorId.ERR_TENANT_NOT_FOUND.value)

    def test_get_subscription_under_nonexistent_tenant(self, api):
        """PRD §2.7: 'The tenant referenced by tenant_id is resolved
        first; a missing tenant yields ERR_TENANT_NOT_FOUND.'"""
        res = api.get_subscription(NON_EXISTENT_UUID, NON_EXISTENT_UUID, PA)
        validate_error(res, ApiErrorId.ERR_TENANT_NOT_FOUND.value)

    def test_get_nonexistent_subscription_under_real_tenant(self, api):
        """PRD §2.7: 'a missing or cross-tenant subscription yields
        ERR_SUBSCRIPTION_NOT_FOUND.'"""
        t = create_tenant()
        res = api.get_subscription(t["id"], NON_EXISTENT_UUID, PA)
        validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value)

    def test_subscription_belonging_to_other_tenant_is_not_found(self, api):
        """PRD §2.7: 'The inner resource must belong to the path tenant
        — a subscription whose tenant_id does not equal the path's
        tenant_id is treated as not-found, never as forbidden.'"""
        t1, _pkg, sub = setup_active_subscription()
        t2 = create_tenant()
        # Use PlatformAdmin so the cross-tenant rule does not pre-empt
        # the existence check (PRD §2.7 applies left-to-right).
        res = api.get_subscription(t2["id"], sub["id"], PA)
        validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value)

    def test_create_tenant_with_unknown_jurisdiction_rejected(self, api):
        """PRD §2.7: 'references to a tax jurisdiction whose
        jurisdiction_code is not registered yield
        ERR_JURISDICTION_NOT_FOUND.'"""
        res = api.create_tenant(
            create_tenant_payload(
                jurisdiction_code="ZZ-NONEXIST-99",
            ),
            PA,
        )
        validate_error(res, ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value)


# ===========================================================================
# Response envelope (PRD §2.2)
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: 'All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body...'
    """

    def test_create_jurisdiction_returns_object_envelope(self, api):
        """PRD §2.2: 'The response_type is either "object" for a single
        resource or "array" for a list of resources.'"""
        res = api.create_jurisdiction(
            {"jurisdiction_code": "ENV-CHECK-" + "test01",
             "tax_rate_bps": 0, "rounding_mode": "TOTAL"},
            PA,
        )
        # 201 per PRD §4 listing
        validate_success(res, 201)
        body = res.json()
        assert body.get("response_type") == "object"
        meta = body.get("meta", {})
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: 'a server-generated unique identifier for the "
            "request that starts with `req_`.'"
        )

    def test_list_packages_returns_paginated_envelope(self, api):
        """PRD §2.3: 'The response meta block on every list endpoint
        reports limit, offset, total_count, and has_more.'"""
        # Ensure at least one package exists
        create_package()
        res = api.list_packages(PA, params={"limit": 5, "offset": 0})
        data, meta = validate_paginated(res)
        assert isinstance(data, list)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta missing '{key}'"
        assert meta["limit"] == 5
        assert meta["offset"] == 0
        assert isinstance(meta["total_count"], int)


# ===========================================================================
# Pagination defaults and bounds (PRD §2.3)
# ===========================================================================
class TestPaginationBounds:
    """PRD §2.3: 'The limit parameter defaults to 10, has a minimum of
    1, and may not exceed 100; the offset parameter defaults to 0 and
    has no upper bound.'
    """

    def test_default_limit_is_ten(self, api):
        """PRD §2.3: 'The limit parameter defaults to 10.'"""
        # Make sure there are multiple packages so default limit is
        # actually exercised.
        for _ in range(3):
            create_package()
        res = api.list_packages(PA, params=None)
        _data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
