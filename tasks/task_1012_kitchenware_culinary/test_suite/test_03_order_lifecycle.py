"""Order lifecycle: the parallel payment/fulfillment axes, invalid and terminal
transitions, create-time stock/discontinued guards, and the store-open gate on
fulfillment."""
from test_helpers import (
    validate_success, validate_error,
    make_store, make_sku, make_member, make_order, order_line,
    setup_reserved_order, setup_paid_order, setup_fulfilled_order,
    pay_order, fulfill_order, cancel_order,
    create_order_payload,
    TEST_USERS,
)

ASSOC = TEST_USERS["associate_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ── non_linear_state_machine / order_parallel_payment_fulfillment ──
def test_pay_advances_payment_axis_only(api):
    """PRD §3.3: "An order occupies two independent state axes at once."
    PRD §3.3: "**Paying an order.** Payment moves an order from `UNPAID` to `PAID`. Payment
    is permitted only while fulfillment status is `RESERVED` and not yet canceled."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment
    """
    store, member, sku, order = setup_reserved_order(state_code="OR", list_price_cents=8000,
                                                     on_hand_qty=5, qty=1)
    paid = pay_order(order["id"])
    assert paid["payment_status"] == "PAID"
    assert paid["fulfillment_status"] == "RESERVED", "fulfillment axis stays RESERVED after pay"


def test_fulfill_advances_fulfillment_axis_only(api):
    """PRD §3.3: "**Fulfilling an order.** Fulfillment advances the order from `RESERVED`
    to `FULFILLED`."
    PRD §3.3: "an order is terminal once fulfillment reaches `FULFILLED` or `CANCELED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment
    """
    store, member, sku, order = setup_reserved_order(state_code="OR", list_price_cents=8000,
                                                     on_hand_qty=5, qty=1)
    pay_order(order["id"])
    fulfilled = fulfill_order(order["id"])
    assert fulfilled["payment_status"] == "PAID", "payment axis stays PAID after fulfill"
    assert fulfilled["fulfillment_status"] == "FULFILLED"


# ── Corner/state_machines/pay_canceled_order_invalid_state ────
def test_pay_canceled_order_rejected(api):
    """PRD §3.3: "Payment is permitted only while fulfillment status is `RESERVED` and not
    yet canceled."
    PRD §2.10: "an attempt to drive a resource from a state that does not permit the
    requested transition — for example, opening a class that is not `DRAFT`, completing a
    ticket that is not `SCHEDULED`, requesting a revision on a special order that is not
    `QUOTED`, or accepting one that is not `QUOTED` — is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pay_canceled_order_invalid_state
    """
    store, member, sku, order = setup_reserved_order(state_code="OR", list_price_cents=2000,
                                                     on_hand_qty=5, qty=1)
    cancel_order(order["id"])
    res = api.pay_order(order["id"], ASSOC)
    validate_error(res, "ERR_INVALID_STATE")


# ── Corner/state_machines/cancel_fulfilled_order_terminal_lockdown ──
def test_cancel_fulfilled_order_rejected(api):
    """PRD §3.3: "**Cancelling an order.** Cancellation is permitted only while fulfillment
    status is `RESERVED` and not yet fulfilled, and it advances fulfillment to `CANCELED`."
    PRD §2.10: "an attempt to drive a resource from a state that does not permit the
    requested transition — for example, opening a class that is not `DRAFT`, completing a
    ticket that is not `SCHEDULED`, requesting a revision on a special order that is not
    `QUOTED`, or accepting one that is not `QUOTED` — is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_fulfilled_order_terminal_lockdown
    """
    store, member, sku, order = setup_fulfilled_order(state_code="OR", list_price_cents=3000,
                                                      on_hand_qty=5, qty=1)
    res = api.cancel_order(order["id"], ASSOC)
    validate_error(res, "ERR_INVALID_STATE")


# ── Corner/validations/order_insufficient_stock_rejected ──────
def test_order_exceeding_available_stock_rejected(api):
    """PRD §3.3: "for each line the SKU's available quantity must be at least the requested
    quantity, or the order is rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/order_insufficient_stock_rejected
    """
    store = make_store(state_code="OR")
    sku = make_sku(list_price_cents=9000, on_hand_qty=2, category="KNIVES", name="Cleaver")
    member = make_member(store["id"])
    res = api.create_order(create_order_payload(member["id"], store["id"],
                                                [order_line(sku["id"], 5)]), ADMIN)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")


# ── Corner/validations/order_discontinued_sku_rejected ────────
def test_order_referencing_discontinued_sku_rejected(api):
    """PRD §3.3: "every referenced SKU must exist and be `ACTIVE`, or the order is rejected
    with `ERR_DISCONTINUED_SKU`".

    Design: Corner/validations/order_discontinued_sku_rejected
    """
    store = make_store(state_code="OR")
    sku = make_sku(list_price_cents=12000, on_hand_qty=5, category="APPLIANCE",
                   name="Old Model", status="DISCONTINUED")
    member = make_member(store["id"])
    res = api.create_order(create_order_payload(member["id"], store["id"],
                                                [order_line(sku["id"], 1)]), ADMIN)
    validate_error(res, "ERR_DISCONTINUED_SKU")


# ── cross_entity_state_dependency / fulfill_requires_store_open ──
def test_fulfill_at_closed_store_rejected(api):
    """PRD §3.3: "the fulfilling store must be `OPEN`, or the request is rejected with
    `ERR_STORE_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/fulfill_requires_store_open
    """
    store, member, sku, order = setup_paid_order(state_code="OR", list_price_cents=4000,
                                                 on_hand_qty=5, qty=1, store_status="CLOSED")
    res = api.fulfill_order(order["id"], {}, ASSOC)
    validate_error(res, "ERR_STORE_CLOSED")


def test_fulfill_at_open_store_succeeds(api):
    """PRD §3.3: "the fulfilling store must be `OPEN`, or the request is rejected with
    `ERR_STORE_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/fulfill_requires_store_open
    """
    store, member, sku, order = setup_paid_order(state_code="OR", list_price_cents=4000,
                                                 on_hand_qty=5, qty=1, store_status="OPEN")
    fulfilled = fulfill_order(order["id"])
    assert fulfilled["fulfillment_status"] == "FULFILLED"
