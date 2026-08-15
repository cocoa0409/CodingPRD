"""Site creation contract, response envelope, listing and pagination behavior."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_site,
    create_site,
    create_site_payload,
    create_stock_item,
    set_clock,
    setup_fuel_site,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    CASH_1,
    FDL,
    GM,
    authorize_retail_sale,
    create_pump,
    reload_pump,
)
from test_helpers.factories import create_pump_payload, create_stock_item_payload
from test_helpers.constants import TEST_CLOCK_ISO


class TestSiteCreationContract:
    def test_entity_creation_defaults_applied(self, api):
        """PRD section 3.1: "A new site starts with `water_usage_gallons` at
        zero and all three retail price mirrors —
        `diesel_retail_cents_per_gallon`, `gas_regular_retail_cents_per_gallon`,
        and `def_retail_cents_per_gallon` — null until prices are posted."
        PRD section 3.4: "Members are born `ACTIVE` with `points_balance`
        zero." and "Each member carries a `stack_cap_points` ceiling on the
        points redeemable in a single transaction, defaulting to 500 when not
        supplied."
        PRD section 3.3: "The account is born `ACTIVE` with
        `current_balance_cents` and `rolling_30d_gallons` both at zero."

        Design: Corner/entities/entity_creation_defaults_applied
        """
        from test_helpers.fixtures import create_member, create_fleet

        site = create_site("Site D1")
        assert_site(site)
        site = validate_success(api.get_site(site["id"], GM))
        assert site["water_usage_gallons"] == 0
        assert site["diesel_retail_cents_per_gallon"] is None
        assert site["gas_regular_retail_cents_per_gallon"] is None
        assert site["def_retail_cents_per_gallon"] is None

        member = create_member(full_name="Driver A", email="a@x.com")
        member = validate_success(api.get_loyalty_member(member["id"], GM))
        assert member["stack_cap_points"] == 500
        assert member["points_balance"] == 0
        assert member["status"] == "ACTIVE"

        fleet = create_fleet("Fleet A", 5_000_000, "T1")
        fleet = validate_success(api.get_fleet_account(fleet["id"], GM))
        assert fleet["current_balance_cents"] == 0
        assert fleet["rolling_30d_gallons"] == 0
        assert fleet["status"] == "ACTIVE"

    def test_site_missing_required_field_rejected(self, api):
        """PRD section 2.10: "malformed request bodies, missing required
        fields, invalid enum values, and non-positive quantities are rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)".
        PRD section 3.1: a site is created with "a `name`, the lot's
        `parking_total_spaces`, the `parking_paid_capacity`" among the inputs.

        Design: Corner/entities/entity_missing_required_field_returns_invalid_request
        """
        resp = api.create_site(
            {
                "name": "Site Bad",
                "parking_total_spaces": 60,
                "shower_units_count": 1,
                "laundry_machines_count": 1,
            },
            GM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        data, meta = validate_paginated(api.list_sites(GM))
        assert meta["total_count"] == 0, "rejected create must not persist a site"

    def test_pump_invalid_fuel_type_rejected(self, api):
        """PRD section 3.1: a pump's `fuel_types` draw from "`DIESEL`,
        `GAS_REGULAR`, `GAS_PREMIUM`, or `DEF`" (the declared fuel enum).
        PRD section 2.10: "malformed request bodies, missing required fields,
        invalid enum values, and non-positive quantities are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/entity_invalid_enum_returns_invalid_request
        """
        site = create_site("Site D2")
        resp = api.create_pump(
            site["id"], create_pump_payload(1, ["JET_A"]), FDL
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_missing_site_not_found(self, api):
        """PRD section 2.10: "Existence checks follow: path identifiers are
        validated left to right, each child required to belong to the site or
        parent scope named in the path, and any miss is `ERR_NOT_FOUND`
        (HTTP 404)".

        Design: Corner/entities/entity_get_missing_site_returns_not_found
        """
        resp = api.get_site(NON_EXISTENT_UUID, GM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestListingsAndPagination:
    def test_pump_list_pagination_counts(self, api):
        """PRD section 2.3: "Every list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more` in its `meta` object,
        where `total_count` is the full filtered result size and `has_more`
        reports whether records exist beyond the returned page."

        Design: Corner/entities/entity_list_pagination_counts
        """
        site = create_site("Site D3")
        create_pump(site["id"], 1, ("DIESEL",))
        create_pump(site["id"], 2, ("DIESEL",))

        page1, meta1 = validate_paginated(
            api.list_pumps(site["id"], GM, params={"limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_pumps(site["id"], GM, params={"limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

    def test_pump_scoped_to_owning_site(self, api):
        """PRD section 3.1: "Every record scoped to the property — pumps,
        prices, parking spaces and reservations ... — carries the owning
        site's identifier as `site_id`."
        PRD section 2.10: "each child required to belong to the site or
        parent scope named in the path".

        Design: Corner/entities/entity_fk_child_scoped_to_parent
        """
        site_a = create_site("Site A5")
        site_b = create_site("Site B5")
        pump = create_pump(site_a["id"], 1, ("DIESEL",))

        list_a, meta_a = validate_paginated(api.list_pumps(site_a["id"], GM))
        assert meta_a["total_count"] == 1
        assert list_a[0]["id"] == pump["id"]

        _, meta_b = validate_paginated(api.list_pumps(site_b["id"], GM))
        assert meta_b["total_count"] == 0

    def test_stock_filter_pagination_interaction(self, api):
        """PRD section 3.6: "Stock listings accept `category` and `low_stock`
        filters."
        PRD section 2.3: "Every list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more` in its `meta`
        object".

        Design: Corner/complexity_layers/layer_pagination_filter_interaction
        """
        site = create_site("Site L3")
        for sku in ("R1", "R2", "R3"):
            create_stock_item(
                site["id"], sku=sku, name=sku, category="RETAIL",
                unit_price_cents=100, reorder_point=0, initial_on_hand_quantity=5,
            )
        create_stock_item(
            site["id"], sku="P1", name="P1", category="SHOP_PART",
            unit_price_cents=100, reorder_point=0, initial_on_hand_quantity=5,
        )

        page1, meta1 = validate_paginated(
            api.list_stock_items(
                site["id"], GM, params={"category": "RETAIL", "limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_stock_items(
                site["id"], GM, params={"category": "RETAIL", "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestEnvelope:
    def test_response_envelope_shape(self, api):
        """PRD section 2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their JSON
        body" with meta.api_request_id, meta.api_request_timestamp,
        response_type and data; and "All error API responses (4xx status
        codes) follow this standard envelope format" with response_type
        "error" and data.error_id plus data.message.

        Design: Corner/endpoints/endpoint_response_envelope_shape
        """
        site = create_site("Site E1")

        body = api.get_site(site["id"], GM).json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert body["data"]["id"] == site["id"]

        err_body = api.get_site(NON_EXISTENT_UUID, GM).json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"].strip()

    def test_immediate_visibility_after_authorize(self, api):
        """PRD section 1: "immediate consistency, derived fields recomputed on
        every mutation" — a sale reads back its authorized state at once.
        PRD section 3.2: "The sale is born `AUTHORIZED` with `payment_status`
        `UNPAID`, and its pump cascades to `IN_USE`."

        Design: Corner/consistency_model/consistency_immediate_visibility_after_write
        """
        ctx = setup_fuel_site("Site M1", diesel_cents=385, clock=TEST_CLOCK_ISO)
        sale = authorize_retail_sale(ctx, max_gallons=10.0)

        sale_read = validate_success(api.get_fuel_sale(sale["id"], CASH_1))
        assert sale_read["status"] == "AUTHORIZED"
        assert sale_read["payment_status"] == "UNPAID"

        pump_read = reload_pump(ctx.pumps[0]["id"])
        assert pump_read["status"] == "IN_USE"
