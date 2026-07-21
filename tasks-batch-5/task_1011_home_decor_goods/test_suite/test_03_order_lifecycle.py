"""Order fulfilment and payment axes: independence, system defaults, invalid
transitions, and the capture precondition on fulfil."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, set_clock,
    new_store, new_product, new_inventory, new_order, add_line,
    capture, ready, setup_fulfilled_order, api_client, TEST_USERS,
)

ASSOCIATE = TEST_USERS["associate_headers"]


def _order_with_reserved_line():
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store SM1")
    product = new_product(sku="SKU-SM1", name="Rug", category="TEXTILE",
                          base_price_cents=5000, clearance_floor_cents=500,
                          first_received_at="2026-06-25T00:00:00Z")
    new_inventory(store["id"], product["id"], 5)
    order = new_order(store["id"], "BOPIS")
    add_line(order["id"], product["id"], 1)
    return order


# ─── order_payment_and_fulfillment_axes_independent (queue A) ───

def test_capture_advances_only_payment_axis():
    """PRD §3.5: "A `StoreAssociate` captures payment, advancing `payment_status`
    from `AUTHORIZED` to `CAPTURED`; capture is permitted only when payment is
    `AUTHORIZED` and the order's `fulfillment_status` is not `CANCELLED`."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_axes_independent
    """
    order = _order_with_reserved_line()
    captured = capture(order["id"])
    assert captured["payment_status"] == "CAPTURED", f"got {captured['payment_status']}"
    assert captured["fulfillment_status"] == "PENDING", (
        f"capture must not touch the fulfilment axis, got {captured['fulfillment_status']}")


def test_ready_advances_only_fulfillment_axis():
    """PRD §3.4: "A `StoreAssociate` marks an order ready, advancing
    `fulfillment_status` from `PENDING` to `READY`; this is allowed only when the
    order is `PENDING`, has at least one order line, and the owning store is
    `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_axes_independent
    """
    order = _order_with_reserved_line()
    capture(order["id"])
    made_ready = ready(order["id"])
    assert made_ready["fulfillment_status"] == "READY", f"got {made_ready['fulfillment_status']}"
    assert made_ready["payment_status"] == "CAPTURED", (
        f"marking ready must not touch the payment axis, got {made_ready['payment_status']}")


# ─── order_system_fields_generated_on_create (queue B) ───

def test_new_order_defaults_and_version():
    """PRD §3.4: "A new order begins with `fulfillment_status` of `PENDING` and
    `payment_status` of `AUTHORIZED`."
    PRD §2.4: "`version`: an integer that starts at 1 on creation and increments by
    1 on every mutation."

    Design: Corner/entities/order_system_fields_generated_on_create
    """
    store = new_store(name="Store E2")
    order = new_order(store["id"], "CARRYOUT")
    assert order["fulfillment_status"] == "PENDING", f"got {order['fulfillment_status']}"
    assert order["payment_status"] == "AUTHORIZED", f"got {order['payment_status']}"
    assert order["version"] == 1, f"expected version 1, got {order['version']}"


# ─── ready_twice_returns_invalid_state (queue B) ───

def test_ready_from_ready_is_invalid_state():
    """PRD §3.5: "A transition attempted from a state the machine does not permit
    is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/ready_twice_returns_invalid_state
    """
    order = _order_with_reserved_line()
    ready(order["id"])
    resp = api_client.ready_order(order["id"], ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── cancel_fulfilled_order_returns_invalid_state (queue B) ───

def test_cancel_fulfilled_order_is_invalid_state():
    """PRD §3.5: "A `StoreAssociate` may cancel an order while its
    `fulfillment_status` is either `PENDING` or `READY`, moving it to the terminal
    `CANCELLED` state."
    PRD §3.5: "A transition attempted from a state the machine does not permit is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_fulfilled_order_returns_invalid_state
    """
    ctx = setup_fulfilled_order(
        store_kwargs={"name": "Store SM3"},
        product_kwargs={"sku": "SKU-SM3", "name": "Tray", "category": "KITCHEN",
                        "base_price_cents": 1200, "clearance_floor_cents": 100,
                        "first_received_at": "2026-06-25T00:00:00Z"},
        allocated_qty=5, order_type="CARRYOUT", qty=1)
    resp = api_client.cancel_order(ctx["order"]["id"], ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── fulfill_before_capture_returns_payment_not_captured (queue B) ───

def test_fulfill_before_capture_rejected():
    """PRD §3.4: "The associate then fulfils the order, advancing
    `fulfillment_status` from `READY` to `FULFILLED`; this is allowed only when the
    order is `READY` and its `payment_status` is already `CAPTURED` (otherwise
    `ERR_PAYMENT_NOT_CAPTURED`)."

    Design: Corner/validations/fulfill_before_capture_returns_payment_not_captured
    """
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store V1")
    product = new_product(sku="SKU-V1", name="Basket", category="DECOR",
                          base_price_cents=1500, clearance_floor_cents=100,
                          first_received_at="2026-06-25T00:00:00Z")
    new_inventory(store["id"], product["id"], 5)
    order = new_order(store["id"], "BOPIS")
    add_line(order["id"], product["id"], 1)
    ready(order["id"])
    resp = api_client.fulfill_order(order["id"], ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_CAPTURED.value)
