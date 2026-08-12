"""RBAC denials, authentication, and pagination envelope behavior."""
from test_helpers import (
    ApiErrorId,
    add_schedule_line,
    certify_lease,
    create_billing,
    create_lease,
    create_pool,
    create_property,
    create_property_payload,
    set_clock,
    validate_error,
    validate_paginated,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
ACCT = TEST_USERS["lease_accountant_headers"]
ABSTRACTOR = TEST_USERS["abstractor_headers"]


class TestRoleEnforcement:
    def test_lease_accountant_cannot_create_property(self, api):
        """PRD §2.1: "If the role is recognized but not authorized for the
        target endpoint per the authorization matrix in §4, the request is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."
        (PRD §4 assigns POST /lease-admin/properties to PlatformAdmin only.)

        Design: Corner/endpoints/rbaccountant_cannot_create_property
        """
        resp = api.create_property(create_property_payload(), ACCT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_abstractor_cannot_activate_lease(self, api):
        """PRD §2.1: "If the role is recognized but not authorized for the
        target endpoint per the authorization matrix in §4, the request is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."
        (PRD §4 assigns POST /lease-admin/leases/{lease_id}/activate to
        PortfolioManager only.)

        Design: Corner/endpoints/abstractor_cannot_activate_lease
        """
        set_clock()
        prop = create_property()
        lease = create_lease(prop["id"])
        certify_lease(lease["id"])
        add_schedule_line(lease["id"])
        pool = create_pool(prop["id"])
        create_billing(lease["id"], pool["id"])
        resp = api.activate_lease(lease["id"], ABSTRACTOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_missing_auth_header(self, api):
        """PRD §2.1: "If the `X-User-Role` header is missing or carries a value
        outside this declared set, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/endpoints/missing_auth_header
        """
        # X-User-ID present, X-User-Role absent.
        resp = api.list_properties(headers={"X-User-ID": "test-no-role-1"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestPagination:
    def test_pagination_limit_offset(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §3.1: "The lease collection supports filtering by `property_id`,
        `status`, `abstraction_status`, or `billing_posture`, and a property's
        leases can also be listed as a sub-resource of the property itself."

        Design: Corner/cross_cutting_layers/pagination_limit_offset
        """
        set_clock()
        prop = create_property()
        for tenant, suite in (("A", "100"), ("B", "200"), ("C", "300")):
            create_lease(
                prop["id"], tenant_legal_name=tenant, suite=suite,
                leased_sf=1000, base_rent_annual_cents=100,
                recovery_structure="GROSS", pro_rata_share_bps=0,
            )
        data, meta = validate_paginated(
            api.list_leases(PM, params={"property_id": prop["id"],
                                        "limit": 2, "offset": 0})
        )
        assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
        assert meta["total_count"] == 3, (
            f"three leases exist, expected total_count 3, got {meta['total_count']}"
        )
        assert meta["has_more"] is True, (
            "a third lease remains beyond the first page"
        )
        assert meta["limit"] == 2
        assert meta["offset"] == 0
