"""Provisioning: accounts, products, inventory-lot system fields, listing.

Corner-design coverage for the `entities` section.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    assert_account, assert_inventory_lot,
    factories as F, fixtures as X,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]


def test_create_account_returns_201_with_zeroed_loyalty_and_balance(api):
    """PRD §3.1: "Every account begins with `status` of `ACTIVE`, an
    `outstanding_balance_cents` of 0, `lifetime_points` of 0, `points_balance`
    of 0, and a `loyalty_tier` of `STANDARD`."

    Design: Corner/entities/create_account_returns_201_with_all_fields
    """
    nursery = X.create_nursery()
    resp = api.create_account(
        nursery["id"],
        F.create_account_payload(account_type="RETAIL", display_name="Walk-in", ship_to_hardiness_zone=6),
        CLERK,
    )
    data = validate_success(resp, expected_status=201)
    assert_account(data)
    assert data["status"] == "ACTIVE"
    assert data["lifetime_points"] == 0
    assert data["points_balance"] == 0
    assert data["loyalty_tier"] == "STANDARD"
    assert data["outstanding_balance_cents"] == 0


def test_retail_account_credit_limit_forced_to_zero(api):
    """PRD §3.1: "a retail account is forced to a `credit_limit_cents` of 0 at
    creation regardless of what was supplied."

    Design: Corner/entities/retail_account_credit_limit_forced_to_zero
    """
    nursery = X.create_nursery()
    resp = api.create_account(
        nursery["id"],
        F.create_account_payload(
            account_type="RETAIL", display_name="Walk-in",
            ship_to_hardiness_zone=6, credit_limit_cents=9999,
        ),
        CLERK,
    )
    data = validate_success(resp, expected_status=201)
    assert data["credit_limit_cents"] == 0


def test_get_account_not_found_returns_404(api):
    """PRD §2.8: "The not-found errors are resource-specific: `ERR_NURSERY_NOT_FOUND`,
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_LINE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_SPECIAL_ORDER_NOT_FOUND`,
    `ERR_DELIVERY_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, and `ERR_CLAIM_NOT_FOUND`,
    each returned with HTTP 404."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account("00000000-0000-4000-8000-000000000000", CLERK)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


def test_create_product_missing_unit_price_returns_422(api):
    """PRD §3.1: "A product is created with a `sku` that must be unique within its
    nursery ... a `unit`, and a `unit_price_cents` list price that must be at least 0."
    PRD §2.10: "malformed enums, non-positive quantities, out-of-range zones,
    unit/category mismatches, and similar shape violations are rejected with
    `ERR_INVALID_REQUEST` (422)".

    Design: Corner/entities/create_product_missing_required_field_returns_422
    """
    nursery = X.create_nursery()
    resp = api.create_product(
        nursery["id"],
        {"sku": "X1", "name": "Bare", "category": "DRY_GOOD", "unit": "EACH"},
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_bulk_material_must_use_cubic_yard_unit(api):
    """PRD §3.1: "a `BULK_MATERIAL` product must use `CUBIC_YARD`, while every
    other category must use `EACH`."

    Design: Corner/entities/bulk_material_must_use_cubic_yard_unit
    """
    nursery = X.create_nursery()
    resp = api.create_product(
        nursery["id"],
        F.create_product_payload(sku="SOIL-1", name="Topsoil", category="BULK_MATERIAL",
                                 unit="EACH", unit_price_cents=4000),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_sku_per_nursery_rejected(api):
    """PRD §3.1: "A product is created with a `sku` that must be unique within its
    nursery — a collision is rejected with `ERR_DUPLICATE_SKU`".

    Design: Corner/entities/duplicate_sku_per_nursery_rejected
    """
    nursery = X.create_nursery()
    api_client.create_product(
        nursery["id"],
        F.create_product_payload(sku="DUP", name="First", category="DRY_GOOD", unit="EACH", unit_price_cents=100),
        INV,
    )
    resp = api.create_product(
        nursery["id"],
        F.create_product_payload(sku="DUP", name="Second", category="DRY_GOOD", unit="EACH", unit_price_cents=200),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU.value)


def test_lot_create_mints_system_fields(api):
    """PRD §3.2: "On receipt the lot's `qty_on_hand` equals its `received_qty`,
    while `reserved_qty`, `shrink_qty`, and `sold_qty` all start at 0, and the lot
    begins life in `QUARANTINE` status."

    Design: Corner/entities/system_fields_generated_ignoring_input
    """
    nursery = X.create_nursery()
    product = X.create_live_plant(nursery["id"], sku="PL-S", name="Sage",
                                  hardiness_min_zone=4, hardiness_max_zone=9, unit_price_cents=700)
    resp = api.create_inventory_lot(
        product["id"], F.create_inventory_lot_payload(received_qty=12, unit_cost_cents=250), INV
    )
    data = validate_success(resp, expected_status=201)
    assert_inventory_lot(data)
    assert data["qty_on_hand"] == 12
    assert data["status"] == "QUARANTINE"
    assert data["reserved_qty"] == 0
    assert data["shrink_qty"] == 0
    assert data["sold_qty"] == 0


def test_list_products_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping inside the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_products_pagination_envelope
    """
    nursery = X.create_nursery()
    api_client.create_product(nursery["id"],
                              F.create_product_payload(sku="A", name="A", unit_price_cents=100), INV)
    api_client.create_product(nursery["id"],
                              F.create_product_payload(sku="B", name="B", unit_price_cents=200), INV)
    resp = api.list_products(nursery["id"], INV, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
