"""Order lifecycle (parallel payment/fulfillment axes), stock reservation and
its conservation on cancel, waitlist promotion, and special-order fulfillment.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    new_store,
    new_customer,
    new_sku,
    new_special_order,
    create_order,
    create_order_payload,
    order_line,
    setup_order,
    setup_picked_up_order,
)

STAFF = TEST_USERS["store_staff_headers"]


def test_order_payment_axis_independent_pay_then_ready(api):
    """PRD §3.4: "Fulfillment and payment advance on independent axes."
    PRD §3.5: "Either way, `amount_due_cents` is set to
    `total_before_credit_cents` minus `store_credit_applied_cents`,
    `payment_status` advances `UNPAID → PAID`, and loyalty accrues."
    PRD §3.4: "On the fulfillment axis, store personnel mark a reserved order
    ready, advancing `RESERVED → READY`; this requires the order to currently be
    `RESERVED`, else `ERR_ORDER_NOT_RESERVED`, and it refreshes the order's
    `updated_at`."

    Design: Difficulty/non_linear_state_machine/order_payment_axis_independent_of_fulfillment_axis
    """
    base = setup_order(api, sku_overrides={"base_price_cents": 5000, "initial_on_hand_qty": 100})
    cust = base["customer"]["id"]
    oid = base["order"]["id"]
    get_success_data(api.pay_order(oid, {"payment_method": "CARD"}, make_customer_headers(cust)))
    data = validate_success(api.mark_ready_order(oid, STAFF), 200)
    assert data["payment_status"] == "PAID"
    assert data["fulfillment_status"] == "READY"


def test_order_payment_axis_independent_ready_then_pay(api):
    """PRD §3.4: "Fulfillment and payment advance on independent axes."
    PRD §3.4: "On the fulfillment axis, store personnel mark a reserved order
    ready, advancing `RESERVED → READY`; this requires the order to currently be
    `RESERVED`, else `ERR_ORDER_NOT_RESERVED`, and it refreshes the order's
    `updated_at`."
    PRD §3.5: "Either way, `amount_due_cents` is set to
    `total_before_credit_cents` minus `store_credit_applied_cents`,
    `payment_status` advances `UNPAID → PAID`, and loyalty accrues."

    Design: Difficulty/non_linear_state_machine/order_payment_axis_independent_of_fulfillment_axis
    """
    base = setup_order(api, sku_overrides={"base_price_cents": 5000, "initial_on_hand_qty": 100})
    cust = base["customer"]["id"]
    oid = base["order"]["id"]
    get_success_data(api.mark_ready_order(oid, STAFF))  # RESERVED -> READY, still UNPAID
    data = validate_success(
        api.pay_order(oid, {"payment_method": "CARD"}, make_customer_headers(cust)), 200
    )
    assert data["payment_status"] == "PAID"
    assert data["fulfillment_status"] == "READY"


def test_order_create_blocked_by_sku_insufficient_stock(api):
    """PRD §3.4: "for each line the SKU's available quantity (its `on_hand_qty`
    minus `reserved_qty`) must be at least the line's `qty`, or the order is
    rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/cross_entity_state_dependency/order_create_blocked_by_sku_insufficient_stock
    """
    store = new_store(api)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=5000, initial_on_hand_qty=1)
    resp = api.create_order(
        create_order_payload(cust, store["id"], [order_line(sku["id"], 2)]),
        make_customer_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


def test_order_create_at_available_boundary_succeeds(api):
    """PRD §3.4: "for each line the SKU's available quantity (its `on_hand_qty`
    minus `reserved_qty`) must be at least the line's `qty`, or the order is
    rejected with `ERR_INSUFFICIENT_STOCK`." — qty exactly equal to available
    is accepted.

    Design: Difficulty/cross_entity_state_dependency/order_create_blocked_by_sku_insufficient_stock
    """
    store = new_store(api)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=5000, initial_on_hand_qty=1)
    resp = api.create_order(
        create_order_payload(cust, store["id"], [order_line(sku["id"], 1)]),
        make_customer_headers(cust),
    )
    data = validate_success(resp, 201)
    assert data["fulfillment_status"] == "RESERVED"


def test_empty_order_lines_rejected_at_create(api):
    """PRD §3.4: "The `lines` array must be non-empty — an empty order is
    rejected with `ERR_EMPTY_ORDER`."

    Design: Difficulty/boundary_precision_check/empty_order_lines_rejected_at_create
    """
    store = new_store(api)
    customer = new_customer(api)
    cust = customer["id"]
    resp = api.create_order(
        create_order_payload(cust, store["id"], []), make_customer_headers(cust)
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)


def test_nonempty_order_lines_accepted_at_create(api):
    """PRD §3.4: "The `lines` array must be non-empty — an empty order is
    rejected with `ERR_EMPTY_ORDER`." — a single-line (non-empty) order is
    created in `RESERVED`.

    Design: Difficulty/boundary_precision_check/empty_order_lines_rejected_at_create
    """
    store = new_store(api)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=5000, initial_on_hand_qty=10)
    resp = api.create_order(
        create_order_payload(cust, store["id"], [order_line(sku["id"], 1)]),
        make_customer_headers(cust),
    )
    data = validate_success(resp, 201)
    assert data["fulfillment_status"] == "RESERVED"


def test_complete_pickup_on_reserved_order_returns_not_ready(api):
    """PRD §3.4: "Completing the pickup advances `READY → PICKED_UP`; this
    requires the order to be `READY` **and** already `PAID`, else
    `ERR_ORDER_NOT_READY`, and it draws down physical stock — each line's SKU has
    both its `on_hand_qty` and its `reserved_qty` lowered by the line `qty`, with
    availability recomputed."

    Design: Corner/state_machines/complete_pickup_on_reserved_order_returns_not_ready
    """
    base = setup_order(api, sku_overrides={"base_price_cents": 4000, "initial_on_hand_qty": 10})
    resp = api.complete_pickup_order(base["order"]["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_READY.value)


def test_cancel_picked_up_order_returns_not_cancellable(api):
    """PRD §3.4: "cancelling an order that is already `PICKED_UP` or `CANCELLED`
    is rejected with `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_picked_up_order_returns_not_cancellable
    """
    base = setup_picked_up_order(api, sku_overrides={"base_price_cents": 4000,
                                                     "initial_on_hand_qty": 10})
    cust = base["customer"]["id"]
    resp = api.cancel_order(base["order"]["id"], make_customer_headers(cust))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value)


def test_reserve_then_cancel_conserves_sku_inventory(api):
    """PRD §3.4: "Cancellation releases each line's reservation — lowering the
    SKU's `reserved_qty` by the line `qty` and recomputing availability — and
    that freed availability cascades into the special-order waitlist, promoting
    the earliest waiting request for the affected SKU."

    Design: Difficulty/compensating_invariant/reserve_then_cancel_conserves_sku_inventory
    """
    base = setup_order(api, sku_overrides={"base_price_cents": 5000, "initial_on_hand_qty": 5},
                       qty=2)
    cust = base["customer"]["id"]
    get_success_data(api.cancel_order(base["order"]["id"], make_customer_headers(cust)))
    sku = get_success_data(api.get_sku(base["sku"]["id"], STAFF))
    assert sku["reserved_qty"] == 0
    assert sku["on_hand_qty"] == 5


def test_reserve_then_cancel_conserves_sku_inventory_larger_qty(api):
    """PRD §3.4: "Cancellation releases each line's reservation — lowering the
    SKU's `reserved_qty` by the line `qty` and recomputing availability — and
    that freed availability cascades into the special-order waitlist, promoting
    the earliest waiting request for the affected SKU."

    Design: Difficulty/compensating_invariant/reserve_then_cancel_conserves_sku_inventory
    """
    base = setup_order(api, sku_overrides={"base_price_cents": 5000, "initial_on_hand_qty": 10},
                       qty=3)
    cust = base["customer"]["id"]
    get_success_data(api.cancel_order(base["order"]["id"], make_customer_headers(cust)))
    sku = get_success_data(api.get_sku(base["sku"]["id"], STAFF))
    assert sku["reserved_qty"] == 0
    assert sku["on_hand_qty"] == 10


def _setup_order_and_waitlisted_so(api):
    """SKU on_hand 1; C1 reserves the unit via an order; C2's special order for
    the same SKU is WAITLISTED. Returns (sku_id, o1_id, c1_id, so_id)."""
    store = new_store(api)
    sku = new_sku(api, store["id"], base_price_cents=5000, initial_on_hand_qty=1)
    c1 = new_customer(api)
    c2 = new_customer(api)
    o1 = create_order(api, c1["id"], store["id"], [order_line(sku["id"], 1)])
    so = new_special_order(api, c2["id"], sku["id"], store["id"], qty=1)
    return sku["id"], o1["id"], c1["id"], so["id"]


def test_order_cancel_release_promotes_waitlisted_special_order(api):
    """PRD §3.4: "that freed availability cascades into the special-order
    waitlist, promoting the earliest waiting request for the affected SKU."
    PRD §3.8: "the earliest `WAITLISTED` special order for that SKU, ordered by
    creation time, is promoted `WAITLISTED → ALLOCATED` provided the
    now-available quantity is at least its `qty`; promotion raises the SKU's
    `reserved_qty` by `qty` and recomputes availability."

    Design: Difficulty/transitive_cascade/order_cancel_release_promotes_waitlisted_special_order
    """
    sku_id, o1_id, c1_id, so_id = _setup_order_and_waitlisted_so(api)
    get_success_data(api.cancel_order(o1_id, make_customer_headers(c1_id)))
    so = get_success_data(api.get_special_order(so_id, STAFF))
    sku = get_success_data(api.get_sku(sku_id, STAFF))
    assert so["status"] == "ALLOCATED"
    assert sku["reserved_qty"] == 1
    assert sku["on_hand_qty"] == 1


def test_order_cancel_marks_order_cancelled_and_preserves_on_hand(api):
    """PRD §3.4: "An order may be cancelled from either `RESERVED` or `READY`,
    moving `fulfillment_status` to `CANCELLED`; cancelling an order that is
    already `PICKED_UP` or `CANCELLED` is rejected with
    `ERR_ORDER_NOT_CANCELLABLE`."
    PRD §3.8: "promotion raises the SKU's `reserved_qty` by `qty` and recomputes
    availability." — physical stock (`on_hand_qty`) is untouched by cancel.

    Design: Difficulty/transitive_cascade/order_cancel_release_promotes_waitlisted_special_order
    """
    sku_id, o1_id, c1_id, so_id = _setup_order_and_waitlisted_so(api)
    order = get_success_data(api.cancel_order(o1_id, make_customer_headers(c1_id)))
    sku = get_success_data(api.get_sku(sku_id, STAFF))
    assert order["fulfillment_status"] == "CANCELLED"
    assert sku["on_hand_qty"] == 1


def test_special_order_fulfill_decrements_stock(api):
    """PRD §3.8: "Store personnel fulfill an allocated special order, advancing
    `ALLOCATED → FULFILLED`; this requires the special order to currently be
    `ALLOCATED`, else `ERR_SPECIAL_ORDER_NOT_ALLOCATED`, and it draws down
    physical stock, lowering the SKU's `on_hand_qty` and `reserved_qty` each by
    `qty` and recomputing availability."

    Design: Corner/state_machines/special_order_fulfill_decrements_stock
    """
    store = new_store(api)
    sku = new_sku(api, store["id"], base_price_cents=4000, initial_on_hand_qty=5)
    customer = new_customer(api)
    so = new_special_order(api, customer["id"], sku["id"], store["id"], qty=1)
    assert so["status"] == "ALLOCATED"
    data = validate_success(api.fulfill_special_order(so["id"], STAFF), 200)
    assert data["status"] == "FULFILLED"
    sku_after = get_success_data(api.get_sku(sku["id"], STAFF))
    assert sku_after["on_hand_qty"] == 4
    assert sku_after["reserved_qty"] == 0


def test_orders_filtered_list_by_customer_id(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`
    (the number of matching records before pagination), and `has_more` (true
    when records remain beyond the current page) inside the `meta` object."
    PRD §4 lists `GET /orders` (List orders) filterable by the buying customer.

    Design: Corner/endpoints/orders_filtered_list_by_customer_id
    """
    base = setup_order(api, sku_overrides={"base_price_cents": 4000, "initial_on_hand_qty": 10})
    cust = base["customer"]["id"]
    resp = api.list_orders(make_customer_headers(cust), params={"customer_id": cust})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert any(o["id"] == base["order"]["id"] for o in data)
