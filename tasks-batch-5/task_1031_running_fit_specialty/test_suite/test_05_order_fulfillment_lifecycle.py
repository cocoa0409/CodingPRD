"""Parallel payment/fulfillment dimensions, inventory conservation, and
order-transition preconditions.

Queue A (Difficulty): non_linear_state_machine (parallel dims),
compensating_invariant (inventory).
Queue B (Corner): state_machines (fulfill/reserve/cancel).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
    factories as fac,
)


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / order_parallel_payment_and_fulfillment_dimensions
# ---------------------------------------------------------------------------
def test_parallel_payment_paid_fulfillment_pending(api, sm):
    """PRD 2.7: "An `Order` carries two independent state dimensions that evolve
    separately."
    PRD 3.4: "Capturing payment moves it from `AUTHORIZED` to `PAID`"

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    member = fx.create_member()
    product = fx.create_product(category="GEAR", unit_price_cents=8000, initial_stock=3)
    order = fx.create_paid_order(member["id"], product["id"], 1)
    assert order["payment_status"] == "PAID"
    assert order["fulfillment_status"] == "PENDING"


def test_parallel_reserve_advances_fulfillment_only(api, sm):
    """PRD 3.4: "Reserving an order moves `fulfillment_status` from `PENDING` to
    `RESERVED`."
    PRD 2.7: "Neither dimension gates the other's transitions except where a
    workflow rule in Section 3 says so explicitly (for example, fulfillment
    requires the payment dimension to have reached `PAID`)."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    member = fx.create_member()
    product = fx.create_product(category="GEAR", unit_price_cents=8000, initial_stock=3)
    order = fx.create_paid_order(member["id"], product["id"], 1)
    reserved = validate_success(api.reserve_order(order["id"], sm), 200)
    assert reserved["fulfillment_status"] == "RESERVED"
    assert reserved["payment_status"] == "PAID"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / inventory_available_reserve_then_release_conserved
# ---------------------------------------------------------------------------
def test_reserve_holds_units_before_release(api, sm):
    """PRD 3.4: "On success each line's product has its `stock_reserved`
    increased by the line quantity."
    PRD 2.6: "`available_units` is computed as `stock_on_hand` minus
    `stock_reserved`"

    Design: Difficulty/compensating_invariant/inventory_available_reserve_then_release_conserved
    """
    member = fx.create_member()
    product = fx.create_product(category="GEAR", unit_price_cents=5000, initial_stock=10)
    order = fx.create_single_line_order(member["id"], product["id"], 3)
    get_success_data(api.reserve_order(order["id"], sm))
    prod = fx.get_product(product["id"])
    assert prod["stock_reserved"] == 3
    assert prod["available_units"] == 7


def test_reserve_then_release_conserves_available_units(api, sm):
    """PRD 3.4: "If the order was `RESERVED`, every line's product has its
    `stock_reserved` reduced by the line quantity, releasing the held units so
    `available_units` is restored."

    Design: Difficulty/compensating_invariant/inventory_available_reserve_then_release_conserved
    """
    member = fx.create_member()
    product = fx.create_product(category="GEAR", unit_price_cents=5000, initial_stock=10)
    order = fx.create_single_line_order(member["id"], product["id"], 3)
    get_success_data(api.reserve_order(order["id"], sm))
    get_success_data(api.cancel_order(order["id"], sm))
    prod = fx.get_product(product["id"])
    assert prod["available_units"] == 10
    assert prod["stock_reserved"] == 0


# ---------------------------------------------------------------------------
# Corner: state_machines
# ---------------------------------------------------------------------------
def test_fulfill_requires_paid(api, sm):
    """PRD 3.4: "Fulfilling an order then moves `fulfillment_status` from
    `RESERVED` to `FULFILLED`, but only if `payment_status` has already reached
    `PAID`; a fulfill attempt on an unpaid order fails with
    `ERR_PAYMENT_NOT_CAPTURED`."

    Design: Corner/state_machines/c_fulfill_requires_paid_returns_payment_not_captured
    """
    member = fx.create_member()
    product = fx.create_product(category="SHOE", unit_price_cents=10000, initial_stock=3)
    order = fx.create_reserved_order(member["id"], product["id"], 1, pay=False)
    resp = api.fulfill_order(order["id"], sm)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_CAPTURED.value, 409)


def test_reserve_insufficient_stock_rejected(api, sm):
    """PRD 3.4: "Reservation requires, for every line, that the product's
    `available_units` be at least that line's `quantity`; otherwise the
    reservation fails with `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/state_machines/c_reserve_insufficient_stock_rejected
    """
    member = fx.create_member()
    product = fx.create_product(category="NUTRITION", unit_price_cents=3000, initial_stock=2)
    order = fx.create_single_line_order(member["id"], product["id"], 5)
    resp = api.reserve_order(order["id"], sm)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value, 409)


def test_cancel_after_cancelled_invalid_state(api, sm):
    """PRD 3.4: "A member may cancel an order while its `fulfillment_status` is
    either `PENDING` or `RESERVED`, which moves it to the terminal `CANCELLED`."
    PRD 2.9: "**State** — the target resource is in a state that permits the
    requested transition, else one of the state errors (`ERR_INVALID_STATE`,
    `ERR_ORDER_NOT_MODIFIABLE`, `ERR_RETURN_NOT_INSPECTABLE`,
    `ERR_PAYMENT_NOT_CAPTURED`, `ERR_SHOE_ALREADY_RETIRED`), all HTTP 409."

    Design: Corner/state_machines/c_order_cancel_after_cancelled_returns_invalid_state
    """
    member = fx.create_member()
    product = fx.create_product(category="NUTRITION", unit_price_cents=3000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    get_success_data(api.cancel_order(order["id"], sm))
    resp = api.cancel_order(order["id"], sm)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
