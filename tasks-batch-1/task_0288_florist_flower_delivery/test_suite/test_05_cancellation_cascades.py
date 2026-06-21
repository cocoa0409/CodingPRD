"""Cancellation cascades and conserved-quantity invariants.

Translates queue-A Difficulty transitive_cascade (cancel BOOKED cascade),
compensating_invariant (wallet credit / florist daily capacity conservation),
and cross_entity_state_dependency (dispatch requires ACCEPTED fulfillment).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    make_customer_headers, make_florist_headers,
    setup_booked_order, setup_accepted_order,
    set_clock, create_zone, create_arrangement, create_customer, create_florist,
    credit_wallet, create_draft_order, quote_order, mark_authorized, book_order,
    get_order_wire_fulfillment, accept_wire_fulfillment, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_cancel_booked_cascades_slot_fulfillment_and_florist_load(api):
    """PRD §3.6: "If a delivery slot exists and is not yet released, its `released`
    flag is set to true, freeing that zone-window capacity."
    PRD §3.6: "If a wire fulfillment exists and is not already released, it is
    released — its `status` becomes `RELEASED` (a terminal fulfillment-side state)
    and the chosen florist's daily load for the `assigned_delivery_date` is
    decremented".

    Design: Difficulty/transitive_cascade/cancel_booked_cascades_slot_then_fulfillment_then_florist_load
    """
    ctx, order, wf = setup_booked_order(
        "2026-06-01T08:00:00Z",
        zone_overrides={"zone_code": "Z7", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A7", "display_name": "Bouquet7", "base_price_cents": 5000},
        florist_overrides={"shop_name": "Shop7", "daily_capacity": 1},
        order_overrides={"delivery_date": "2026-06-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    cancelled = validate_success(
        api.cancel_order(order["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"

    slots = validate_success(api.list_order_delivery_slots(order["id"], DISPATCHER), 200)
    rows = slots if isinstance(slots, list) else slots
    assert all(s["released"] is True for s in rows), "DeliverySlot must be released"

    wf_after = validate_success(api.get_wire_fulfillment(wf["id"], DISPATCHER), 200)
    assert wf_after["status"] == "RELEASED"

    # Florist daily load restored: a fresh same-date booking on capacity-1 florist now fits.
    fresh = create_draft_order(ctx["customer"], ctx["arrangement"], ctx["zone"],
                               delivery_date="2026-06-05", window_start_minute=800,
                               window_end_minute=900)
    fresh = quote_order(fresh, ctx["customer"])
    fresh = mark_authorized(fresh["id"])
    rebooked = validate_success(api.book_order(
        fresh["id"], {"expected_order_version": fresh["version"]},
        make_customer_headers(ctx["customer"]["id"])), 200)
    assert rebooked["fulfillment_status"] == "BOOKED"


def test_cancel_quoted_conserves_wallet_credit(api):
    """PRD §3.6: "a cancellation from `QUOTED` releases no slot or fulfillment (none
    exist yet) but still refunds any applied wallet credit".
    PRD §3.2: "the customer's `wallet_credit_cents` is debited by exactly that
    amount".

    Design: Difficulty/compensating_invariant/cancel_quoted_conserves_wallet_credit
    """
    set_clock("2026-10-01T08:00:00Z")
    zone = create_zone(zone_code="Z16", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="A16", display_name="Bouquet16", base_price_cents=5000)
    cust = create_customer(email="wl@x.com", full_name="Wallet C")
    credit_wallet(cust["id"], 1500)
    order = create_draft_order(cust, arr, zone, delivery_date="2026-10-05",
                               window_start_minute=540, window_end_minute=720,
                               apply_wallet_credit=True)
    order = quote_order(order, cust)  # debits up to 1500
    cancelled = validate_success(
        api.cancel_order(order["id"], make_customer_headers(cust["id"])), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    cust_after = validate_success(api.get_customer(cust["id"], DISPATCHER), 200)
    assert cust_after["wallet_credit_cents"] == 1500, cust_after["wallet_credit_cents"]


def test_cancel_booked_conserves_florist_daily_capacity(api):
    """PRD §3.6: "it is released — its `status` becomes `RELEASED` (a terminal
    fulfillment-side state) and the chosen florist's daily load for the
    `assigned_delivery_date` is decremented".

    Design: Difficulty/compensating_invariant/cancel_booked_conserves_florist_daily_capacity
    """
    ctx, order, wf = setup_accepted_order(
        "2026-10-08T08:00:00Z",
        zone_overrides={"zone_code": "Z17", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A17", "display_name": "Bouquet17", "base_price_cents": 5000},
        florist_overrides={"shop_name": "Shop17", "daily_capacity": 1},
        order_overrides={"delivery_date": "2026-10-12", "window_start_minute": 540,
                         "window_end_minute": 720})
    # Cancel order A (was BOOKED+ACCEPTED) — releases the accepted fulfillment.
    validate_success(api.cancel_order(order["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    # Order B on the same date now books because headroom is restored to 1.
    b = create_draft_order(ctx["customer"], ctx["arrangement"], ctx["zone"],
                           delivery_date="2026-10-12", window_start_minute=800,
                           window_end_minute=900)
    b = quote_order(b, ctx["customer"])
    b = mark_authorized(b["id"])
    booked_b = validate_success(api.book_order(
        b["id"], {"expected_order_version": b["version"]},
        make_customer_headers(ctx["customer"]["id"])), 200)
    assert booked_b["fulfillment_status"] == "BOOKED"


def test_dispatch_requires_wire_fulfillment_accepted(api):
    """PRD §3.5: "it carries the cross-entity precondition that the order's wire
    fulfillment has `status` `ACCEPTED`; dispatching an order whose fulfillment has
    not been accepted is rejected with `ERR_PRECONDITION_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_wire_fulfillment_accepted
    """
    ctx, order, _wf = setup_booked_order(
        "2026-08-01T08:00:00Z",
        zone_overrides={"zone_code": "Z12", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A12", "display_name": "Bouquet12", "base_price_cents": 5000},
        florist_overrides={"shop_name": "Shop12", "daily_capacity": 5},
        order_overrides={"delivery_date": "2026-08-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    # WireFulfillment is still ASSIGNED (florist never accepted).
    res = api.dispatch_order(order["id"], make_florist_headers(ctx["florist"]["id"]))
    validate_error(res, "ERR_PRECONDITION_NOT_MET", expected_status=409)
    after = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    assert after["fulfillment_status"] == "BOOKED"
