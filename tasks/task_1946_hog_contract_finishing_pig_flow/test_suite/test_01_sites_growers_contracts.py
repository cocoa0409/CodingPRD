"""Site, grower, and contract registration: creation defaults, required
fields, uniqueness scopes, pagination, and the site's derived capacity.
"""
import re

from test_helpers import (
    ApiErrorId,
    assert_barn,
    assert_contract,
    assert_grower,
    assert_site,
    create_barn,
    create_grower,
    create_site,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_barn_payload,
    create_contract_payload,
    create_site_payload,
)
from test_helpers.fixtures import ADMIN

_ISO8601_3FRAC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class TestSiteCreation:
    def test_site_creation_returns_defaults_and_system_fields(self, api):
        """PRD §3.1: "A new site starts life `ACTIVE`, and its `site_status`
        can later move `ACTIVE` → `SUSPENDED` when the integrator suspends it".
        PRD §3.2: "A new barn starts `AVAILABLE`, and every barn's capacity
        contributes to its site's `total_capacity_head`, the sum of
        `capacity_head` across the site's barns that are not `OUT_OF_SERVICE`".
        PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created."

        Design: Corner/entities/site_creation_returns_defaults_and_system_fields
        """
        res = api.create_site(
            create_site_payload(name="Prairie", state_code="IA", county="Sioux"),
            ADMIN,
        )
        site = validate_success(res, 201)
        assert_site(site)
        assert site["name"] == "Prairie"
        assert site["state_code"] == "IA"
        assert site["county"] == "Sioux"
        assert site["site_status"] == "ACTIVE"
        # No barns exist yet, so the derived capacity sums to zero.
        assert site["total_capacity_head"] == 0
        assert is_valid_uuid(site["id"])
        assert _ISO8601_3FRAC.match(site["created_at"]), (
            f"created_at must carry three fractional digits: {site['created_at']!r}"
        )
        assert _ISO8601_3FRAC.match(site["updated_at"]), (
            f"updated_at must carry three fractional digits: {site['updated_at']!r}"
        )

    def test_site_create_missing_required_returns_400(self, api):
        """PRD §2.6: "Required fields must be present, enum values must be
        members of their declared sets, integers must honor their minimums ...
        violations fail with `ERR_MALFORMED_FIELD` (HTTP 400)."
        PRD §3.1: "An `IntegratorAdmin` begins by registering each finishing
        **site** with a display `name`, a two-letter `state_code`, and a
        `county`."

        Design: Corner/entities/site_create_missing_required_returns_400
        """
        res = api.create_site({"name": "S", "state_code": "IA"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_MALFORMED_FIELD, expected_status=400)
        # The rejected request persists nothing.
        data, meta = validate_paginated(api.list_sites(ADMIN))
        assert data == [] and meta["total_count"] == 0

    def test_barn_get_not_found_returns_404(self, api):
        """PRD §2.6: "Path identifiers are validated first, in left-to-right
        order as they appear in the URL, and only then are foreign-key
        identifiers in the request body checked; the first missing reference
        fails with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/barn_get_not_found_returns_404
        """
        missing = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
        res = api.get_barn(missing, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_contract_split_defaults_applied(self, api):
        """PRD §3.1: "Three optional percentages declare how maintenance costs
        split between owner and grower, each an integer from 0 to 100:
        `structural_owner_pct` defaulting to 100, `equipment_owner_pct`
        defaulting to 50, and `routine_owner_pct` defaulting to 0."
        PRD §3.1: "A new contract sits in `DRAFT`."

        Design: Corner/entities/contract_split_defaults_applied
        """
        site = create_site(name="S")
        grower = create_grower()
        payload = create_contract_payload(grower["id"], site["id"])
        # Omit the three optional split percentages entirely.
        for key in ("structural_owner_pct", "equipment_owner_pct", "routine_owner_pct"):
            payload.pop(key)
        res = api.create_contract(payload, ADMIN)
        contract = validate_success(res, 201)
        assert_contract(contract)
        assert contract["structural_owner_pct"] == 100
        assert contract["equipment_owner_pct"] == 50
        assert contract["routine_owner_pct"] == 0
        assert contract["contract_status"] == "DRAFT"


class TestUniquenessScopes:
    def test_duplicate_codes_rejected(self, api):
        """PRD §3.1: "Registering a code already in use on another grower is
        rejected with `ERR_DUPLICATE_GROWER_CODE`."
        PRD §3.2: "Each barn is registered under its site with a `barn_code`
        unique within that site — a code collision fails with
        `ERR_DUPLICATE_BARN_CODE` — plus its `capacity_head` ceiling and its
        usable `floor_space_sqft`."

        Design: Corner/errors/duplicate_codes_rejected
        """
        create_grower(grower_code="G-1", legal_name="G", email="g@x.com")
        res = api.create_grower(
            {"legal_name": "G2", "grower_code": "G-1", "email": "g2@x.com"}, ADMIN
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_GROWER_CODE, expected_status=409)

        site1 = create_site(name="S1", county="Sioux")
        site2 = create_site(name="S2", county="Lyon")
        create_barn(site1["id"], barn_code="B1")
        # Same code within the same site collides.
        res = api.create_barn(
            create_barn_payload(
                site1["id"], barn_code="B1", capacity_head=800,
                floor_space_sqft=6400,
            ),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_BARN_CODE, expected_status=409)
        # The same code on a different site is allowed (site-scoped uniqueness).
        res = api.create_barn(
            create_barn_payload(
                site2["id"], barn_code="B1", capacity_head=800,
                floor_space_sqft=6400,
            ),
            ADMIN,
        )
        barn2 = validate_success(res, 201)
        assert_barn(barn2)
        assert barn2["site_id"] == site2["id"]


class TestGrowerPagination:
    def test_pagination_limit_offset_filter(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, accepts a minimum of 1, and is capped at a maximum
        of 100. The `offset` parameter skips a number of items from the front
        of the result set and defaults to 0."
        PRD §3.1: "The grower list can be filtered by `grower_status`."

        Design: Corner/cross_cutting_layers/pagination_limit_offset_filter
        """
        growers = [
            create_grower(
                grower_code=f"G-{i:02d}", legal_name=f"G{i:02d}",
                email=f"g{i:02d}@x.com",
            )
            for i in range(1, 13)
        ]
        get_success_data(api.suspend_grower(growers[11]["id"], ADMIN))

        # Page 1 with defaults: limit 10.
        data, meta = validate_paginated(api.list_growers(ADMIN))
        assert len(data) == 10
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        for g in data:
            assert_grower(g)

        # Page 2 via offset.
        data2, meta2 = validate_paginated(
            api.list_growers(ADMIN, params={"offset": 10})
        )
        assert len(data2) == 2
        assert meta2["offset"] == 10
        assert meta2["has_more"] is False

        # Status filter intersects with pagination.
        data3, meta3 = validate_paginated(
            api.list_growers(ADMIN, params={"grower_status": "SUSPENDED"})
        )
        assert meta3["total_count"] == 1
        assert data3[0]["id"] == growers[11]["id"]


class TestSiteCapacityReconciliation:
    def test_site_capacity_reconciled_on_barn_status_change(self, api):
        """PRD §3.2: "A new barn starts `AVAILABLE`, and every barn's capacity
        contributes to its site's `total_capacity_head`, the sum of
        `capacity_head` across the site's barns that are not `OUT_OF_SERVICE`;
        that total is recomputed whenever a barn is created, marked out of
        service, or returned to service."

        Design: Corner/cross_cutting_layers/site_capacity_reconciled_on_barn_status_change
        """
        site = create_site(name="S")
        create_barn(site["id"], barn_code="B1", capacity_head=1200,
                    floor_space_sqft=9600)
        barn2 = create_barn(site["id"], barn_code="B2", capacity_head=800,
                            floor_space_sqft=6400)

        site0 = validate_success(api.get_site(site["id"], ADMIN), 200)
        assert site0["total_capacity_head"] == 2000

        get_success_data(api.mark_barn_out_of_service(barn2["id"], ADMIN))
        site1 = validate_success(api.get_site(site["id"], ADMIN), 200)
        assert site1["total_capacity_head"] == 1200

        get_success_data(api.return_barn_to_service(barn2["id"], ADMIN))
        site2 = validate_success(api.get_site(site["id"], ADMIN), 200)
        assert site2["total_capacity_head"] == 2000
