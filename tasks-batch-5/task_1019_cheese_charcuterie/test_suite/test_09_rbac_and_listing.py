"""RBAC (role and ownership denial, authentication) and list-filter pagination metadata."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_customer, create_wholesale_customer, create_product, create_cave, receive_lot,
    create_order, make_wholesale_customer_headers, make_anonymous_headers, TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
CS = TEST_USERS["counter_staff_headers"]


# ─── Corner: RBAC / corner_counterstaff_create_product_unauthorized ────────
def test_counterstaff_create_product_unauthorized(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to perform the
    requested operation — or a wholesale principal reaching for a resource it does not own — is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/RBAC/corner_counterstaff_create_product_unauthorized
    """
    res = api.create_product({"name": "X", "category": "CHEESE", "milk_type": "COW",
                              "pasteurized": True, "form": "WHEEL", "pricing_mode": "BY_WEIGHT",
                              "price_per_kg_cents": 3000, "min_aging_days": 0}, CS)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: RBAC / corner_wholesale_rotate_cave_unauthorized ──────────────
def test_wholesale_rotate_cave_unauthorized(api):
    """PRD §2.1: "A `ShopManager` is a back-of-house operator responsible for catalog and
    inventory: products, caves, lots, rotation runs, boards, prep stations, tasting rooms, and
    customer accounts."

    Design: Corner/RBAC/corner_wholesale_rotate_cave_unauthorized
    """
    customer = create_wholesale_customer(name="WR Cust")
    cave = create_cave(name="Cave WR")
    res = api.rotate_cave(cave["id"], make_wholesale_customer_headers(customer["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: RBAC / corner_get_product_unauthenticated ─────────────────────
def test_get_product_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` that is not
    one of the three known roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/RBAC/corner_get_product_unauthenticated
    """
    product = create_product(name="UA Cheese")
    res = api.get_product(product["id"], make_anonymous_headers())
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Corner: RBAC / corner_wholesale_reads_other_order_unauthorized ────────
def test_wholesale_reads_other_order_unauthorized(api):
    """PRD §2.1: "A `WholesaleCustomer` may create and manage only orders and subscriptions
    whose `customer_id` equals its own `X-User-ID`, and may read only its own orders, order
    lines, and subscriptions (plus the shared read-only catalog of products, lots, and boards)."

    Design: Corner/RBAC/corner_wholesale_reads_other_order_unauthorized
    """
    owner = create_wholesale_customer(name="Owner")
    intruder = create_wholesale_customer(name="Intruder")
    order = create_order(owner["id"], "WHOLESALE", headers=make_wholesale_customer_headers(owner["id"]))
    res = api.get_order(order["id"], make_wholesale_customer_headers(intruder["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: endpoints / corner_list_lots_filter_by_cave ───────────────────
def test_list_lots_filter_by_cave(api):
    """PRD §2.3: "The `meta` block of a list response reports `limit`, `offset`, `total_count`
    (the number of records matching the filter before pagination), and `has_more` (true when
    records remain beyond the current page)."

    Design: Corner/endpoints/corner_list_lots_filter_by_cave
    """
    product = create_product(name="LF Cheese")
    cave = create_cave(name="Cave LF")
    receive_lot(product["id"], cave["id"], 500)
    receive_lot(product["id"], cave["id"], 700)
    data, meta = validate_paginated(api.list_lots(SM, params={"cave_id": cave["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ─── Corner: endpoints / corner_list_orders_filter_by_customer ─────────────
def test_list_orders_filter_by_customer(api):
    """PRD §2.3: "The `meta` block of a list response reports `limit`, `offset`, `total_count`
    (the number of records matching the filter before pagination), and `has_more` (true when
    records remain beyond the current page)."

    Design: Corner/endpoints/corner_list_orders_filter_by_customer
    """
    customer = create_customer(name="LO Cust")
    create_order(customer["id"], "RETAIL")
    data, meta = validate_paginated(api.list_orders(CS, params={"customer_id": customer["id"]}))
    assert meta["total_count"] == 1
