"""Catalog and CRUD: product creation, computed-field initialization, required
and conditional-required fields, uniqueness, listing/pagination, FK reverse
lists, and the receiving-time inventory reconciliation.

All tests translate corner-design instances (queue B).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    factories,
    fixtures,
    assert_product,
    NON_EXISTENT_UUID,
)

SM = TEST_USERS["store_manager_headers"]
PM = TEST_USERS["price_manager_headers"]
RC = TEST_USERS["receiving_clerk_headers"]
CSH = TEST_USERS["cashier_headers"]
AUD = TEST_USERS["inventory_auditor_headers"]


def test_create_product_returns_201_with_computed_fields_zeroed(api):
    """PRD §3.1: "When a product is created its computed inventory mirrors start
    at zero — `on_hand_qty` is 0 and `on_hand_value_cents` is 0 — its
    `reorder_flagged` is computed immediately, and its lifecycle `status` is
    `ACTIVE`."
    PRD §3.1: "Because the reorder flag is set whenever on-hand quantity is at or
    below the reorder point, a brand-new product with zero on hand and any
    non-negative reorder point begins flagged."

    Design: Corner/entities/create_product_returns_201_with_computed_fields_zeroed
    """
    dept = fixtures.create_department()
    resp = api.create_product(
        factories.create_product_payload(
            dept["id"], name="Sugar", sku="SKU-SUGAR", unit_price_cents=199,
            reorder_point_qty=0,
        ), PM)
    data = validate_success(resp, 201)
    assert_product(data)
    assert data["on_hand_qty"] == 0
    assert data["on_hand_value_cents"] == 0
    assert data["status"] == "ACTIVE"
    assert data["reorder_flagged"] is True


def test_get_nonexistent_product_returns_not_found(api):
    """PRD §2.9: "every referenced id must resolve to an existing record of the right type, or the matching not-found error is returned (for example `ERR_PRODUCT_NOT_FOUND` ...), each at HTTP 404."

    Design: Corner/entities/get_nonexistent_product_returns_not_found
    """
    resp = api.get_product(NON_EXISTENT_UUID, CSH)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)


def test_create_product_missing_required_unit_price_invalid_request(api):
    """PRD §2.10: "request-body well-formedness — required fields present, types
    correct, enums in range, integer constraints honored, and conditional-required
    fields supplied — else `ERR_INVALID_REQUEST`"
    PRD §3.1: "Each product has a display `name`, a base everyday `unit_price_cents`, and several behavioral flags."

    Design: Corner/entities/create_product_missing_required_unit_price_invalid_request
    """
    dept = fixtures.create_department()
    resp = api.create_product(
        {"department_id": dept["id"], "name": "NoPrice", "sku": "SKU-NP",
         "sell_by_weight": False}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_weighed_product_without_plu_invalid_request(api):
    """PRD §3.1: "the `plu` is required when `sell_by_weight` is true, must be
    unique across products where present, and is null for each-sold items."
    PRD §2.10: "conditional-required fields supplied — else `ERR_INVALID_REQUEST`"

    Design: Corner/entities/weighed_product_without_plu_invalid_request
    """
    dept = fixtures.create_department()
    resp = api.create_product(
        {"department_id": dept["id"], "name": "NoPLU", "sell_by_weight": True,
         "unit_price_cents": 100}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_department_code_conflict(api):
    """PRD §3.1: "it must be unique across all departments; a collision is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/duplicate_department_code_conflict
    """
    get_success_data(api.create_department({"code": "GROCERY", "name": "Grocery"}, SM))
    resp = api.create_department({"code": "GROCERY", "name": "Grocery 2"}, SM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_list_products_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page)."

    Design: Corner/entities/list_products_pagination_envelope
    """
    dept = fixtures.create_department()
    fixtures.create_product(department_id=dept["id"], name="A", unit_price_cents=100)
    fixtures.create_product(department_id=dept["id"], name="B", unit_price_cents=100)
    resp = api.list_products(CSH, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_system_fields_ignored_on_create(api):
    """PRD §3.1: "When a product is created its computed inventory mirrors start at zero — `on_hand_qty` is 0 and `on_hand_value_cents` is 0 ... and its lifecycle `status` is `ACTIVE`."
    PRD §2.6: "Several fields on a `Product` are read-only mirrors of the
    underlying inventory lots and are never written directly by a client:
    `on_hand_qty`, `on_hand_value_cents`, and `reorder_flagged`."

    Design: Corner/entities/system_fields_ignored_on_create
    """
    dept = fixtures.create_department()
    resp = api.create_product(
        {"department_id": dept["id"], "name": "Ignore", "sku": "SKU-IGN",
         "sell_by_weight": False, "unit_price_cents": 100, "reorder_point_qty": 0,
         "on_hand_qty": 999, "status": "DISCONTINUED"}, PM)
    data = validate_success(resp, 201)
    assert data["on_hand_qty"] == 0
    assert data["status"] == "ACTIVE"


def test_fk_reverse_list_lots_by_shipment(api):
    """PRD §3.3: "lots may be listed and filtered by `product_id`, by `shipment_id`, and by `status`."
    PRD §3.2: "For each line whose `accepted_qty` is greater than 0, one `InventoryLot` is created in `ACTIVE` with its `shipment_id` set to this shipment ..."

    Design: Corner/endpoints/fk_reverse_list_lots_by_shipment
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="FKL",
                                      unit_price_cents=99, reorder_point_qty=0)
    ship, _ = fixtures.receive_lot(product["id"], 5, unit_cost_cents=100,
                                   expected_total_cents=500)
    resp = api.list_inventory_lots(AUD, params={"shipment_id": ship["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1


def test_derived_on_hand_reconciled_after_receive(api):
    """PRD §3.2: "Each created lot triggers the inventory rollup on its product,
    recomputing `on_hand_qty` and `on_hand_value_cents`, and that rollup in turn
    recomputes the reorder flag ..."
    PRD §3.4: "The product's `on_hand_qty` is the sum of `remaining_qty` over the
    lots that are in `ACTIVE` or `QUARANTINED` status."

    Design: Corner/cross_cutting_complexity_layers/derived_on_hand_reconciled_after_receive
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="Recon",
                                      unit_price_cents=150, reorder_point_qty=0)
    # Receive 10 @ cost 100, expected_total 1000 == received -> within tolerance, no override.
    fixtures.receive_lot(product["id"], 10, unit_cost_cents=100,
                         expected_total_cents=1000, override_variance=False)
    prod = get_success_data(api.get_product(product["id"], RC))
    assert prod["on_hand_qty"] == 10
    assert prod["on_hand_value_cents"] == 1000


def test_short_receive_marks_line_short_and_partial_qty(api):
    """PRD §3.2: "the line is set to `ACCEPTED` when its accepted quantity equals
    its ordered quantity, otherwise to `SHORT`."
    PRD §3.2: "one `InventoryLot` is created in `ACTIVE` with its `shipment_id` set
    to this shipment, its `received_qty` equal to the line's accepted quantity ..."

    Design: Corner/cross_cutting_complexity_layers/short_receive_marks_line_short_and_partial_qty
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="Short",
                                      unit_price_cents=150, reorder_point_qty=0)
    # Ordered 10, accepted 6, expected_total 600 == received -> within tolerance.
    ship, line = fixtures.receive_lot(
        product["id"], 6, unit_cost_cents=100, ordered_qty=10,
        expected_total_cents=600, override_variance=False)
    line_now = get_success_data(api.get_shipment_line(line["id"], RC))
    assert line_now["status"] == "SHORT"
    prod = get_success_data(api.get_product(product["id"], RC))
    assert prod["on_hand_qty"] == 6
