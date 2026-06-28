"""Catalog CRUD and input validation: product creation, defaults, duplicates,
required fields, enum constraints, not-found, and list pagination.

Covers the Corner queue entities section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_vendor, create_product,
    create_vendor_payload, create_product_payload,
    api_client, INVENTORY, NON_EXISTENT_UUID,
)


def test_create_product_returns_201_with_system_fields(api):
    """PRD 3.1: "A newly created product starts with on_hand of 0, a status of
    ACTIVE, and reorder_needed recomputed from its starting stock against its
    reorder point per the inventory rule."
    PRD 2.4: "The version field is an integer that begins at its initial value
    on creation and increments by one on each mutation."

    Design: Corner/entities/create_product_returns_201_with_system_fields
    """
    vendor = create_vendor()
    payload = create_product_payload(
        vendor["id"], sku="C-SKU-1", sell_mode="EACH", aisle="Z1", bin="Y1",
        list_price_cents=1500, reorder_point=3, reorder_qty=10)
    product = validate_success(api.create_product(payload, INVENTORY), 201)
    assert product["on_hand"] == 0
    assert product["status"] == "ACTIVE"
    assert product["reorder_needed"] is True, "on_hand 0 <= reorder_point 3"
    assert product["version"] == 1


def test_get_product_not_found_returns_404(api):
    """PRD 2.5: "the server validates existence left to right and rejects the
    request with ERR_NOT_FOUND against the first identifier in the path that
    does not resolve to an existing resource."

    Design: Corner/entities/get_product_not_found_returns_404
    """
    res = api.get_product(NON_EXISTENT_UUID, INVENTORY)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_product_missing_required_field_returns_422(api):
    """PRD 3.11: "Request validity is fourth: missing or mistyped required
    fields, illegal enum values, out-of-range numbers ... all yield
    ERR_INVALID_REQUEST."
    PRD 3.1: "a sell_mode of either EACH (discrete units) or BY_FOOT (lumber
    sold by the linear foot)."

    Design: Corner/entities/create_product_missing_required_field_returns_422
    """
    vendor = create_vendor()
    payload = create_product_payload(
        vendor["id"], sku="C-SKU-2", aisle="Z2", bin="Y2",
        list_price_cents=1500, reorder_point=3, reorder_qty=10)
    del payload["sell_mode"]
    res = api.create_product(payload, INVENTORY)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_product_invalid_enum_sell_mode_returns_422(api):
    """PRD 3.11: "Request validity is fourth: missing or mistyped required
    fields, illegal enum values ... all yield ERR_INVALID_REQUEST."
    PRD 3.1: "a sell_mode of either EACH (discrete units) or BY_FOOT (lumber
    sold by the linear foot)."

    Design: Corner/entities/create_product_invalid_enum_sell_mode_returns_422
    """
    vendor = create_vendor()
    payload = create_product_payload(
        vendor["id"], sku="C-SKU-3", sell_mode="BULK", aisle="Z3", bin="Y3",
        list_price_cents=1500, reorder_point=3, reorder_qty=10)
    res = api.create_product(payload, INVENTORY)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_product_defaults_status_active(api):
    """PRD 3.1: "A newly created product starts with `on_hand` of 0, a `status`
    of `ACTIVE`, and `reorder_needed` recomputed from its starting stock against
    its reorder point per the inventory rule."
    PRD 3.1: "A new vendor begins with `status` of `ACTIVE`; the manager may
    later move it to `INACTIVE` via a deactivate action."

    Design: Corner/entities/create_product_default_status_active
    """
    vendor_res = api.create_vendor(
        create_vendor_payload(name="CV4", coop_rebate_pct=0.1), INVENTORY)
    vendor = validate_success(vendor_res, 201)
    assert vendor["status"] == "ACTIVE"

    payload = create_product_payload(
        vendor["id"], sku="C-SKU-4", sell_mode="EACH", aisle="Z4", bin="Y4",
        list_price_cents=1500, reorder_point=3, reorder_qty=10)
    product = validate_success(api.create_product(payload, INVENTORY), 201)
    assert product["status"] == "ACTIVE"


def test_duplicate_sku_returns_409(api):
    """PRD 3.1: "A creation attempt whose sku already exists, or whose aisle and
    bin pair is already taken, is rejected with ERR_DUPLICATE_RESOURCE."

    Design: Corner/entities/duplicate_sku_returns_409
    """
    vendor = create_vendor()
    first = create_product_payload(
        vendor["id"], sku="DUP-1", sell_mode="EACH", aisle="Z5", bin="Y5",
        list_price_cents=1500, reorder_point=3, reorder_qty=10)
    validate_success(api.create_product(first, INVENTORY), 201)
    second = create_product_payload(
        vendor["id"], sku="DUP-1", sell_mode="EACH", aisle="Z6", bin="Y6",
        list_price_cents=1500, reorder_point=3, reorder_qty=10)
    res = api.create_product(second, INVENTORY)
    validate_error(res, "ERR_DUPLICATE_RESOURCE")


def test_list_products_pagination_envelope(api):
    """PRD 2.3: "Each list response carries limit, offset, total_count, and
    has_more inside the meta object of the envelope, where total_count is the
    full size of the matching set before the page window is applied and
    has_more indicates whether further items remain beyond the current window."

    Design: Corner/entities/list_products_pagination_envelope
    """
    vendor = create_vendor()
    for sku, aisle, bin_ in (("L-1", "Z7", "Y7"), ("L-2", "Z8", "Y8")):
        validate_success(api.create_product(create_product_payload(
            vendor["id"], sku=sku, sell_mode="EACH", aisle=aisle, bin=bin_,
            list_price_cents=100, reorder_point=0, reorder_qty=1), INVENTORY), 201)

    data, meta = validate_paginated(
        api.list_products(INVENTORY, params={"vendor_id": vendor["id"],
                                             "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
