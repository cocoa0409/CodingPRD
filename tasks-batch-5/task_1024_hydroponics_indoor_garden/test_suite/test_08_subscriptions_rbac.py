"""Subscription pause/resume cycle, role-authorization gates, and the order-list
pagination envelope."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, api_client,
    new_customer, new_stocked_product, new_retail_order, new_active_subscription,
    new_consultant, create_product_payload, order_line,
    make_customer_headers, make_consultant_headers, TEST_USERS,
)

ADMIN = TEST_USERS["store_admin_headers"]


# ─── Corner: state_machines / subscription pause→resume cycle ──────────────
def test_subscription_pause_resume_cycle(api):
    """PRD §3.6: "A subscription cycles between `ACTIVE` and `PAUSED` and can end
    at the terminal `CANCELLED`. Pausing an `ACTIVE` subscription freezes
    `next_ship_at` in place; resuming a `PAUSED` subscription recomputes
    `next_ship_at` as the current clock time plus `interval_days`."

    Design: Corner/state_machines/subscription_pause_resume_cycle
    """
    customer, product, sub = new_active_subscription()
    headers = make_customer_headers(customer["id"])
    validate_success(api.pause_subscription(sub["id"], headers))
    resumed = validate_success(api.resume_subscription(sub["id"], headers))
    assert resumed["status"] == "ACTIVE"


# ─── Corner: rbac / Customer cannot ship an order ──────────────────────────
def test_customer_cannot_ship_order(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_ship_order_returns_unauthorized
    """
    customer = new_customer(email="us@x.com", full_name="U S")
    product, _lot = new_stocked_product(quantity=10, sku_code="ACC-5", name="Hanger",
                                        category="ACCESSORY", unit_price_cents=700)
    order = new_retail_order(customer["id"], [order_line(product["id"], 1)])
    res = api.ship_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: rbac / Consultant cannot create a product ─────────────────────
def test_consultant_cannot_create_product(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/consultant_cannot_create_product_returns_unauthorized
    """
    consultant = new_consultant(name="Cara", specialty="LIGHTING", hourly_rate_cents=9000)
    headers = make_consultant_headers(consultant["id"])
    res = api.create_product(
        create_product_payload(sku_code="X-1", name="X", category="ACCESSORY",
                               unit_price_cents=100),
        headers,
    )
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: endpoints / order list pagination envelope ────────────────────
def test_list_orders_by_customer_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the
    envelope."

    Design: Corner/endpoints/list_orders_by_customer_pagination_envelope
    """
    customer = new_customer(email="pg@x.com", full_name="P G")
    product, _lot = new_stocked_product(quantity=100, sku_code="ACC-4", name="Clip",
                                        category="ACCESSORY", unit_price_cents=300)
    new_retail_order(customer["id"], [order_line(product["id"], 1)])
    new_retail_order(customer["id"], [order_line(product["id"], 2)])

    data, meta = validate_paginated(
        api.list_orders(ADMIN, params={"customer_id": customer["id"]})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
