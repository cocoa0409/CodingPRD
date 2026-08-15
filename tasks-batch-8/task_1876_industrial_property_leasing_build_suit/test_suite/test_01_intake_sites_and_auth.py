"""Requirement intake, site inventory, authentication and RBAC, and the
market-survey list (PRD §2.1, §2.3, §2.4, §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_site,
    assert_site_sf_invariant,
    assert_tenant_requirement,
    create_requirement,
    create_requirement_payload,
    create_site,
    create_site_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

LM = TEST_USERS["leasing_manager_headers"]
REP_1 = TEST_USERS["tenant_rep_1_headers"]
REP_2 = TEST_USERS["tenant_rep_2_headers"]


class TestAuthenticationAndRoles:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        value outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_sites(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_tenantrep_cannot_create_site_returns_forbidden(self, api):
        """PRD §2.1: "A request whose role is not authorized for the endpoint
        it targets is rejected with `ERR_FORBIDDEN` (HTTP 403)" and
        "`LeasingManager` — the developer-side leasing lead: registers sites".

        Design: Corner/validations/tenantrep_cannot_create_site_returns_forbidden
        """
        resp = api.create_site(create_site_payload(), REP_1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_other_rep_cannot_withdraw_requirement_returns_forbidden(self, api):
        """PRD §3.1: "it becomes `WITHDRAWN` when the owning representative
        withdraws it — ownership here means `X-User-ID` equals the
        requirement's `tenant_rep_id`, failing which the call is
        `ERR_FORBIDDEN`."

        Design: Corner/validations/other_rep_cannot_withdraw_requirement_returns_forbidden
        """
        req = create_requirement(REP_1)
        resp = api.withdraw_tenant_requirement(req["id"], REP_2)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        # The requirement is untouched by the rejected call.
        after = validate_success(api.get_tenant_requirement(req["id"], LM))
        assert after["status"] == "ACTIVE", (
            f"Requirement must remain ACTIVE after a forbidden withdraw, "
            f"got {after['status']}"
        )


class TestRequirementIntake:
    def test_requirement_create_missing_required_field_returns_invalid_request(
        self, api
    ):
        """PRD §2.8: "Required fields must be present with correct types on
        every creation and action call — otherwise `ERR_INVALID_REQUEST`
        (400)." PRD §3.1: "The intake payload names the prospective tenant
        (`tenant_name`), the use (`use_type`, one of `DISTRIBUTION`,
        `MANUFACTURING`, `COLD_STORAGE`, or `R_AND_D`)".

        Design: Corner/entities/requirement_create_missing_required_field_returns_invalid_request
        """
        payload = create_requirement_payload()
        del payload["use_type"]
        resp = api.create_tenant_requirement(payload, REP_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_requirement_initial_state_active(self, api):
        """PRD §3.1: "The creating representative's header is stamped into
        `tenant_rep_id`, which becomes the ownership token for every later
        rep-scoped write on the record, and the requirement begins life
        `ACTIVE`."

        Design: Corner/state_machines/requirement_initial_state_active
        """
        resp = api.create_tenant_requirement(create_requirement_payload(), REP_1)
        data = validate_success(resp, 201)
        assert_tenant_requirement(data)
        assert data["status"] == "ACTIVE", (
            f"A newly created requirement must start ACTIVE, "
            f"got {data['status']}"
        )
        assert data["tenant_rep_id"] == "rep-001"

    def test_requirement_withdraw_twice_returns_invalid_state(self, api):
        """PRD §2.8: "The requested transition must be declared from the
        entity's current status; terminal states accept no further
        transitions — otherwise `ERR_INVALID_STATE` (409)." PRD §3.1: "A
        requirement ends in one of two terminal states."

        Design: Corner/state_machines/requirement_withdraw_twice_returns_invalid_state
        """
        req = create_requirement(REP_1)
        first = validate_success(api.withdraw_tenant_requirement(req["id"], REP_1))
        assert first["status"] == "WITHDRAWN"
        resp = api.withdraw_tenant_requirement(req["id"], REP_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_requirement_get_not_found_returns_404(self, api):
        """PRD §2.8: "Every identifier in the URL path and every foreign-key
        identifier in the request body (`requirement_id`, `site_id`,
        `plan_id`, `loi_id`, `land_site_id`) must resolve to an existing
        record, validated left to right with path identifiers before body
        identifiers — otherwise `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/requirement_get_not_found_returns_404
        """
        resp = api.get_tenant_requirement(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", LM
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSiteInventory:
    def test_site_create_invalid_enum_returns_invalid_enum(self, api):
        """PRD §2.8: "Enum-typed inputs — `use_type`, `parcel_type`,
        `pricing_method`, `milestone_type`, `review_type`, `outcome`,
        `commission_basis` — must carry a declared member — otherwise
        `ERR_INVALID_ENUM` (400)." PRD §3.1: "the `parcel_type` (`EXISTING`
        for a standing building, `LAND_BANK` for banked land held for
        expansion or build-to-suit)".

        Design: Corner/entities/site_create_invalid_enum_returns_invalid_enum
        """
        payload = create_site_payload(
            site_name="Swamp Parcel", submarket="High Desert",
            parcel_type="SWAMP", total_sf=500000, clear_height_ft=0,
            dock_doors=0, power_amps=0, yard_depth_ft=0, asking_rate_psf=2.00,
        )
        resp = api.create_site(payload, LM)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)

    def test_site_create_system_fields_input_ignored(self, api):
        """PRD §2.4: "`id` is a server-minted UUID with no type prefix."
        PRD §3.1: "A newly registered site starts `LISTED` with `reserved_sf`
        at zero".

        Design: Corner/entities/site_create_system_fields_input_ignored
        """
        client_id = "00000000-0000-0000-0000-000000000099"
        payload = create_site_payload()
        payload["id"] = client_id
        payload["version"] = 99
        payload["status"] = "LEASED"
        resp = api.create_site(payload, LM)
        data = validate_success(resp, 201)
        assert_site(data)
        assert data["id"] != client_id, (
            "The server must mint its own UUID id; a client-supplied id "
            "must not be honored"
        )
        assert data["status"] == "LISTED", (
            f"A newly registered site starts LISTED regardless of "
            f"client-supplied status, got {data['status']}"
        )

    def test_site_available_sf_defaults_on_create(self, api):
        """PRD §3.1: "A newly registered site starts `LISTED` with
        `reserved_sf` at zero; `available_sf` is read-only and always equals
        `total_sf` minus `reserved_sf`, recomputed whenever `reserved_sf`
        changes."

        Design: Corner/entities/site_available_sf_defaults_on_create
        """
        resp = api.create_site(create_site_payload(total_sf=200000), LM)
        data = validate_success(resp, 201)
        assert_site(data)
        assert data["status"] == "LISTED"
        assert data["reserved_sf"] == 0
        assert data["available_sf"] == 200000, (
            f"available_sf must equal total_sf on create, "
            f"got {data['available_sf']}"
        )
        assert_site_sf_invariant(data)

    def test_sites_list_pagination_and_submarket_filter(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        which defaults to 10 with a minimum of 1 and a maximum of 100, and
        `offset`, which defaults to 0." PRD §3.1: "The market-survey list
        supports filtering by `submarket`, `status`, and `parcel_type`, with
        standard pagination".

        Design: Corner/entities/sites_list_pagination_and_submarket_filter
        """
        create_site(site_name="Ridge Logistics Center", submarket="Inland Empire")
        create_site(
            site_name="Summit Logistics Center", submarket="Inland Empire",
            total_sf=150000, clear_height_ft=32, dock_doors=16,
            power_amps=3000, yard_depth_ft=150,
            environmental_phase="PHASE_II_REQUIRED", asking_rate_psf=5.50,
        )
        create_site(
            site_name="Pacific BTS Site", submarket="Antelope Valley",
            zoning_designation="M-2", asking_rate_psf=13.20,
        )

        page0, meta0 = validate_paginated(
            api.list_sites(
                REP_1, params={"submarket": "Inland Empire", "limit": 1, "offset": 0}
            )
        )
        assert meta0["total_count"] == 2, (
            f"submarket filter must yield total_count 2, got "
            f"{meta0['total_count']}"
        )
        assert meta0["has_more"] is True
        assert len(page0) == 1
        assert page0[0]["submarket"] == "Inland Empire"

        page1, meta1 = validate_paginated(
            api.list_sites(
                REP_1, params={"submarket": "Inland Empire", "limit": 1, "offset": 1}
            )
        )
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is False
        assert len(page1) == 1
        assert page1[0]["submarket"] == "Inland Empire"
        assert page0[0]["id"] != page1[0]["id"]
