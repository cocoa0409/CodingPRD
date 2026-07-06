"""Difficulty rule 7 — cross-entity state dependencies across different pairs.

Instance A: Order fulfillment vs Order payment — pickup requires PAID.
Instance B: EventBooking depends on parent Order's payment_status.
"""
from test_helpers import (
    validate_success, validate_error, api_client, ApiErrorId,
    make_store_clerk_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock,
    setup_draft_order, create_rental_contract, create_event_package,
    create_event_booking, reserve_order, pay_order,
    start_picking, mark_ready, setup_tableware_sku_with_stock,
)


# =====================================================================
# Instance A — order_pickup_rejects_when_payment_deposit_held_only
# =====================================================================

def test_order_pickup_requires_payment_paid_deposit_held_rejects():
    """PRD §3.5: "Picking up transitions READY_FOR_PICKUP to PICKED_UP,
    requires payment_status to be PAID, and requires the server clock to
    be strictly before pickup_deadline."
    PRD §3.5: "Attempted transitions on either axis whose preconditions
    are not met are rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/order_pickup_rejects_when_payment_deposit_held_only
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    plate = setup_tableware_sku_with_stock(unit_price_cents=500, on_hand=20)
    order = setup_draft_order(
        cust["id"], plate["id"], qty=1, channel="BOPIS",
        pickup_window_start="2026-06-15T14:00:00Z",
        pickup_window_end="2026-06-15T18:00:00Z",
    )
    create_rental_contract(
        order["id"], plate["id"], qty=2,
        rental_start="2026-06-16T00:00:00Z",
        rental_end="2026-06-20T00:00:00Z",
    )
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "DEPOSIT")
    start_picking(reserved["id"])
    ready = mark_ready(reserved["id"])
    assert ready["fulfillment_status"] == "READY_FOR_PICKUP"
    assert ready["payment_status"] == "DEPOSIT_HELD"
    # pickup with DEPOSIT_HELD only (not PAID) → rejected.
    resp = api_client.pickup_order(ready["id"], make_store_clerk_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_order_start_picking_requires_deposit_held_or_paid_unpaid_rejects():
    """PRD §3.5: "Starting picking transitions RESERVED to PICKING, but
    only if payment_status is in DEPOSIT_HELD or PAID."
    PRD §3.5: "Attempted transitions on either axis whose preconditions
    are not met are rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/order_pickup_rejects_when_payment_deposit_held_only
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=500, on_hand=20)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    reserved = reserve_order(order["id"], order["version"])
    assert reserved["payment_status"] == "UNPAID"
    # start-picking with UNPAID → rejected.
    resp = api_client.start_picking_order(
        reserved["id"], make_store_clerk_headers()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# =====================================================================
# Instance B — event_confirm_requires_order_payment_deposit_or_paid
# =====================================================================

def test_event_confirm_rejects_when_order_payment_unpaid():
    """PRD §3.8: "Confirming a booking transitions HELD to CONFIRMED.
    This is permitted only when the parent order's payment_status is
    DEPOSIT_HELD or PAID, and when event_date minus the server clock is
    at least min_lead_days — a shorter lead time is rejected with
    ERR_EVENT_LEAD_TOO_SHORT."
    PRD §3.5: "Attempted transitions on either axis whose preconditions
    are not met are rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/event_confirm_requires_order_payment_deposit_or_paid
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=20)
    pkg = create_event_package(base_price_cents=50000, deposit_pct=0.20,
                                min_lead_days=7)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    booking = create_event_booking(order["id"], pkg["id"], "2026-07-30T18:00:00Z")
    reserved = reserve_order(order["id"], order["version"])
    assert reserved["payment_status"] == "UNPAID"
    # Confirm — parent Order.payment_status is UNPAID, must reject.
    resp = api_client.confirm_event_booking(
        booking["id"], make_store_clerk_headers()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_event_confirm_permits_when_order_payment_deposit_held():
    """PRD §3.8: "Confirming a booking transitions HELD to CONFIRMED.
    This is permitted only when the parent order's payment_status is
    DEPOSIT_HELD or PAID, and when event_date minus the server clock is
    at least min_lead_days — a shorter lead time is rejected with
    ERR_EVENT_LEAD_TOO_SHORT."

    Design: Difficulty/cross_entity_state_dependency/event_confirm_requires_order_payment_deposit_or_paid
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=20)
    pkg = create_event_package(base_price_cents=50000, deposit_pct=0.20,
                                min_lead_days=7)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    booking = create_event_booking(order["id"], pkg["id"], "2026-07-30T18:00:00Z")
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "DEPOSIT")
    resp = api_client.confirm_event_booking(
        booking["id"], make_store_clerk_headers()
    )
    confirmed = validate_success(resp)
    assert confirmed["status"] == "CONFIRMED"
