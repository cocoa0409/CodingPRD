"""Vendors, product SKUs, DSD receiving lots, listing/pagination, and RBAC on
merchandising writes."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_vendor_payload, create_product_payload,
    create_approved_vendor, create_pending_vendor, create_product,
    assert_vendor, TEST_USERS,
)

INVENTORY = TEST_USERS["inventory_manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def test_create_vendor_mints_system_fields_starts_pending(api, inventory_manager_headers):
    """PRD §2.4: "Each has an `id`, a server-minted UUID that serves as identity only
    and carries no type prefix." PRD §3.2: "A vendor begins in `PENDING`."

    Design: Corner/entities/system_ids_generated_input_ignored
    """
    res = api.create_vendor(create_vendor_payload(name="Sunrise Bakery"),
                            inventory_manager_headers)
    vendor = validate_success(res, 201)
    assert_vendor(vendor)
    assert vendor["status"] == "PENDING"
    assert vendor["version"] == 1


def test_product_missing_department_rejected(api, inventory_manager_headers):
    """PRD §2.9: "Malformed bodies, missing required fields, or bad enum/type values
    are rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/product_missing_required_department_returns_invalid_request
    """
    vendor = create_approved_vendor()
    payload = create_product_payload(vendor["id"], sku="X", name="No Dept")
    del payload["department"]
    res = api.create_product(payload, inventory_manager_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_product_invalid_department_enum_rejected(api, inventory_manager_headers):
    """PRD §2.9: "Malformed bodies, missing required fields, or bad enum/type values
    are rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/product_invalid_enum_department_rejected
    """
    vendor = create_approved_vendor()
    res = api.create_product(
        create_product_payload(vendor["id"], sku="X", name="Bad Dept", department="FROZEN"),
        inventory_manager_headers,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_vendor_suspend_then_reapprove_cycle(api):
    """PRD §3.2: "`PENDING` may be approved to `APPROVED`, `APPROVED` may be suspended
    to `SUSPENDED`, and a `SUSPENDED` vendor may be restored to `APPROVED`."

    Design: Corner/state_machines/vendor_suspend_then_reapprove_cycle
    """
    vendor = validate_success(api.create_vendor(create_vendor_payload(name="Cycle Co"), INVENTORY), 201)
    approved = validate_success(api.set_vendor_status(vendor["id"], {"status": "APPROVED"}, INVENTORY), 200)
    assert approved["status"] == "APPROVED"
    suspended = validate_success(api.set_vendor_status(vendor["id"], {"status": "SUSPENDED"}, INVENTORY), 200)
    assert suspended["status"] == "SUSPENDED"
    reapproved = validate_success(api.set_vendor_status(vendor["id"], {"status": "APPROVED"}, INVENTORY), 200)
    assert reapproved["status"] == "APPROVED"


def test_derived_product_fields_reconciled_on_lot_post(api):
    """PRD §3.2: "On posting, the lot's `qty_on_hand` is set to its `received_qty`,
    while `qty_sold` and `qty_shrunk` are set to zero, and the product's
    `qty_on_hand_total`, `needs_reorder`, and `inventory_value_cents` are recomputed."

    Design: Corner/cross_cutting_complexity_layers/derived_inventory_value_on_lot_post
    """
    vendor = create_approved_vendor()
    product = create_product(vendor["id"], sku="FLR", name="Flour", reorder_point=2, reorder_qty=10)
    lot = validate_success(
        api.create_inventory_lot(
            {"product_id": product["id"], "vendor_id": vendor["id"],
             "received_qty": 5, "unit_cost_cents": 200}, INVENTORY), 201)
    validate_success(api.post_inventory_lot(lot["id"], INVENTORY), 200)

    product_after = validate_success(api.get_product(product["id"], INVENTORY), 200)
    assert product_after["qty_on_hand_total"] == 5
    assert product_after["inventory_value_cents"] == 1000
    assert product_after["needs_reorder"] is False


def test_lots_filtered_by_product_id(api):
    """PRD §4: "GET | `/coop/inventory-lots` | List lots; filter by product_id and/or
    vendor_id | Any".

    Design: Corner/endpoints/fk_reverse_lots_filtered_by_product
    """
    vendor = create_approved_vendor()
    product = create_product(vendor["id"], sku="A", name="A")
    lot = validate_success(
        api.create_inventory_lot(
            {"product_id": product["id"], "vendor_id": vendor["id"],
             "received_qty": 5, "unit_cost_cents": 50}, INVENTORY), 201)

    res = api.list_inventory_lots(INVENTORY, params={"product_id": product["id"]})
    data, _meta = validate_paginated(res)
    assert any(l["id"] == lot["id"] for l in data), "listing must include the product's lot"


def test_products_list_pagination(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/products_list_pagination
    """
    vendor = create_approved_vendor()
    create_product(vendor["id"], sku="A", name="A", base_price_cents=100, reorder_qty=1)
    create_product(vendor["id"], sku="B", name="B", base_price_cents=100, reorder_qty=1)

    res = api.list_products(INVENTORY, params={"vendor_id": vendor["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_cashier_cannot_create_product(api):
    """PRD §2.1: "When a role is authenticated but not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED`." PRD §4
    restricts POST `/coop/products` to InventoryManager.

    Design: Corner/rbac/cashier_cannot_create_product
    """
    vendor = create_approved_vendor()
    res = api.create_product(
        create_product_payload(vendor["id"], sku="X", name="X", base_price_cents=100, reorder_qty=1),
        CASHIER,
    )
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


class TestLotPostRequiresApprovedVendor:
    """DSD receiving requires an APPROVED vendor (PRD §3.2)."""

    def test_post_lot_with_pending_vendor_rejected(self, api):
        """PRD §3.2: "Posting is gated by three conditions: the lot must be in `DRAFT`
        (else `ERR_LOT_NOT_DRAFT`), the lot's vendor must be `APPROVED` (else
        `ERR_VENDOR_NOT_APPROVED`), and the lot's product must not be `DISCONTINUED`."

        Design: Difficulty/cross_entity_state_dependency/cesd_lot_post_requires_vendor_approved
        """
        vendor = create_pending_vendor(name="Unvetted DSD")
        product = create_product(vendor["id"], sku="HNY", name="Local Honey",
                                 base_price_cents=900, reorder_qty=10)
        lot = validate_success(
            api.create_inventory_lot(
                {"product_id": product["id"], "vendor_id": vendor["id"],
                 "received_qty": 6, "unit_cost_cents": 500}, INVENTORY), 201)
        res = api.post_inventory_lot(lot["id"], INVENTORY)
        validate_error(res, "ERR_VENDOR_NOT_APPROVED", expected_status=409)

    def test_post_lot_succeeds_once_vendor_approved(self, api):
        """PRD §3.2: "the lot's vendor must be `APPROVED` (else `ERR_VENDOR_NOT_APPROVED`)".
        Once the vendor is APPROVED the same post succeeds, confirming vendor state is
        the gate. PRD §3.2: "On posting, the lot's `qty_on_hand` is set to its `received_qty`".

        Design: Difficulty/cross_entity_state_dependency/cesd_lot_post_requires_vendor_approved
        """
        vendor = create_pending_vendor(name="Now Vetted DSD")
        product = create_product(vendor["id"], sku="HNY2", name="Local Honey",
                                 base_price_cents=900, reorder_qty=10)
        lot = validate_success(
            api.create_inventory_lot(
                {"product_id": product["id"], "vendor_id": vendor["id"],
                 "received_qty": 6, "unit_cost_cents": 500}, INVENTORY), 201)
        api.set_vendor_status(vendor["id"], {"status": "APPROVED"}, INVENTORY)
        posted = validate_success(api.post_inventory_lot(lot["id"], INVENTORY), 200)
        assert posted["status"] == "POSTED"
        assert posted["qty_on_hand"] == 6
