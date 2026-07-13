"""Order creation defaults, initial state, parallel axes, quote totals, and lifecycle guards."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    make_customer_headers, create_customer_payload,
    assert_order,
    setup_catalog_customer_order, setup_quoted_order, setup_confirmed_order,
    setup_rush_two_line_quoted,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
PM = TEST_USERS["production_manager_headers"]


# ---- corner: order_type default ------------------------------------------

def test_order_type_defaults_to_standard(api):
    """PRD 3.2: "The `order_type` is one of `STANDARD`, `SAMPLE`, or `REORDER` and defaults
    to `STANDARD`; `reorder_source_order_id` is populated only for a reorder (see 3.9)."

    Design: Corner/entities/order_type_defaults_to_standard
    """
    cust = validate_success(api.create_customer(create_customer_payload(), ADMIN), 201)
    ch = make_customer_headers(cust["id"])
    resp = api.create_order(
        {"customer_id": cust["id"], "in_hands_date": "2026-05-20T00:00:00Z"}, ch)
    order = validate_success(resp, 201)
    assert order["order_type"] == "STANDARD"
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"


# ---- corner: initial order state -----------------------------------------

def test_new_order_initial_state_is_draft_unpaid(api):
    """PRD 3.2: "A new order begins with `fulfillment_status` of `DRAFT`, `payment_status`
    of `UNPAID`, and `escrow_cents` of 0."

    Design: Corner/state_machines/new_order_initial_state_is_draft_unpaid
    """
    cust = validate_success(api.create_customer(create_customer_payload(), ADMIN), 201)
    ch = make_customer_headers(cust["id"])
    resp = api.create_order(
        {"customer_id": cust["id"], "order_type": "STANDARD",
         "in_hands_date": "2026-05-20T00:00:00Z"}, ch)
    order = validate_success(resp, 201)
    assert_order(order)
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["escrow_cents"] == 0


# ---- corner: not found ----------------------------------------------------

def test_get_order_not_found(api):
    """PRD 2.9: "The full family of existence errors is `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRICE_TIER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_STATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`,
    `ERR_ART_PROOF_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`, and
    `ERR_SHIPMENT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/get_order_not_found_returns_404
    """
    resp = api.get_order(NON_EXISTENT_UUID, AM)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)


# ---- queue A: parallel payment / fulfillment axes ------------------------

def test_deposit_payment_sets_deposit_paid_while_still_quoted(api):
    """PRD 3.5: "it moves to `DEPOSIT_PAID` once escrow has reached
    `deposit_required_cents` but is still below `quoted_total_cents`, and to
    `PAID_IN_FULL` once escrow has reached `quoted_total_cents` (whether it arrives
    there from `UNPAID` in one payment or from `DEPOSIT_PAID` in a later one)."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment
    """
    ctx = setup_quoted_order()
    resp = api.create_payment(ctx["order_id"], {"amount_cents": 60650}, ctx["cust_headers"])
    order = validate_success(resp)
    assert order["payment_status"] == "DEPOSIT_PAID"
    assert order["fulfillment_status"] == "QUOTED", "payment must not advance the fulfillment axis"
    assert order["escrow_cents"] == 60650


def test_confirm_advances_fulfillment_keeping_deposit_paid(api):
    """PRD 3.6: "Confirming an order is the gate between sales and the shop floor
    and is performed by an `AccountManager`, advancing `fulfillment_status` from `QUOTED`
    to `CONFIRMED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment
    """
    ctx = setup_confirmed_order()
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["fulfillment_status"] == "CONFIRMED"
    assert order["payment_status"] == "DEPOSIT_PAID", "fulfillment advance must not disturb payment axis"
    assert order["escrow_cents"] == 60650


# ---- queue A: rush surcharge rounding order ------------------------------

def test_rush_surcharge_rounded_once_after_summing(api):
    """PRD 3.5: "The `quoted_rush_cents` is the rush surcharge: when `is_rush` is true,
    it is 20 percent of the quoted subtotal, rounded half-up exactly once after the
    lines have been summed; when `is_rush` is false, it is 0."

    Design: Difficulty/combinatorial_formula/order_total_rush_rounding_order
    """
    ctx = setup_rush_two_line_quoted()
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["is_rush"] is True
    assert order["quoted_subtotal_cents"] == 107604
    assert order["quoted_rush_cents"] == 21521, (
        "round_half_up(107604*0.20)=21521, not per-line 21520")


def test_rush_quoted_total_sums_subtotal_and_rush(api):
    """PRD 3.5: "The `quoted_total_cents` is the quoted subtotal plus the quoted rush."
    PRD 3.5: "the order's `is_rush` is true when that lead is strictly less than 10 days."

    Design: Difficulty/combinatorial_formula/order_total_rush_rounding_order
    """
    ctx = setup_rush_two_line_quoted()
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["is_rush"] is True
    assert order["quoted_total_cents"] == 129125, (
        f"107604 + 21521, got {order['quoted_total_cents']}")


# ---- corner: invalid transitions / terminal lockdown ---------------------

def test_deliver_unshipped_order_rejected(api):
    """PRD 3.8: "Delivery closes the order: a `ProductionManager` marks a shipped
    order delivered, advancing `fulfillment_status` from `SHIPPED` to `DELIVERED`. The
    order must be in `SHIPPED`, else `ERR_ORDER_NOT_SHIPPED`."

    Design: Corner/state_machines/deliver_unshipped_order_returns_invalid_state
    """
    ctx = setup_catalog_customer_order()
    resp = api.deliver_order(ctx["order_id"], PM)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SHIPPED)


def test_cancel_already_cancelled_order_rejected(api):
    """PRD 3.9: "An `AccountManager` may cancel an order while its `fulfillment_status`
    is `DRAFT`, `QUOTED`, or `CONFIRMED`; any other state yields `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_already_cancelled_order_returns_not_cancellable
    """
    ctx = setup_catalog_customer_order()
    validate_success(api.cancel_order(ctx["order_id"], AM))
    resp = api.cancel_order(ctx["order_id"], AM)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["fulfillment_status"] == "CANCELLED"


# ---- corner: list pagination envelope ------------------------------------

def test_list_orders_returns_pagination_envelope(api):
    """PRD 2.3: "Unless otherwise stated, list endpoints return resources sorted by
    their creation timestamp (`created_at`) in ascending order. Every list response
    includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of
    the envelope."

    Design: Corner/consistency_model/list_orders_returns_pagination_envelope
    """
    ctx = setup_catalog_customer_order()
    resp = api.list_orders(AM, params={"customer_id": ctx["customer_id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert any(o["id"] == ctx["order_id"] for o in data), "the created order must be listed"
