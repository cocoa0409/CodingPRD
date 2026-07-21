"""Multi-hop cascades and compensating invariants: the recall ->
release -> short-quantity -> final-subtotal chain, the customer-suspend ->
subscription-pause -> draft-order-cancel chain, and inventory reservation
conservation across place + cancel.
"""
from test_helpers import (
    validate_success, assert_lot_invariants, TEST_USERS, make_customer_headers,
    new_customer, new_product, new_lot, new_order, add_line, place, fulfill,
    setup_placed_one_off_order, setup_autoship_draft_order, recall_lot,
)

OPERATOR = TEST_USERS["store_operator_headers"]


def test_recall_releases_reservation_and_shorts_line(api):
    """PRD §3.2: "every allocation on the recalled lot that is currently
    `RESERVED` transitions to `RELEASED`; each released allocation increases the
    `short_quantity` of its owning `OrderLine` by that allocation's quantity,
    marking those units as no longer shippable; and the lot's `quantity_reserved`
    decreases by the total quantity of the released allocations."

    Design: Difficulty/transitive_cascade/recall_release_short_cascade
    """
    ctx = setup_placed_one_off_order(unit_price_cents=5000, quantity=2, lot_quantity=2)
    recall_lot(ctx["lot"]["id"], reason="supplier defect", severity="CLASS_II")
    lot = validate_success(api.get_lot(ctx["lot"]["id"], OPERATOR), 200)
    line = validate_success(api.get_order_line(ctx["line"]["id"], OPERATOR), 200)
    assert lot["quantity_reserved"] == 0
    assert line["short_quantity"] == 2


def test_recall_shorted_order_fulfils_to_zero_subtotal(api):
    """PRD §3.6: "The order's `final_subtotal_cents` is recomputed as the sum over
    lines of `net_unit_price_cents` multiplied by the line's `quantity` minus its
    `short_quantity`; a recall that shorted a line between placement and
    fulfilment makes the final subtotal fall below the provisional one".

    Design: Difficulty/transitive_cascade/recall_release_short_cascade
    """
    ctx = setup_placed_one_off_order(unit_price_cents=5000, quantity=2, lot_quantity=2)
    recall_lot(ctx["lot"]["id"], reason="supplier defect", severity="CLASS_II")
    fulfilled = fulfill(ctx["order"]["id"])
    assert fulfilled["final_subtotal_cents"] == 0


def test_customer_suspend_pauses_active_subscription(api):
    """PRD §3.3: "Suspending a customer is a `StoreOperator` action that moves an
    `ACTIVE` customer to `SUSPENDED` and runs a three-level cascade. First, every
    `Subscription` of that customer currently in `ACTIVE` status is moved to
    `PAUSED`."

    Design: Difficulty/transitive_cascade/customer_suspend_pause_cancel_cascade
    """
    ctx = setup_autoship_draft_order(cadence_days=30, quantity_per_cycle=1,
                                     unit_price_cents=3000, lot_quantity=10)
    validate_success(api.suspend_customer(ctx["customer"]["id"], OPERATOR), 200)
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OPERATOR), 200)
    sub = validate_success(api.get_subscription(ctx["subscription"]["id"], OPERATOR), 200)
    assert cust["status"] == "SUSPENDED"
    assert sub["status"] == "PAUSED"


def test_customer_suspend_cancels_draft_autoship_order(api):
    """PRD §3.3: "Second, for each such subscription, any of its auto-ship
    `Order`s still in `DRAFT` are moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/customer_suspend_pause_cancel_cascade
    """
    ctx = setup_autoship_draft_order(cadence_days=30, quantity_per_cycle=1,
                                     unit_price_cents=3000, lot_quantity=10)
    validate_success(api.suspend_customer(ctx["customer"]["id"], OPERATOR), 200)
    order = validate_success(api.get_order(ctx["order"]["id"], OPERATOR), 200)
    assert order["status"] == "CANCELLED"


def test_place_reserves_units_forward(api):
    """PRD §3.6: "it records a `RESERVED` allocation of that quantity against the
    lot (an entry of `lot_id`, `quantity`, and `status` in the line's
    `lot_allocations`) and increases the lot's `quantity_reserved` by the same
    amount, reducing the remaining demand."

    Design: Difficulty/compensating_invariant/inventory_reservation_conservation
    """
    cust = new_customer(email="c15@x.com", full_name="Cust Fifteen")
    prod = new_product(unit_price_cents=1000)
    lot = new_lot(prod["id"], quantity_received=10, lot_number="CN-1")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 4)
    place(order["id"], cust["id"])
    fetched = validate_success(api.get_lot(lot["id"], OPERATOR), 200)
    assert fetched["quantity_reserved"] == 4
    assert fetched["quantity_available"] == 6
    assert_lot_invariants(fetched)


def test_cancel_placed_order_restores_reservation(api):
    """PRD §3.6: "Cancelling a `PLACED` order is compensating: every `RESERVED`
    allocation transitions to `RELEASED` and its lot's `quantity_reserved`
    decreases by the allocation's quantity, restoring `quantity_available`".

    Design: Difficulty/compensating_invariant/inventory_reservation_conservation
    """
    cust = new_customer(email="c15b@x.com", full_name="Cust Fifteen B")
    prod = new_product(unit_price_cents=1000)
    lot = new_lot(prod["id"], quantity_received=10, lot_number="CN-2")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 4)
    place(order["id"], cust["id"])
    validate_success(api.cancel_order(order["id"], make_customer_headers(cust["id"])), 200)
    fetched = validate_success(api.get_lot(lot["id"], OPERATOR), 200)
    assert fetched["quantity_reserved"] == 0
    assert fetched["quantity_available"] == 10
    assert fetched["quantity_on_hand"] == 10
    assert_lot_invariants(fetched)
