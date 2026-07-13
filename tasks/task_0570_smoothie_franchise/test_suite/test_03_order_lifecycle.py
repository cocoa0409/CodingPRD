"""Order state machine: parallel dimensions, store-posture gating, invalid transitions."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    setup_order_env, suspend_store, place_order, pay_order, order_line,
    make_customer_headers, make_store_staff_headers,
)


def _placed_order(api, size="SMALL"):
    env = setup_order_env(api)
    st, cust, mi = env["store"], env["customer"], env["menu_item"]
    order = place_order(api, st["id"], cust["id"], [order_line(mi["id"], size)])
    return env, order


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment
# ---------------------------------------------------------------------------

def test_pay_advances_both_payment_and_fulfillment(api):
    """PRD §3.6: "Payment first confirms inventory, then advances the order
    `fulfillment=PLACED → PREPARING` together with `payment=PENDING → PAID`, and stamps
    `paid_at` with the current clock."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment
    """
    env, order = _placed_order(api)
    paid = pay_order(api, order["id"], env["customer"]["id"])
    assert paid["payment_status"] == "PAID", f"Expected PAID, got {paid['payment_status']}"
    assert paid["fulfillment_status"] == "PREPARING", (
        f"Expected PREPARING, got {paid['fulfillment_status']}"
    )


def test_ready_advances_only_fulfillment(api):
    """PRD §3.6: "**Marking ready** is a store-staff action permitted only from
    `PREPARING`, advancing `fulfillment=PREPARING → READY` with no other effect."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment
    """
    env, order = _placed_order(api)
    pay_order(api, order["id"], env["customer"]["id"])
    resp = api.ready_order(order["id"], make_store_staff_headers(env["store"]["id"]))
    data = validate_success(resp)
    assert data["fulfillment_status"] == "READY", (
        f"Expected READY, got {data['fulfillment_status']}"
    )
    assert data["payment_status"] == "PAID", (
        f"payment must remain PAID after ready, got {data['payment_status']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/order_pay_requires_store_open
# ---------------------------------------------------------------------------

def test_pay_at_suspended_store_rejected(api):
    """PRD §3.6: "**Payment** is performed by the ordering customer and is permitted only
    when the order is `PLACED` and `PENDING` and the store is `OPEN` (otherwise
    `ERR_INVALID_STATE`, or `ERR_STORE_NOT_OPEN` if the store is not open)."

    Design: Difficulty/cross_entity_state_dependency/order_pay_requires_store_open
    """
    env, order = _placed_order(api)
    suspend_store(api, env["store"])
    resp = api.pay_order(order["id"], make_customer_headers(env["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STORE_NOT_OPEN.value)


def test_pay_rejected_leaves_order_pending(api):
    """PRD §3.5: "A new order begins with `fulfillment_status` of `PLACED` and
    `payment_status` of `PENDING` — two independent dimensions that evolve separately,
    as described in §3.6."
    PRD §3.6: "**Payment** is performed by the ordering customer and is permitted only
    when the order is `PLACED` and `PENDING` and the store is `OPEN` (otherwise
    `ERR_INVALID_STATE`, or `ERR_STORE_NOT_OPEN` if the store is not open)."

    Design: Difficulty/cross_entity_state_dependency/order_pay_requires_store_open
    """
    env, order = _placed_order(api)
    suspend_store(api, env["store"])
    api.pay_order(order["id"], make_customer_headers(env["customer"]["id"]))
    resp = api.get_order(order["id"], make_customer_headers(env["customer"]["id"]))
    data = validate_success(resp)
    assert data["payment_status"] == "PENDING", (
        f"payment must stay PENDING after rejected pay, got {data['payment_status']}"
    )


# ---------------------------------------------------------------------------
# Corner/state_machines — invalid transitions
# ---------------------------------------------------------------------------

def test_ready_on_placed_order_returns_invalid_state(api):
    """PRD §3.6: "**Marking ready** is a store-staff action permitted only from
    `PREPARING`, advancing `fulfillment=PREPARING → READY` with no other effect."

    Design: Corner/state_machines/ready_on_placed_order_returns_invalid_state
    """
    env, order = _placed_order(api)
    resp = api.ready_order(order["id"], make_store_staff_headers(env["store"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_cancelled_order_returns_invalid_state(api):
    """PRD §3.6: "**Payment** is performed by the ordering customer and is permitted only
    when the order is `PLACED` and `PENDING` and the store is `OPEN` (otherwise
    `ERR_INVALID_STATE`, or `ERR_STORE_NOT_OPEN` if the store is not open)."

    Design: Corner/state_machines/pay_cancelled_order_terminal_returns_invalid_state
    """
    env, order = _placed_order(api)
    cust_id = env["customer"]["id"]
    validate_success(api.cancel_order(order["id"], make_customer_headers(cust_id)))
    resp = api.pay_order(order["id"], make_customer_headers(cust_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_order_twice_second_returns_invalid_state(api):
    """PRD §3.6: "A cancellation attempted from any state other than `PLACED`,
    `PREPARING`, or `READY` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_order_twice_second_returns_invalid_state
    """
    env, order = _placed_order(api)
    cust_id = env["customer"]["id"]
    validate_success(api.cancel_order(order["id"], make_customer_headers(cust_id)))
    resp = api.cancel_order(order["id"], make_customer_headers(cust_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner/entities/list_orders_by_customer_reverse_reachability
# ---------------------------------------------------------------------------

def test_list_orders_by_customer_reverse_reachability(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_orders_by_customer_reverse_reachability
    """
    env, order = _placed_order(api)
    cust_id = env["customer"]["id"]
    resp = api.list_orders(make_customer_headers(cust_id), params={"customer_id": cust_id})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"
    assert data[0]["id"] == order["id"], "Listed order should be the one just placed"
    assert meta["has_more"] is False, "Expected has_more false with a single order"
