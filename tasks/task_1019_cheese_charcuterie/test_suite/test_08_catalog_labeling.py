"""Catalog creation defaults, product validation, allergen labeling, and not-found reads."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, create_customer, create_order, add_unit_line,
    create_by_unit_product, TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
CS = TEST_USERS["counter_staff_headers"]


# ─── Corner: entities / corner_customer_create_defaults ────────────────────
def test_customer_create_defaults(api):
    """PRD §3.1: "A customer may hold a prepaid `store_credit_cents` balance, set at creation,
    defaulting to 0 and never negative; this balance is the funding source for store-credit
    payments and is credited back on refunds."

    Design: Corner/entities/corner_customer_create_defaults
    """
    res = api.create_customer({"account_type": "RETAIL", "name": "Default Cust", "region_code": "CA"}, SM)
    customer = validate_success(res, 201)
    assert customer["wholesale_tier"] == "NONE"
    assert customer["store_credit_cents"] == 0
    assert customer["status"] == "ACTIVE"


# ─── Corner: entities / corner_product_missing_pricing_mode_invalid_request ─
def test_product_missing_pricing_mode(api):
    """PRD §2.9: "Only then is the request body checked for well-formedness — required fields
    present, enum values legal, types correct — with a malformed body rejected as
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/corner_product_missing_pricing_mode_invalid_request
    """
    res = api.create_product({"name": "No Mode", "category": "CHEESE", "milk_type": "COW",
                              "pasteurized": True, "form": "WHEEL"}, SM)
    validate_error(res, "ERR_VALIDATION")


# ─── Corner: entities / corner_product_by_weight_without_price_invalid_config ─
def test_product_by_weight_without_price(api):
    """PRD §3.1: "a `BY_WEIGHT` product requires `price_per_kg_cents` greater than zero and
    `unit_price_cents` exactly zero, while a `BY_UNIT` product requires `unit_price_cents`
    greater than zero and `price_per_kg_cents` exactly zero. A product violating either rule is
    rejected at creation with `ERR_INVALID_PRICING_CONFIG` (HTTP 422)."

    Design: Corner/entities/corner_product_by_weight_without_price_invalid_config
    """
    res = api.create_product({"name": "Bad Price", "category": "CHEESE", "milk_type": "COW",
                              "pasteurized": True, "form": "WHEEL", "pricing_mode": "BY_WEIGHT",
                              "price_per_kg_cents": 0}, SM)
    validate_error(res, "ERR_INVALID_PRICING_CONFIG")


# ─── Corner: calculations / corner_order_label_allergen_union ──────────────
def test_order_label_allergen_union(api):
    """PRD §3.7: "The allergen list is the sorted union of the allergen tokens of every product
    on the order — the product on each product line, and every component product of each board
    line — with duplicates collapsed and the output deterministically sorted."
    PRD §3.7: "The `contains_raw_milk` flag is true when any product involved in the order,
    whether a line's product or a board component's product, has `pasteurized` equal to false."

    Design: Corner/calculations/corner_order_label_allergen_union
    """
    customer = create_customer(name="Label Cust")
    raw_cheese = create_by_unit_product(name="Raw Blue", category="CHEESE", milk_type="COW",
                                        pasteurized=False, form="WEDGE", unit_price_cents=900,
                                        allergens=["MILK"])
    charcuterie = create_by_unit_product(name="Prosciutto", form="SLICED", unit_price_cents=1200,
                                         allergens=["PORK"])
    order = create_order(customer["id"], "RETAIL")
    add_unit_line(order["id"], raw_cheese["id"], 1)
    add_unit_line(order["id"], charcuterie["id"], 1)

    label = validate_success(api.get_order_label(order["id"], CS), 200)
    assert label["allergens"] == ["MILK", "PORK"]
    assert label["contains_raw_milk"] is True
    assert label["line_count"] == 2


# ─── Corner: entities / corner_get_lot_not_found ───────────────────────────
def test_get_lot_not_found(api):
    """PRD §2.9: "every identifier — path ids and body foreign keys alike — is resolved left to
    right, and the first that does not resolve to an existing resource yields `ERR_NOT_FOUND`."

    Design: Corner/entities/corner_get_lot_not_found
    """
    res = api.get_lot(NON_EXISTENT_UUID, SM)
    validate_error(res, "ERR_NOT_FOUND")
