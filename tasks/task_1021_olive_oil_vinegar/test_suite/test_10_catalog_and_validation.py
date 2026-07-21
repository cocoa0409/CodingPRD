"""Catalog CRUD & defaults, gift-set composition rules, body/existence validation, and
read-after-write consistency."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_product_component,
    create_member, create_bottle, create_bulk_product, create_gift_set, add_component,
    create_order, unit_line, refill_line, make_customer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
STAFF = TEST_USERS["shop_staff_headers"]


# ── Corner: entities / create_member_returns_defaults ──

def test_new_member_returns_retail_zero_balances(api):
    """PRD §3.1: "A newly created member begins as a `RETAIL` `member_type` with a
    `wallet_credit_cents` balance of 0 and `loyalty_points` of 0".

    Design: Corner/entities/create_member_returns_defaults
    """
    member = validate_success(
        api.create_member({"email": "corner-mem@x.com", "full_name": "Corner Mem"}, ADMIN), 201)
    assert member["member_type"] == "RETAIL"
    assert member["wallet_credit_cents"] == 0
    assert member["loyalty_points"] == 0
    assert member["version"] == 1


# ── Corner: entities / product_allergens_default_empty ──

def test_product_without_allergens_defaults_to_empty_list(api):
    """PRD §3.1: "a list of `allergens` drawn from `TREE_NUT` and `SULFITES`, and a
    `shelf_life_days` count ... All four are optional and default to empty or zero."

    Design: Corner/entities/product_allergens_default_empty
    """
    product = validate_success(api.create_product(
        {"sku": "COR-NOALG", "name": "Plain Bottle", "product_type": "BOTTLE",
         "unit_price_cents": 1000}, INV), 201)
    assert product["allergens"] == []


# ── Corner: entities / product_component_immutable_no_version ──

def test_product_component_is_lightweight_join_row(api):
    """PRD §2.4: "a `ProductComponent` (the join between a set and its member product) and a
    `Reservation` are immutable-by-nature join/ledger rows in the sense that they carry only the
    common audit fields the scaffold assigns them; where a resource is not marked as carrying the
    full common-field set it exposes only `id` and `created_at`, with both `updated_at` and
    `version` absent."

    Design: Corner/entities/product_component_immutable_no_version
    """
    gift = create_gift_set(api, sku="COR-GIFT", name="Gift")
    bottle = create_bottle(api, unit_price_cents=1000, sku="COR-BOT", name="Bottle")
    component = validate_success(api.add_component(
        gift["id"], {"component_product_id": bottle["id"], "quantity": 2}, INV), 201)
    assert component["set_product_id"] == gift["id"]
    assert component["component_product_id"] == bottle["id"]
    assert component["quantity"] == 2
    assert_product_component(component)


# ── Corner: entities / member_not_found_returns_404 ──

def test_get_missing_member_returns_not_found(api):
    """PRD §2.8: "When a path contains a resource identifier, the server validates existence left
    to right and rejects the first missing identifier with the matching not-found error (for
    example ... `ERR_MEMBER_NOT_FOUND` ...), each carrying HTTP 404."

    Design: Corner/entities/member_not_found_returns_404
    """
    resp = api.get_member("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


# ── Corner: entities / fusti_create_unknown_product_returns_not_found ──

def test_create_fusti_unknown_product_returns_not_found(api):
    """PRD §2.8: "Body-referenced foreign keys — a `product_id`, a `wholesale_account_id`, a
    `station_id`, or a `component_product_id` — are validated for existence in the same way when
    an order, subscription, fusti, component, or tasting session is created."

    Design: Corner/entities/fusti_create_unknown_product_returns_not_found
    """
    resp = api.create_fusti(
        {"product_id": "00000000-0000-0000-0000-000000000000", "capacity_ml": 1000,
         "initial_volume_ml": 1000, "reorder_point_ml": 100,
         "harvest_date": "2026-06-01T00:00:00Z"}, INV)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)


# ── Corner: validations / zero_volume_refill_returns_invalid_quantity ──

def test_zero_volume_refill_line_rejected(api):
    """PRD §3.3: "The `lines` array must be non-empty, and a refill whose volume is zero or
    negative is rejected with `ERR_INVALID_QUANTITY`."

    Design: Corner/validations/zero_volume_refill_returns_invalid_quantity
    """
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    resp = api.create_order(
        {"lines": [{"line_type": "REFILL", "product_id": product["id"], "quantity": 1,
                    "volume_ml": 0}]},
        make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY.value)


# ── Corner: validations / duplicate_sku_returns_conflict ──

def test_duplicate_sku_rejected(api):
    """PRD §3.1: "Attempting to create a product whose `sku` already exists is rejected with
    `ERR_DUPLICATE_SKU`."

    Design: Corner/validations/duplicate_sku_returns_conflict
    """
    validate_success(api.create_product(
        {"sku": "COR-DUP", "name": "First", "product_type": "BOTTLE",
         "unit_price_cents": 1000}, INV), 201)
    resp = api.create_product(
        {"sku": "COR-DUP", "name": "Second", "product_type": "BOTTLE",
         "unit_price_cents": 1500}, INV)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU.value)


# ── Corner: validations / bundle_component_referencing_set_returns_invalid_component ──

def test_component_referencing_a_set_rejected(api):
    """PRD §3.1: "A component may not itself reference a set — if the `component_product_id`
    points at a `GIFT_SET` or `BLEND`, or if a set is offered for sale with no components at all,
    the request is rejected with `ERR_INVALID_COMPONENT`."

    Design: Corner/validations/bundle_component_referencing_set_returns_invalid_component
    """
    outer = create_gift_set(api, sku="COR-SET-OUTER", name="Outer Set")
    inner = create_gift_set(api, sku="COR-SET-INNER", name="Inner Set")
    resp = api.add_component(outer["id"], {"component_product_id": inner["id"], "quantity": 1}, INV)
    validate_error(resp, ApiErrorId.ERR_INVALID_COMPONENT.value)


# ── Corner: validations / create_order_missing_lines_returns_validation ──

def test_create_order_without_lines_returns_validation(api):
    """PRD §3.3: "The `lines` array must be non-empty". PRD §2.10: "then structural body
    validation (required fields, correct types and enums, quantities and volumes at least 1, and
    a session's end strictly after its start)".

    Design: Corner/validations/create_order_missing_lines_returns_validation
    """
    member = create_member(api)
    resp = api.create_order({"use_wallet_credit": False}, make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ── Corner: errors / order_not_found_on_pay ──

def test_pay_missing_order_returns_not_found(api):
    """PRD §2.8: "When a path contains a resource identifier, the server validates existence left
    to right and rejects the first missing identifier with the matching not-found error (for
    example `ERR_ORDER_NOT_FOUND` ...), each carrying HTTP 404."

    Design: Corner/errors/order_not_found_on_pay
    """
    member = create_member(api)
    resp = api.pay_order("00000000-0000-0000-0000-000000000000",
                         {"expected_order_version": 1}, make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


# ── Corner: errors / reservation_not_found ──

def test_get_missing_reservation_returns_not_found(api):
    """PRD §2.8: "When a path contains a resource identifier, the server validates existence left
    to right and rejects the first missing identifier with the matching not-found error (for
    example ... `ERR_RESERVATION_NOT_FOUND` ...), each carrying HTTP 404."

    Design: Corner/errors/reservation_not_found
    """
    resp = api.get_reservation("00000000-0000-0000-0000-000000000000", STAFF)
    validate_error(resp, ApiErrorId.ERR_RESERVATION_NOT_FOUND.value)


# ── Corner: errors / replenishment_receive_not_found ──

def test_receive_missing_replenishment_returns_not_found(api):
    """PRD §2.8: "When a path contains a resource identifier, the server validates existence left
    to right and rejects the first missing identifier with the matching not-found error (for
    example ... `ERR_REPLENISHMENT_NOT_FOUND` ...), each carrying HTTP 404."

    Design: Corner/errors/replenishment_receive_not_found
    """
    resp = api.receive_replenishment("00000000-0000-0000-0000-000000000000",
                                     {"received_harvest_date": "2026-07-01T00:00:00Z"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_REPLENISHMENT_NOT_FOUND.value)


# ── Corner: consistency_model / immediate_read_after_write_reflects_state ──

def test_product_read_immediately_reflects_written_fields(api):
    """PRD §3.1: "An `InventoryManager` builds the catalog by creating a `Product`, supplying a
    `sku` (unique and non-empty), a `name`, and a `product_type`".

    Design: Corner/consistency_model/immediate_read_after_write_reflects_state
    """
    product = validate_success(api.create_product(
        {"sku": "COR-IMM", "name": "Immediate", "product_type": "ACCESSORY",
         "unit_price_cents": 700}, INV), 201)
    read = validate_success(api.get_product(product["id"], INV))
    assert read["sku"] == "COR-IMM"
    assert read["product_type"] == "ACCESSORY"
