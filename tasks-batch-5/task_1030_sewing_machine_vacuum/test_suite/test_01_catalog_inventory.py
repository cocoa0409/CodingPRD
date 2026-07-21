"""Catalog, inventory intake, recalls, and RBAC on catalog operations.

Covers corner-design entity/state-machine/endpoint/rbac instances for Products
and InventoryItems.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_product,
    create_product_payload,
    new_inventory_item,
    new_product,
    setup_repair_in_repair,
    validate_error,
    validate_paginated,
    validate_success,
)

SM = TEST_USERS["store_manager_headers"]
ST = TEST_USERS["service_tech_headers"]


def test_product_create_echoes_fields_and_defaults_recall_none(api):
    """PRD §3.1: "A newly created product begins with `recall_status` of `NONE`
    and a null `recall_reason`."

    Design: Corner/entities/product_create_returns_all_fields
    """
    res = api.create_product(
        create_product_payload(
            model_name="Elna 720", category="SEWING_MACHINE", brand="Elna",
            msrp_cents=95000, warranty_months=18,
        ),
        SM,
    )
    prod = validate_success(res, 201)
    assert_product(prod)
    assert prod["recall_status"] == "NONE"
    assert prod["warranty_months"] == 18


def test_product_default_warranty_months_applied(api):
    """PRD §3.1: "An optional `warranty_months` gives the length of the factory
    warranty in whole months and defaults to 12 when omitted."

    Design: Corner/entities/product_default_warranty_months_applied
    """
    res = api.create_product(
        {"model_name": "Basic Vac", "category": "VACUUM", "brand": "Generic", "msrp_cents": 20000},
        SM,
    )
    prod = validate_success(res, 201)
    assert prod["warranty_months"] == 12


def test_product_missing_category_rejected(api):
    """PRD §2.10: "**Body well-formedness** — required fields present, enum values
    valid, integer amounts at least 0, and any end/due instant strictly after its
    start instant, else `ERR_VALIDATION` (400)."

    Design: Corner/entities/product_missing_category_rejected
    """
    res = api.create_product(
        {"model_name": "No Cat", "brand": "Generic", "msrp_cents": 10000}, SM
    )
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_product_invalid_category_enum_rejected(api):
    """PRD §2.10: "**Body well-formedness** — required fields present, enum values
    valid, integer amounts at least 0, and any end/due instant strictly after its
    start instant, else `ERR_VALIDATION` (400)."

    Design: Corner/entities/product_invalid_category_enum_rejected
    """
    res = api.create_product(
        {"model_name": "Bad Enum", "category": "TOASTER", "brand": "Generic", "msrp_cents": 10000},
        SM,
    )
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_product_get_nonexistent_returns_not_found(api):
    """PRD §2.10: "**Existence** — path resource ids are resolved left to right,
    and any foreign-key id in the body (`customer_id`, `inventory_item_id`,
    `product_id`, `class_session_id`) must reference an existing entity, else the
    corresponding not-found error (404)."

    Design: Corner/entities/product_get_nonexistent_returns_not_found
    """
    res = api.get_product(NON_EXISTENT_UUID, SM)
    validate_error(res, "ERR_PRODUCT_NOT_FOUND", expected_status=404)


def test_inventory_item_defaults_in_stock(api):
    """PRD §3.1: "A new item enters with `status` of `IN_STOCK`."

    Design: Corner/entities/inventory_item_defaults_in_stock
    """
    prod = new_product(model_name="Stk Model", category="VACUUM", brand="Generic", msrp_cents=30000)
    res = api.create_inventory_item(
        {
            "product_id": prod["id"], "serial_number": "SN-STK", "condition": "NEW",
            "acquisition_cost_cents": 18000, "list_price_cents": 30000,
        },
        SM,
    )
    item = validate_success(res, 201)
    assert item["status"] == "IN_STOCK"


def test_product_double_recall_rejected(api):
    """PRD §3.1: "A product already in `RECALLED` cannot be recalled again; a
    second attempt is rejected with `ERR_ALREADY_RECALLED`."

    Design: Corner/state_machines/product_double_recall_rejected
    """
    prod = new_product(model_name="Rec Model", category="SEWING_MACHINE", brand="G", msrp_cents=60000)
    validate_success(api.recall_product(prod["id"], {"recall_reason": "first"}, SM), 200)
    res = api.recall_product(prod["id"], {"recall_reason": "second"}, SM)
    validate_error(res, "ERR_ALREADY_RECALLED", expected_status=409)


def test_scrap_sold_part_unit_rejected(api):
    """PRD §3.1: "A `StoreManager` may scrap an in-stock unit, moving it
    `IN_STOCK → SCRAPPED`; scrapping requires the unit to be `IN_STOCK`, else
    `ERR_ITEM_NOT_AVAILABLE`."

    Design: Corner/state_machines/inventory_scrap_from_sold_invalid
    """
    # Consume a PART unit onto a repair so it becomes SOLD.
    _cust, _machine, _ticket, part_ids = setup_repair_in_repair(
        labor_hours=1.0, part_prices=(4000,), machine_category="VACUUM",
    )
    part_id = part_ids[0]
    res = api.scrap_inventory_item(part_id, SM)
    validate_error(res, "ERR_ITEM_NOT_AVAILABLE", expected_status=409)
    item = validate_success(api.get_inventory_item(part_id, SM), 200)
    assert item["status"] == "SOLD"


def test_list_products_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of a list response reports `limit`, `offset`,
    `total_count` (the total number of matching records before the page window is
    applied), and `has_more` (true when records remain beyond the current window)."

    Design: Corner/endpoints/list_products_pagination_envelope
    """
    for name in ("P1", "P2", "P3"):
        new_product(model_name=name, category="VACUUM", brand="G", msrp_cents=10000)
    data, meta = validate_paginated(api.list_products(SM, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_inventory_reverse_filter_by_product(api):
    """PRD §3.1: "Inventory may be listed and filtered by `product_id` and by
    `status`, and fetched individually."

    Design: Corner/endpoints/fk_reverse_inventory_by_product
    """
    prod = new_product(model_name="Fk Model", category="VACUUM", brand="G", msrp_cents=30000)
    new_inventory_item(prod["id"], serial_number="SN-A", acquisition_cost_cents=18000, list_price_cents=30000)
    new_inventory_item(prod["id"], serial_number="SN-B", acquisition_cost_cents=18000, list_price_cents=30000)
    data, _meta = validate_paginated(api.list_inventory_items(SM, params={"product_id": prod["id"]}))
    assert len(data) == 2


def test_products_create_denied_for_servicetech(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/products_create_denied_for_servicetech
    """
    res = api.create_product(
        {"model_name": "X", "category": "VACUUM", "brand": "G", "msrp_cents": 10000}, ST
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
