"""Cancellation cascades (weather depth-3, ops depth-2 venue release) and the
too-early-to-complete temporal guard.

Queue A: transitive_cascade.
Queue B: errors section (too-early-to-complete).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_operator_headers, make_guide_headers, make_guest_headers,
    get_success_data,
    setup_scheduled_departure_with_confirmed_stop,
    create_paid_booking, create_reserved_booking,
    setup_departed_departure,
)
from test_helpers import api_client

OP = make_operator_headers()
GUIDE = make_guide_headers()


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade
# ---------------------------------------------------------------------------
def test_weather_cancel_cascade_depth3_booking_payment_seatpool(api):
    """PRD §3.8: "This is the weather-override path: every non-terminal booking
    is moved to `CANCELLED` with `refund_cents` set to 100 percent of its
    `amount_paid_cents`, and each such booking whose `payment_status` was
    `CAPTURED` advances to `REFUNDED`."
    PRD §3.6: "Cancelling a `RESERVED` booking returns its seats: the
    departure's `seats_taken` and `expected_headcount` are each reduced by the
    booking's `party_size`"

    Design: Difficulty/transitive_cascade/weather_cancel_cascade_depth3_booking_payment_seatpool
    """
    # CONFIRMED departure with one CONFIRMED stop and one PAID party-6 cheese booking
    # (seats_taken 6, amount_paid 71154).
    s = setup_scheduled_departure_with_confirmed_stop(
        seat_capacity=12, requested_headcount=6,
        venue_overrides={"name": "Oak", "kind": "WINERY", "commission_pct": 0.10,
                         "tasting_cost_per_guest_cents": 1200},
        product_overrides={"base_price_per_person_cents": 9000, "gratuity_pct": 0.18})
    addon = get_success_data(api.create_add_on(
        {"tour_product_id": s["product"]["id"], "name": "Cheese",
         "price_per_person_cents": 1500}, OP))
    booking, _ = create_paid_booking(s["departure"]["id"], s["pickup"]["id"], 6,
                                     add_on_id=addon["id"])
    get_success_data(api.confirm_departure(s["departure"]["id"], OP))
    get_success_data(api.cancel_departure_weather(s["departure"]["id"], "storm", OP))
    b = validate_success(api.get_booking(booking["id"], OP))
    assert b["status"] == "CANCELLED", f"hop1: expected CANCELLED, got {b['status']}"
    assert b["payment_status"] == "REFUNDED", \
        f"hop2: expected REFUNDED, got {b['payment_status']}"
    assert b["refund_cents"] == 71154, \
        f"hop2: expected refund 71154, got {b['refund_cents']}"
    dep = validate_success(api.get_departure(s["departure"]["id"], OP))
    assert dep["seats_taken"] == 0, \
        f"hop3: expected seats_taken 0 after seat release, got {dep['seats_taken']}"


def test_ops_cancel_cascade_depth2_venue_confirmation_release(api):
    """PRD §3.8: "As on the weather path, every stop's `CONFIRMED` venue
    confirmation is moved to `RELEASED`, and the departure's `version` is
    incremented."
    PRD §3.8: "An `Operator` may likewise cancel a departure for operational
    reasons from either `SCHEDULED` or `CONFIRMED`, advancing it to
    `CANCELLED_OPS` and recording the supplied `cancel_reason`."

    Design: Difficulty/transitive_cascade/ops_cancel_cascade_depth2_venue_confirmation_release
    """
    # CONFIRMED departure with one CONFIRMED stop/VC and one PAID party-4 booking.
    s = setup_scheduled_departure_with_confirmed_stop(
        seat_capacity=12, requested_headcount=4,
        venue_overrides={"name": "Oak", "kind": "WINERY", "commission_pct": 0.10,
                         "tasting_cost_per_guest_cents": 1200},
        product_overrides={"base_price_per_person_cents": 9000, "gratuity_pct": 0.18})
    create_paid_booking(s["departure"]["id"], s["pickup"]["id"], 4)
    get_success_data(api.confirm_departure(s["departure"]["id"], OP))
    # 72h before depart (refund tier 50%) — but the asserted effect is the VC release.
    get_success_data(api.set_clock("2026-04-07T18:00:00Z", OP))
    get_success_data(api.cancel_departure_ops(s["departure"]["id"], "low bookings", OP))
    vc = validate_success(api.get_venue_confirmation(s["confirmation"]["id"], OP))
    assert vc["status"] == "RELEASED", \
        f"expected VenueConfirmation RELEASED, got {vc['status']}"
    dep = validate_success(api.get_departure(s["departure"]["id"], OP))
    assert dep["status"] == "CANCELLED_OPS", \
        f"expected departure CANCELLED_OPS, got {dep['status']}"


# ---------------------------------------------------------------------------
# Queue B: errors (too-early-to-complete)
# ---------------------------------------------------------------------------
def test_error_too_early_to_complete_triggerable(api):
    """PRD §3.8: "A `Guide` completes a `DEPARTED` departure, advancing it
    `DEPARTED → COMPLETED`, but only once the logical clock has reached or passed
    `return_at`; an attempt before then is rejected with
    `ERR_TOO_EARLY_TO_COMPLETE`."

    Design: Corner/errors/error_too_early_to_complete_triggerable
    """
    # DEPARTED departure, booking CHECKED_IN; clock left at depart_at (< return_at).
    s = setup_departed_departure(seat_capacity=12, party_size=4, check_in=True)
    # clock is at depart_at 2026-04-10T18:00, return_at is 2026-04-10T23:00.
    resp = api.complete_departure(s["departure"]["id"], GUIDE)
    validate_error(resp, ApiErrorId.ERR_TOO_EARLY_TO_COMPLETE.value, expected_status=409)
