"""Catalog, inventory, availability reconciliation, uniqueness, and listing.

All tests translate corner-design instances (breadth).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_product, assert_product_availability,
    create_product_payload, create_rental_asset_payload,
    TEST_USERS,
)
import test_helpers as th

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]


def test_product_create_applies_default_status_and_inventory(api):
    """PRD §3.1: "A new product opens in `status` `ACTIVE`."
    PRD §2.6: "A newly created product starts with `on_hand_qty`, `reserved_qty`, and `available_qty` all at 0."
    PRD §2.4: "The version starts at 1 on creation and increments by exactly 1 on every mutation that changes the resource"

    Design: Corner/entities/product_creation_applies_defaults
    """
    resp = api.create_product(
        {"sku": "ACC-1", "name": "Sticker Pack", "category": "ACCESSORY", "unit_price_cents": 500},
        SM,
    )
    data = validate_success(resp, expected_status=201)
    assert_product(data)
    assert data["status"] == "ACTIVE"
    assert data["on_hand_qty"] == 0 and data["reserved_qty"] == 0 and data["available_qty"] == 0
    assert data["version"] == 1


def test_product_create_defaults_is_rentable_false(api):
    """PRD §3.1: "`is_rentable` defaults to false and governs whether physical rental units may be registered against the product."

    Design: Corner/entities/product_creation_applies_defaults
    """
    resp = api.create_product(
        {"sku": "ACC-2", "name": "Wax Comb", "category": "ACCESSORY", "unit_price_cents": 300},
        SM,
    )
    data = validate_success(resp, expected_status=201)
    assert data["is_rentable"] is False


def test_get_nonexistent_product_returns_not_found(api):
    """PRD §2.10: "each missing reference yields the not-found error for its specific entity type (for example `ERR_PRODUCT_NOT_FOUND`, ...)."

    Design: Corner/entities/product_get_nonexistent_returns_not_found
    """
    resp = api.get_product(NON_EXISTENT_UUID, SA)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)


def test_create_product_invalid_category_enum_returns_validation(api):
    """PRD §3.1: "The `category` must be one of nine values: `DECK`, `TRUCKS`, `WHEELS`, `GRIP`, `WAX`, `COMPLETE`, `SURFBOARD`, `WETSUIT`, or `ACCESSORY`."
    PRD §2.10: "a bad type or enum value ... is always reported as `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/product_create_invalid_enum_category_returns_invalid_request
    """
    resp = api.create_product(
        {"sku": "BAD-1", "name": "Mystery", "category": "SPACESHIP", "unit_price_cents": 100},
        SM,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_available_qty_reconciles_on_inventory_adjustment(api):
    """PRD §2.6: "Availability is a derived field, reconciled on every mutation of its inputs as `available_qty` equal to `on_hand_qty` minus `reserved_qty`."

    Design: Corner/entities/product_computed_available_qty_reconciles_on_adjust
    """
    prod = th.create_product(api, sku="WHL-C", name="Wheels C", category="WHEELS", unit_price_cents=3200)
    resp = api.adjust_inventory(prod["id"], {"delta_on_hand": 7}, SM)
    data = validate_success(resp, expected_status=200)
    assert data["on_hand_qty"] == 7
    assert data["reserved_qty"] == 0
    assert data["available_qty"] == 7
    assert_product_availability(data)


def test_rental_asset_with_unknown_product_returns_not_found(api):
    """PRD §2.10: "each missing reference yields the not-found error for its specific entity type (for example `ERR_PRODUCT_NOT_FOUND`, ...)."

    Design: Corner/entities/rental_asset_fk_product_not_found
    """
    resp = api.create_rental_asset(
        {"product_id": NON_EXISTENT_UUID, "asset_tag": "GHOST-1"}, SM
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)


def test_duplicate_sku_rejected(api):
    """PRD §3.1: "an attempt to create a product whose `sku` already exists is rejected with `ERR_DUPLICATE_SKU`."

    Design: Corner/validations/duplicate_sku_returns_conflict
    """
    validate_success(
        api.create_product({"sku": "DUP-1", "name": "First", "category": "WAX", "unit_price_cents": 700}, SM),
        expected_status=201,
    )
    resp = api.create_product(
        {"sku": "DUP-1", "name": "Second", "category": "WAX", "unit_price_cents": 800}, SM
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU.value)


def test_duplicate_asset_tag_rejected(api):
    """PRD §3.1: "A duplicate `asset_tag` is rejected with `ERR_DUPLICATE_ASSET_TAG`."

    Design: Corner/validations/duplicate_asset_tag_returns_conflict
    """
    prod = th.create_rentable_product(api, sku="SB-5", name="Gun", category="SURFBOARD",
                                      unit_price_cents=70000, rental_day_rate_cents=3000)
    validate_success(
        api.create_rental_asset({"product_id": prod["id"], "asset_tag": "TAG-1"}, SM),
        expected_status=201,
    )
    resp = api.create_rental_asset({"product_id": prod["id"], "asset_tag": "TAG-1"}, SM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSET_TAG.value)


def test_reserve_reserved_qty_immediately_visible_on_read(api):
    """PRD §2.6: "Whenever `on_hand_qty` or `reserved_qty` changes — through an inventory adjustment, a board-build reservation, a board-build completion or cancellation, or a special-order fulfillment — `available_qty` is recomputed immediately."

    Design: Corner/consistency/reserve_immediately_visible_on_product_read
    """
    customer, prod, build = th.setup_reserved_board_build(api, on_hand=4, qty=2, unit_price_cents=1000)
    resp = api.get_product(prod["id"], TEST_USERS["bench_tech_headers"])
    data = validate_success(resp, expected_status=200)
    assert data["reserved_qty"] == 2
    assert data["available_qty"] == 2
    assert_product_availability(data)


def test_products_list_returns_paginated_envelope(api):
    """PRD §2.3: "The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records remain beyond the current page)."

    Design: Corner/endpoints/products_list_returns_paginated_envelope
    """
    th.create_product(api, sku="L-1", name="One", category="ACCESSORY", unit_price_cents=100)
    th.create_product(api, sku="L-2", name="Two", category="ACCESSORY", unit_price_cents=200)
    resp = api.list_products(SA, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
