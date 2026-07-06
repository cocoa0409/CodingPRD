"""Corner queue — state_machines section."""
from test_helpers import (
    validate_error, validate_success, api_client, ApiErrorId,
    make_store_clerk_headers, make_store_manager_headers,
    make_customer_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku, create_sku_with_stock,
    setup_draft_order, reserve_order, pay_order, apply_clearance,
    start_picking, mark_ready, create_event_package,
    create_event_booking, attach_custom_print,
    do_request_revision_and_proof, setup_cpo_at_proof_sent,
    restock_sku,
)


def test_reserve_from_reserved_returns_invalid_state():
    """PRD §3.5: "Attempted transitions on either axis whose
    preconditions are not met are rejected with ERR_INVALID_STATE."
    PRD §3.4: "Reservation is the pivotal transition that moves the
    order from DRAFT to RESERVED."

    Design: Corner/state_machines/reserve_from_reserved_returns_invalid_state
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    reserved = reserve_order(order["id"], order["version"])
    # Try to reserve again with the fresh version — from-state is now RESERVED, not DRAFT.
    resp = api_client.reserve_order(
        reserved["id"], reserved["version"], make_store_clerk_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_from_cancelled_returns_invalid_state():
    """PRD §3.5: "Cancellation from DRAFT, RESERVED, or PICKING moves
    the fulfillment axis to CANCELLED."
    PRD §3.5: "Attempted transitions on either axis whose preconditions
    are not met are rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_from_cancelled_returns_invalid_state
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    r1 = api_client.cancel_order(order["id"], make_store_clerk_headers())
    validate_success(r1)
    # Second cancel — order is already CANCELLED.
    r2 = api_client.cancel_order(order["id"], make_store_clerk_headers())
    validate_error(r2, ApiErrorId.ERR_INVALID_STATE)


def test_new_order_starts_in_draft_and_unpaid():
    """PRD §2.7: "Every new order is created with fulfillment_status set
    to DRAFT and payment_status set to UNPAID."

    Design: Corner/state_machines/order_initial_state_is_draft_unpaid
    """
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    resp = api_client.create_order(
        {"customer_id": cust["id"], "channel": "IN_STORE",
         "lines": [{"sku_id": sku["id"], "qty": 1}]},
        make_store_clerk_headers(),
    )
    order = validate_success(resp, expected_status=201)
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"


def test_no_show_sweep_cancels_ready_order_past_pickup_deadline():
    """PRD §2.13: "The first is the no-show sweep. Every Order whose
    fulfillment_status is READY_FOR_PICKUP and whose pickup_deadline is
    now on or before the new clock is moved to CANCELLED. Its
    reservations release: reserved_qty on every affected SKU decreases
    by the corresponding line quantity, any helium allocation is
    returned to the source tanks, and any attached DeliverySlot moves
    from RESERVED to CANCELLED. The payment axis moves from
    DEPOSIT_HELD or PAID to REFUNDED and the customer's
    store_credit_cents is credited with the order's grand_total_cents."

    Design: Corner/state_machines/no_show_sweep_cancels_ready_orders_past_pickup_deadline
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=300, on_hand=5)
    order = setup_draft_order(
        cust["id"], sku["id"], qty=1, channel="BOPIS",
        pickup_window_start="2026-06-15T14:00:00Z",
        pickup_window_end="2026-06-15T18:00:00Z",
    )
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    start_picking(reserved["id"])
    ready = mark_ready(reserved["id"])
    assert ready["fulfillment_status"] == "READY_FOR_PICKUP"
    # pickup_deadline = pickup_window_end + 48h = 2026-06-17T18:00:00Z.
    # Advance clock past it.
    set_clock("2026-06-18T00:00:00Z")
    r = api_client.get_order(order["id"], make_store_clerk_headers())
    after = validate_success(r)
    assert after["fulfillment_status"] == "CANCELLED", (
        f"No-show sweep must move READY_FOR_PICKUP → CANCELLED; "
        f"got {after['fulfillment_status']}"
    )
    assert after["payment_status"] == "REFUNDED", (
        f"No-show sweep must move payment_status → REFUNDED; "
        f"got {after['payment_status']}"
    )


def test_revision_limit_fourth_request_rejected():
    """PRD §3.7: "A revision request transitions PROOF_SENT to
    REVISION_REQUESTED, increments revision_count by one, and is
    permitted only when revision_count is currently less than 3 — a
    fourth revision attempt is rejected with ERR_REVISION_LIMIT."

    Design: Corner/state_machines/cyclic_revision_limit_exceeded_returns_revision_limit
    """
    cust, sku, order, cpo_ps = setup_cpo_at_proof_sent(
        banner_length_ft=8, base_sku_price=100, base_on_hand=5,
    )
    # Loop 3 revisions to reach revision_count=3 status=PROOF_SENT.
    latest = cpo_ps
    for _ in range(3):
        latest = do_request_revision_and_proof(cpo_ps["id"], cust["id"])
    assert latest["revision_count"] == 3
    assert latest["status"] == "PROOF_SENT"
    # Fourth request-revision must be rejected.
    resp = api_client.request_revision(
        cpo_ps["id"], make_customer_headers(cust["id"])
    )
    validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT)


def test_unclear_flips_is_clearance_and_zeroes_pct():
    """PRD §3.1: "Reversing clearance moves is_clearance back to false,
    resets clearance_pct to zero, and again increments version."

    Design: Corner/state_machines/unclear_sku_flips_is_clearance_and_zeroes_pct
    """
    sku = create_sku(unit_price_cents=500, category="DECOR")
    sku = restock_sku(sku["id"], 5)
    # Apply clearance pct=0.15.
    cl = apply_clearance(sku["id"], 0.15, sku["version"])
    assert cl["is_clearance"] is True
    assert cl["clearance_pct"] == 0.15
    # Now unclear.
    resp = api_client.unclear_sku(sku["id"], make_store_manager_headers())
    unclr = validate_success(resp)
    assert unclr["is_clearance"] is False, (
        f"unclear must flip is_clearance→false; got {unclr['is_clearance']}"
    )
    assert unclr["clearance_pct"] == 0, (
        f"unclear must reset clearance_pct to 0; got {unclr['clearance_pct']}"
    )


def test_event_forfeit_sweep_moves_held_to_forfeited_within_7_days():
    """PRD §2.13: "The second is the event forfeit sweep. Every
    EventBooking whose status is HELD or CONFIRMED and whose event_date
    minus the new clock is strictly less than seven days is moved to
    FORFEITED. The booking's deposit_cents is not refunded and
    store_credit_cents is not increased."

    Design: Corner/state_machines/event_forfeit_sweep_at_less_than_7_days_lead
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    pkg = create_event_package(base_price_cents=30000, deposit_pct=0.25,
                                 min_lead_days=7)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    booking = create_event_booking(order["id"], pkg["id"], "2026-06-25T18:00:00Z")
    assert booking["status"] == "HELD"
    # Advance clock so event_date - now < 7 days.
    set_clock("2026-06-20T00:00:00Z")
    r = api_client.get_event_booking(booking["id"], make_store_clerk_headers())
    after = validate_success(r)
    assert after["status"] == "FORFEITED", (
        f"Event forfeit sweep must flip HELD → FORFEITED; "
        f"got {after['status']}"
    )
