"""Catalog CRUD, note-finder discovery, and list pagination."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    make_customer, make_product, make_order,
    create_customer_payload, create_variant_payload,
    TEST_USERS,
)
from test_helpers.test_users import make_customer_headers

MERCH = TEST_USERS["merchandiser_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_register_customer_starts_active_bronze_zero_points(api):
    """PRD §3.8: "the account starts with `status` `ACTIVE`, `tier` `BRONZE`, a
    `loyalty_points_balance` of zero, and a `lifetime_spend_cents` of zero."

    Design: Corner/entities/customer_create_returns_201_with_defaults
    """
    resp = api.create_customer(create_customer_payload(email="defaults@x.com"), ADMIN)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["tier"] == "BRONZE"
    assert data["loyalty_points_balance"] == 0
    assert data["lifetime_spend_cents"] == 0


def test_new_order_defaults_cart_unpaid_zero_pricing(api):
    """PRD §3.2: "the new order starts with `fulfillment_status` of `CART` and
    `payment_status` of `UNPAID`."

    Design: Corner/entities/order_computed_fields_defaulted_on_create
    """
    cust = make_customer()
    resp = api.create_order({"customer_id": cust["id"]}, make_customer_headers(cust["id"]))
    data = validate_success(resp, 201)
    assert data["fulfillment_status"] == "CART"
    assert data["payment_status"] == "UNPAID"
    assert data["total_cents"] == 0


def test_get_unknown_product_returns_not_found(api):
    """PRD §2.7: "Each entity has its own not-found error and all are HTTP 404:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`,"

    Design: Corner/entities/product_get_not_found_returns_404
    """
    resp = api.get_product(NON_EXISTENT_UUID, MERCH)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND, 404)


def test_create_variant_missing_price_rejected(api):
    """PRD §2.8: "generic request-body validation of required fields, enums, and
    types (`ERR_INVALID_REQUEST`, HTTP 400), which applies to every POST."

    Design: Corner/entities/variant_create_missing_required_returns_400
    """
    prod = make_product()
    payload = create_variant_payload(kind="SAMPLE", volume_ml=2, on_hand_qty=5)
    payload.pop("unit_price_cents")
    resp = api.create_variant(prod["id"], payload, MERCH)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_note_finder_filters_by_family(api):
    """PRD §3.1: "Shoppers and staff discover products through a note-finder
    listing that filters the catalog by the query parameters `note` (matching an
    embedded note's name), `family` (matching an embedded note's family), and
    `kind` (matching the product's merchandising kind)."

    Design: Corner/endpoints/note_finder_filters_by_family
    """
    woody = make_product(name="Woodsy", concentration="EDP",
                         notes=[{"name": "Cedar", "family": "WOODY", "level": "BASE"}])
    make_product(name="Citrusy", concentration="EDT",
                 notes=[{"name": "Bergamot", "family": "CITRUS", "level": "TOP"}])
    resp = api.list_products(TEST_USERS["customer_headers"], params={"family": "WOODY"})
    data, _meta = validate_paginated(resp)
    ids = {p["id"] for p in data}
    assert woody["id"] in ids, "WOODY product must be returned"
    for p in data:
        families = {n["family"] for n in p.get("notes", [])}
        assert "WOODY" in families, f"product {p['id']} lacks a WOODY note"


def test_orders_list_pagination_envelope(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/orders_list_pagination_envelope
    """
    cust = make_customer()
    headers = make_customer_headers(cust["id"])
    make_order(cust["id"])
    make_order(cust["id"])
    resp = api.list_orders(headers, params={"customer_id": cust["id"], "limit": 1})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
