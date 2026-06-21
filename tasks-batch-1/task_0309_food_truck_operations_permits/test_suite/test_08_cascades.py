"""Depth-3 transitive cascades: commissary-suspend grounding a truck and cancelling its
future bookings, and event-cancel voiding the open orders under arrived bookings.

Queue A: transitive_cascade/commissary_suspend_cascades_truck_grounded_booking_cancelled,
         transitive_cascade/event_cancel_cascades_arrived_booking_void_order.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_reserved_booking, setup_captured_order,
    create_commissary, create_truck, issue_permit, add_propane, add_shift,
    create_spot, create_event, reserve_booking, set_clock,
    api_client, TEST_USERS, make_operator_truck_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── commissary suspend -> truck GROUNDED -> booking CANCELLED ──────────────

def test_commissary_suspend_grounds_truck(api):
    """PRD §3.1: "any truck that loses its only active commissary thereby fails hard gate H1 and
    is forced to `GROUNDED`."

    The first cascade hop: suspending the commissary forces its OPERABLE docked truck to
    GROUNDED.

    Design: Difficulty/transitive_cascade/commissary_suspend_cascades_truck_grounded_booking_cancelled
    """
    set_clock("2026-06-07T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    add_propane(truck["id"], 50)
    add_shift(truck["id"], "DRIVER", "2026-06-07T08:00:00.000Z", "2026-06-07T23:59:00.000Z", staff_name="Dee")
    add_shift(truck["id"], "COOK", "2026-06-07T08:00:00.000Z", "2026-06-07T23:59:00.000Z", staff_name="Coe")
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=2500)
    event = create_event("2026-06-07T18:00:00.000Z", "2026-06-07T23:00:00.000Z")
    reserve_booking(truck["id"], spot["id"], event["id"],
                    "2026-06-07T19:00:00.000Z", "2026-06-07T22:00:00.000Z")
    validate_success(api.suspend_commissary(commissary["id"], DISPATCHER), 200)
    truck_after = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert truck_after["operability"] == "GROUNDED"


def test_commissary_suspend_cascades_to_booking_cancel_with_refund(api):
    """PRD §3.1: "For each truck so grounded, its future `RESERVED` bookings are cancelled with a
    full fee refund as a transitive cascade."
    PRD §3.4: "This cascade transition `RESERVED → CANCELLED` always refunds in full:
    `fee_refunded_cents` is set to `reservation_fee_cents`."

    The deeper hops: the grounded truck's future RESERVED booking is CANCELLED with
    fee_refunded_cents=2500, and the truck's reservation_fee_balance_cents nets back to 0.

    Design: Difficulty/transitive_cascade/commissary_suspend_cascades_truck_grounded_booking_cancelled
    """
    set_clock("2026-07-29T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    add_propane(truck["id"], 50)
    add_shift(truck["id"], "DRIVER", "2026-07-29T08:00:00.000Z", "2026-07-29T23:59:00.000Z", staff_name="Dee")
    add_shift(truck["id"], "COOK", "2026-07-29T08:00:00.000Z", "2026-07-29T23:59:00.000Z", staff_name="Coe")
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=2500)
    event = create_event("2026-07-29T18:00:00.000Z", "2026-07-29T23:00:00.000Z")
    booking = reserve_booking(truck["id"], spot["id"], event["id"],
                              "2026-07-29T19:00:00.000Z", "2026-07-29T22:00:00.000Z")
    validate_success(api.suspend_commissary(commissary["id"], DISPATCHER), 200)
    booking_after = validate_success(api.get_booking(booking["id"], DISPATCHER), 200)
    assert booking_after["status"] == "CANCELLED"
    assert booking_after["fee_refunded_cents"] == 2500
    truck_after = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert truck_after["reservation_fee_balance_cents"] == 0


# ─── event cancel -> ARRIVED booking CANCELLED -> OPEN order VOID ───────────

def test_event_cancel_cancels_arrived_booking_no_refund(api):
    """PRD §3.3: "whereas an `ARRIVED` booking that is cancelled by the event receives **no**
    refund — the truck already showed up, so its fee is kept (its `fee_refunded_cents` stays 0)."

    Cancelling the event cancels the ARRIVED booking on it with fee_refunded_cents 0 (no refund).

    Design: Difficulty/transitive_cascade/event_cancel_cascades_arrived_booking_void_order
    """
    ctx = setup_captured_order(
        "2026-06-08", clock_iso="2026-06-08T18:00:00.000Z",
        line_specs=[1], item_price_cents=250, prepared_units=10,
        reservation_fee_cents=1000)
    validate_success(api.cancel_event(ctx["event"]["id"], DISPATCHER), 200)
    booking_after = validate_success(api.get_booking(ctx["booking"]["id"], DISPATCHER), 200)
    assert booking_after["status"] == "CANCELLED"
    assert booking_after["fee_refunded_cents"] == 0


def test_event_cancel_voids_open_order_and_refunds_payment(api):
    """PRD §3.3: "any order still `OPEN` under one of those now-cancelled arrived bookings is
    voided as a transitive cascade."
    PRD §3.7: "when an event cancellation cascades down to an `OPEN` order (through a cancelled
    arrived booking), that order transitions `OPEN → VOID`, and if its payment was `CAPTURED` it
    likewise moves to `REFUNDED`."

    The deepest hop: the OPEN, CAPTURED order under the cancelled arrived booking is VOIDed with
    payment_status REFUNDED.

    Design: Difficulty/transitive_cascade/event_cancel_cascades_arrived_booking_void_order
    """
    ctx = setup_captured_order(
        "2026-07-30", clock_iso="2026-07-30T18:00:00.000Z",
        line_specs=[1], item_price_cents=250, prepared_units=10,
        reservation_fee_cents=1000)
    validate_success(api.cancel_event(ctx["event"]["id"], DISPATCHER), 200)
    order_after = validate_success(api.get_order(ctx["order"]["id"], DISPATCHER), 200)
    assert order_after["lifecycle_status"] == "VOID"
    assert order_after["payment_status"] == "REFUNDED"
