"""Tenant registration, lease origination defaults, envelope/auth basics, and
optimistic concurrency on lease amendments."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_lease,
    assert_tenant,
    create_lease_payload,
    create_tenant,
    create_tenant_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestTenantRegistration:
    def test_tenant_creation_applies_defaults_and_system_fields(self, api, admin_headers):
        """PRD §3.1: "An `AirportAdmin` registers a concessionaire by supplying its
        `legal_name` and `contact_email`, plus an optional `acdbe_certified` flag —
        defaulted to `false` when omitted — recording whether the tenant is itself an
        ACDBE-certified firm."
        PRD §2.6: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/tenant_creation_applies_defaults_and_system_fields
        """
        res = api.create_tenant(create_tenant_payload(), admin_headers)
        tenant = validate_success(res, 201)
        assert_tenant(tenant)
        assert tenant["acdbe_certified"] is False, (
            f"acdbe_certified must default to false when omitted: {tenant}"
        )
        assert is_valid_uuid(tenant["id"])

    def test_tenant_create_missing_required_returns_invalid_request(
        self, api, admin_headers
    ):
        """PRD §2.8: "Request shape — every required field is present and well-typed,
        else `ERR_INVALID_REQUEST`."
        PRD §3.1: "An `AirportAdmin` registers a concessionaire by supplying its
        `legal_name` and `contact_email`, plus an optional `acdbe_certified` flag —
        defaulted to `false` when omitted — recording whether the tenant is itself an
        ACDBE-certified firm."

        Design: Corner/entities/tenant_create_missing_required_returns_invalid_request
        """
        payload = create_tenant_payload()
        del payload["legal_name"]
        res = api.create_tenant(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestLeaseOrigination:
    def test_lease_creation_initializes_computed_counters(self, api, admin_headers):
        """PRD §3.1: "A new lease is born in `DRAFT` with `arrears_cents` at zero and
        `ti_remaining_cents` equal to the full `ti_allowance_cents`."

        Design: Corner/entities/lease_creation_initializes_computed_counters
        """
        tenant = create_tenant()
        res = api.create_lease(
            create_lease_payload(tenant["id"], ti_allowance_cents=500_000), admin_headers
        )
        lease = validate_success(res, 201)
        assert_lease(lease)
        assert lease["status"] == "DRAFT"
        assert lease["arrears_cents"] == 0
        assert lease["ti_remaining_cents"] == 500_000

    def test_lease_get_not_found_returns_not_found(self, api, admin_headers):
        """PRD §2.8: "Existence — every identifier the request names must resolve,
        else `ERR_NOT_FOUND`."

        Design: Corner/entities/lease_get_not_found_returns_not_found
        """
        res = api.get_lease(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_lease_create_invalid_enum_returns_invalid_enum(self, api, admin_headers):
        """PRD §2.8: "Enum membership — every enum-typed field carries a declared
        member, else `ERR_INVALID_ENUM`. This covers `category`, `kind`, `milestone`,
        `method`, `action`, `reason`, and any status-bearing field supplied by the
        client."

        Design: Corner/entities/lease_create_invalid_enum_returns_invalid_enum
        """
        tenant = create_tenant()
        payload = create_lease_payload(tenant["id"], category="LOUNGE")
        res = api.create_lease(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_ENUM)


class TestAuthenticationAndRbac:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role outside
        this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        res = api.list_tenants(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_analyst_cannot_create_tenant_returns_forbidden(
        self, api, analyst_headers
    ):
        """PRD §2.1: "Once authenticated, the acting role must appear in the
        endpoint's authorized role list as given in §4; otherwise the request is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /concessions/tenants is authorized to AirportAdmin only.

        Design: Corner/rbac/analyst_cannot_create_tenant_returns_forbidden
        """
        res = api.create_tenant(create_tenant_payload(), analyst_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestLeaseAmendmentOcc:
    def test_lease_patch_stale_version_returns_stale_version(self, api, admin_headers):
        """PRD §2.7: "If that value does not match the lease's current `version` —
        meaning the lease's version has advanced since the client last read it — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412), so term edits are
        always based on the currently observed terms."
        PRD §3.1: "A successful amendment increments the lease's `version` by one; an
        amendment attempted after the lease has left `DRAFT` is rejected with
        `ERR_LEASE_STATE_FORBIDS`."

        Design: Corner/cross_cutting_layers/lease_patch_stale_version_returns_stale_version
        """
        tenant = create_tenant()
        lease = validate_success(
            api.create_lease(create_lease_payload(tenant["id"]), admin_headers), 201
        )
        observed_version = lease["version"]

        first = api.patch_lease(
            lease["id"],
            {"expected_lease_version": observed_version, "min_spe_cents": 1100},
            admin_headers,
        )
        amended = validate_success(first, 200)
        assert amended["version"] == observed_version + 1, (
            f"Amendment must increment version by one: "
            f"{observed_version} -> {amended['version']}"
        )

        second = api.patch_lease(
            lease["id"],
            {"expected_lease_version": observed_version, "min_spe_cents": 1200},
            admin_headers,
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)
