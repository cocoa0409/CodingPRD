"""Network build-out, catalog, and lot receipt: defaults, computed receipt
fields, putaway guards, listing/pagination, and single-resource retrieval."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_lot,
    assert_warehouse,
    get_success_data,
    is_valid_uuid,
    make_lot,
    make_product,
    make_warehouse,
    make_zone,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]


class TestWarehouseAndCatalog:
    def test_warehouse_created_with_operational_defaults(self, api):
        """PRD §3.1: "A warehouse begins `OPERATIONAL`; the operator may later suspend it, moving `status` from `OPERATIONAL` to `SUSPENDED` (attempting to suspend one that is not `OPERATIONAL` is rejected with `ERR_WAREHOUSE_NOT_OPERATIONAL`), and resume it from `SUSPENDED` back to `OPERATIONAL` (resuming one that is not `SUSPENDED` fails with `ERR_WAREHOUSE_NOT_SUSPENDED`)."
        PRD §2.4: "`id` (string): a server-minted UUID, with no type prefix."
        PRD §2.4: "`version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including system-driven state transitions applied by cascades."

        Design: Corner/entities/warehouse_created_with_operational_defaults
        """
        resp = api.create_warehouse(
            {"name": "WH-NE", "region_code": "US-NE", "hazmat_certified": True}, OPS
        )
        data = validate_success(resp, 201)
        assert_warehouse(data)
        assert data["status"] == "OPERATIONAL", f"new warehouse must begin OPERATIONAL: {data}"
        assert data["version"] == 1, f"new warehouse version must be 1: {data}"
        assert is_valid_uuid(data["id"]) and "-" in data["id"], "id must be a bare UUID"

    def test_product_create_rejects_invalid_hazard_enum(self, api):
        """PRD §2.10: "Every product declares a `hazard_class` of `NON_HAZARDOUS`, `FLAMMABLE`, `CORROSIVE`, `TOXIC`, or `OXIDIZER`, and a `unit_haz_factor` — the hazmat load units each unit of the product contributes, which must be at least 1, defaults to 1, and is ignored for `NON_HAZARDOUS` products."
        PRD §2.6: "required fields present, types correct, enum members valid, integer fields positive where declared, ISO dates parseable, `effective_until` after `effective_from` where applicable, and no unknown fields, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/product_create_rejects_invalid_hazard_enum
        """
        resp = api.create_product(
            {
                "sku": "BAD-1",
                "name": "Bad",
                "storage_requirement": "AMBIENT",
                "hazard_class": "RADIOACTIVE",
                "max_qty_per_shipment": 10,
                "unit_price_cents": 100,
                "requires_cold_chain": False,
                "shelf_life_days": 30,
            },
            CATALOG,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLotReceipt:
    def test_lot_receipt_computes_sequence_expiry_and_occupancy(self, api):
        """PRD §3.2: "First, a `lot_sequence_number`: one greater than the highest sequence number among all existing lots of the same product regardless of status, or exactly 1 for the product's first receipt. Second, an `expiry_date`: the `manufacture_date` advanced by the product's `shelf_life_days` in calendar days."
        PRD §3.2: "The system also records `received_at` from the logical clock, initializes `quantity_on_hand` equal to `quantity_received`, and zeroes `quantity_reserved`, `quantity_consumed`, and `adjustment_total`."
        PRD §3.2: "A received lot starts `AVAILABLE`, and receipt immediately triggers the backorder waitlist retry described in §3.4."
        PRD §3.1: "A new zone's `occupied_units` starts at 0 and is thereafter maintained by the system as the sum of `quantity_on_hand` over the lots stored in it whose status is `AVAILABLE` or `QUARANTINED`."

        Design: Corner/entities/lot_receipt_computes_sequence_expiry_and_occupancy
        """
        warehouse = make_warehouse(api)
        zone = make_zone(
            api, warehouse["id"], zone_class="REFRIGERATED_2_8", capacity_units=100
        )
        product = make_product(
            api,
            sku="RG-100",
            name="Enzyme Mix",
            storage_requirement="REFRIGERATED_2_8",
            unit_price_cents=20000,
            requires_cold_chain=True,
            shelf_life_days=60,
        )
        resp = api.create_lot(
            {
                "product_id": product["id"],
                "warehouse_id": warehouse["id"],
                "storage_zone_id": zone["id"],
                "quantity_received": 20,
                "manufacture_date": "2026-04-01",
            },
            CLERK,
        )
        lot = validate_success(resp, 201)
        assert_lot(lot)
        assert lot["lot_sequence_number"] == 1, f"first receipt must take sequence 1: {lot}"
        assert lot["expiry_date"] == "2026-05-31", (
            f"2026-04-01 + 60 days must give 2026-05-31: {lot}"
        )
        assert lot["quantity_on_hand"] == 20
        assert lot["status"] == "AVAILABLE"

        zone_after = validate_success(api.get_zone(zone["id"], OPS), 200)
        assert zone_after["occupied_units"] == 20, (
            f"zone occupancy must reflect the receipt: {zone_after}"
        )

    def test_lot_receipt_with_unknown_product_returns_not_found(self, api):
        """PRD §2.6: "The system validates the existence of path identifiers strictly left to right, and body-referenced identifiers in the endpoint's declared input order; the first missing reference yields that resource's per-type 404."
        PRD §2.6: "The mapping is one-to-one: a missing warehouse yields `ERR_WAREHOUSE_NOT_FOUND`, a storage zone `ERR_STORAGE_ZONE_NOT_FOUND`, a product `ERR_PRODUCT_NOT_FOUND`, a lot `ERR_LOT_NOT_FOUND`, a customer `ERR_CUSTOMER_NOT_FOUND`,"

        Design: Corner/entities/lot_receipt_with_unknown_product_returns_not_found
        """
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=100)
        resp = api.create_lot(
            {
                "product_id": NON_EXISTENT_UUID,
                "warehouse_id": warehouse["id"],
                "storage_zone_id": zone["id"],
                "quantity_received": 5,
                "manufacture_date": "2026-04-01",
            },
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)

    def test_zone_capacity_exactly_at_capacity(self, api):
        """PRD §3.2: "the zone must have room — its `occupied_units` plus the incoming quantity may not exceed `capacity_units`, though a receipt that exactly fills the zone is allowed (`ERR_ZONE_CAPACITY_EXCEEDED`)"

        Design: Corner/calculations/zone_capacity_exactly_at_capacity
        """
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=100)
        product = make_product(api, sku="CH-105", unit_price_cents=105)

        first = api.create_lot(
            {
                "product_id": product["id"],
                "warehouse_id": warehouse["id"],
                "storage_zone_id": zone["id"],
                "quantity_received": 100,
                "manufacture_date": "2026-01-15",
            },
            CLERK,
        )
        lot = validate_success(first, 201)
        assert lot["quantity_on_hand"] == 100
        zone_after = validate_success(api.get_zone(zone["id"], OPS), 200)
        assert zone_after["occupied_units"] == 100, (
            "a receipt that exactly fills the zone is allowed"
        )

        overflow = api.create_lot(
            {
                "product_id": product["id"],
                "warehouse_id": warehouse["id"],
                "storage_zone_id": zone["id"],
                "quantity_received": 1,
                "manufacture_date": "2026-01-15",
            },
            CLERK,
        )
        validate_error(overflow, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED)

    def test_lot_receipt_zone_warehouse_mismatch_rejected(self, api):
        """PRD §3.2: "and the declared `storage_zone_id` must actually belong to the declared `warehouse_id` (`ERR_ZONE_WAREHOUSE_MISMATCH`)."

        Design: Corner/validations/lot_receipt_zone_warehouse_mismatch_rejected
        """
        wh1 = make_warehouse(api, name="WH-1", region_code="US-NE")
        wh2 = make_warehouse(api, name="WH-2", region_code="US-W")
        zone = make_zone(api, wh1["id"], zone_class="AMBIENT", capacity_units=100)
        product = make_product(api, sku="CH-105", unit_price_cents=105)
        resp = api.create_lot(
            {
                "product_id": product["id"],
                "warehouse_id": wh2["id"],
                "storage_zone_id": zone["id"],
                "quantity_received": 5,
                "manufacture_date": "2026-01-15",
            },
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_WAREHOUSE_MISMATCH)

    def test_storage_zone_warmer_than_requirement_rejected(self, api):
        """PRD §3.2: "the zone's `zone_class` must be at least as cold as the product's `storage_requirement` per the coldness ordering of §2.9 (`ERR_STORAGE_ZONE_INCOMPATIBLE`)"
        PRD §2.9: "an `AMBIENT` zone may hold only `AMBIENT` product, while an `ULTRACOLD_MINUS_80` zone may hold anything."

        Design: Corner/validations/storage_zone_warmer_than_requirement_rejected
        """
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=100)
        product = make_product(
            api,
            sku="UC-80",
            name="Ultra Freezer Enzyme",
            storage_requirement="ULTRACOLD_MINUS_80",
            unit_price_cents=50000,
            requires_cold_chain=True,
            shelf_life_days=90,
        )
        resp = api.create_lot(
            {
                "product_id": product["id"],
                "warehouse_id": warehouse["id"],
                "storage_zone_id": zone["id"],
                "quantity_received": 5,
                "manufacture_date": "2026-04-01",
            },
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_STORAGE_ZONE_INCOMPATIBLE)

    def test_hazmat_warehouse_not_certified_on_lot_receipt(self, api):
        """PRD §3.2: "Putaway is guarded by four business checks, evaluated after the generic request validations and in this order: the warehouse must be hazmat-certified when the product's `hazard_class` is anything other than `NON_HAZARDOUS` (`ERR_HAZMAT_WAREHOUSE_NOT_CERTIFIED`);"

        Design: Corner/validations/hazmat_warehouse_not_certified_on_lot_receipt
        """
        warehouse = make_warehouse(api, name="WH-PLAIN", hazmat_certified=False)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=100)
        product = make_product(
            api,
            sku="HZ-200",
            name="Solvent X",
            hazard_class="FLAMMABLE",
            unit_haz_factor=2,
            max_qty_per_shipment=100,
            unit_price_cents=10000,
        )
        resp = api.create_lot(
            {
                "product_id": product["id"],
                "warehouse_id": warehouse["id"],
                "storage_zone_id": zone["id"],
                "quantity_received": 5,
                "manufacture_date": "2026-01-15",
            },
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_HAZMAT_WAREHOUSE_NOT_CERTIFIED)


class TestListingAndRetrieval:
    def test_products_list_pagination_limit_offset_has_more(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/products_list_pagination_limit_offset_has_more
        """
        for i in (1, 2, 3):
            make_product(
                api,
                sku=f"P-{i}",
                name=f"P{i}",
                unit_price_cents=100,
                shelf_life_days=30,
                min_remaining_shelf_life_days=7,
            )
        page1, meta1 = validate_paginated(
            api.list_products(OPS, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2, f"page 1 must hold exactly 2 rows: {page1}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_products(OPS, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1, f"page 2 must hold exactly 1 row: {page2}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_lot_list_filters_by_status(self, api):
        """PRD §2.3: "the lot list accepts `product_id`, `warehouse_id`, `storage_zone_id`, `recall_id`, and `status`"

        Design: Corner/endpoints/lot_list_filters_by_status
        """
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(api, sku="CH-105", unit_price_cents=105)
        make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=5,
                 manufacture_date="2026-01-15")
        lot_b = make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=5,
                         manufacture_date="2026-02-15")
        get_success_data(api.quarantine_lot(lot_b["id"], QUALITY))

        data, meta = validate_paginated(api.list_lots(OPS, params={"status": "QUARANTINED"}))
        assert meta["total_count"] == 1, f"only the quarantined lot may match: {data}"
        assert len(data) == 1
        assert data[0]["id"] == lot_b["id"]

    def test_get_single_lot_returns_stored_entity(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §3.2: "First, a `lot_sequence_number`: one greater than the highest sequence number among all existing lots of the same product regardless of status, or exactly 1 for the product's first receipt."
        PRD §3.2: "The system also records `received_at` from the logical clock, initializes `quantity_on_hand` equal to `quantity_received`, and zeroes `quantity_reserved`, `quantity_consumed`, and `adjustment_total`."

        Design: Corner/endpoints/get_single_lot_returns_stored_entity
        """
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=100)
        product = make_product(api, sku="CH-105", unit_price_cents=105)
        lot = make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=7)

        resp = api.get_lot(lot["id"], QUALITY)
        assert resp.json()["response_type"] == "object"
        data = validate_success(resp, 200)
        assert_lot(data)
        assert data["id"] == lot["id"]
        assert data["quantity_on_hand"] == 7
        assert data["lot_sequence_number"] == 1
