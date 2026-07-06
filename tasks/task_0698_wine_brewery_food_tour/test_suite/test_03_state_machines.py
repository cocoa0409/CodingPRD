"""State-machine transitions, preconditions, terminal lockdown, and the two
non-linear state-machine difficulty instances (cyclic VC loop, parallel booking
dimensions).

Queue A: non_linear_state_machine.
Queue B: state_machines section.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_operator_headers, make_guide_headers,
    make_partner_venue_headers, make_guest_headers,
    get_success_data,
    create_tour_product_payload, create_vehicle_payload,
    create_pickup_point_payload, create_partner_venue_payload,
    create_departure_payload, create_stop_payload,
    create_venue_confirmation_payload, create_booking_payload, create_guest_payload,
    setup_scheduled_departure, setup_requested_venue_confirmation,
    setup_completed_departure, create_cleared_guest,
)
from test_helpers import api_client

OP = make_operator_headers()
GUIDE = make_guide_headers()


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine
# ---------------------------------------------------------------------------
def test_venue_confirmation_cyclic_revision_loop(api):
    """PRD §3.4: "The `Operator` resubmits it with a revised `requested_headcount`,
    advancing `CHANGES_REQUESTED → REQUESTED`, updating the held headcount from
    the body, and incrementing `revision_count` by one as a cycle counter."

    Design: Difficulty/non_linear_state_machine/venue_confirmation_cyclic_revision_loop
    """
    s = setup_requested_venue_confirmation(requested_headcount=8,
                                           venue_overrides={"name": "Hop House",
                                                            "kind": "BREWERY",
                                                            "commission_pct": 0.10,
                                                            "tasting_cost_per_guest_cents": 1000})
    vc_id = s["confirmation"]["id"]
    venue_headers = make_partner_venue_headers(s["venue"]["id"])
    get_success_data(api.request_changes_venue_confirmation(
        vc_id, "shift to afternoon", venue_headers))
    after = validate_success(api.resubmit_venue_confirmation(vc_id, 10, OP))
    assert after["status"] == "REQUESTED", f"expected REQUESTED after resubmit, got {after['status']}"
    assert after["revision_count"] == 1, f"expected revision_count 1, got {after['revision_count']}"
    assert after["requested_headcount"] == 10, \
        f"expected requested_headcount 10, got {after['requested_headcount']}"


def test_booking_parallel_status_and_payment_dimensions(api):
    """PRD §3.6: "A booking advances `DRAFT → RESERVED` when its seats are
    reserved" and "On creation the booking enters `DRAFT` with `payment_status`
    of `UNPAID`".
    PRD §3.6: "Capturing payment sets the `payment_status` to `CAPTURED`, sets
    `amount_paid_cents` equal to `total_cents`, and increments the booking's
    `version`."

    Design: Difficulty/non_linear_state_machine/booking_parallel_status_and_payment_dimensions
    """
    s = setup_scheduled_departure(seat_capacity=12, product_overrides={"gratuity_pct": 0.18})
    guest = create_cleared_guest()
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 4),
        make_guest_headers(guest["id"])))
    reserved = validate_success(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    assert reserved["status"] == "RESERVED", f"expected RESERVED, got {reserved['status']}"
    assert reserved["payment_status"] == "UNPAID", \
        f"expected payment_status UNPAID after reserve, got {reserved['payment_status']}"
    paid = validate_success(api.pay_booking(booking["id"], make_guest_headers(guest["id"])))
    assert paid["status"] == "PAID", f"expected PAID, got {paid['status']}"
    assert paid["payment_status"] == "CAPTURED", \
        f"expected payment_status CAPTURED after pay, got {paid['payment_status']}"


# ---------------------------------------------------------------------------
# Queue B: state_machines
# ---------------------------------------------------------------------------
def test_publish_already_published_returns_invalid_state(api):
    """PRD §3.1: "Publishing a `DRAFT` product advances its `status` to
    `PUBLISHED`; this requires only that the product currently be in `DRAFT`"

    Design: Corner/state_machines/publish_already_published_returns_invalid_state
    """
    product = get_success_data(api.create_tour_product(create_tour_product_payload(), OP))
    get_success_data(api.publish_tour_product(product["id"], OP))
    resp = api.publish_tour_product(product["id"], OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_depart_before_depart_at_too_early(api):
    """PRD §3.8: "A `Guide` departs a `CONFIRMED` departure, advancing it
    `CONFIRMED → DEPARTED`, but only once the logical clock has reached or passed
    `depart_at`; an attempt before then is rejected with
    `ERR_TOO_EARLY_TO_DEPART`."

    Design: Corner/state_machines/depart_before_depart_at_too_early
    """
    # CONFIRMED departure; clock at startup default 2026-03-01 < depart_at 2026-04-10.
    from test_helpers import setup_confirmed_departure
    s = setup_confirmed_departure(seat_capacity=12, party_size=4, paid=False)
    get_success_data(api.set_clock("2026-04-10T17:00:00Z", OP))  # 1h before depart_at
    resp = api.depart_departure(s["departure"]["id"], GUIDE)
    validate_error(resp, ApiErrorId.ERR_TOO_EARLY_TO_DEPART.value, expected_status=409)


def test_confirm_departure_without_confirmed_stop_rejected(api):
    """PRD §3.8: "Every stop of the departure must have a venue confirmation in
    `CONFIRMED` status, failing which the confirm is rejected with
    `ERR_VENUE_NOT_CONFIRMED`."

    Design: Corner/state_machines/confirm_departure_without_confirmed_stop_rejected
    """
    s = setup_requested_venue_confirmation(requested_headcount=4)  # stop with REQUESTED VC
    pickup = get_success_data(api.create_pickup_point(create_pickup_point_payload(), OP))
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], pickup["id"], 4),
        make_guest_headers(guest["id"])))
    get_success_data(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    resp = api.confirm_departure(s["departure"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_VENUE_NOT_CONFIRMED.value, expected_status=409)


def test_new_booking_starts_in_draft_unpaid(api):
    """PRD §3.6: "On creation the booking enters `DRAFT` with `payment_status`
    of `UNPAID`"

    Design: Corner/state_machines/new_booking_starts_in_draft_unpaid
    """
    s = setup_scheduled_departure(seat_capacity=12)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    data = validate_success(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 4),
        make_guest_headers(guest["id"])), expected_status=201)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
    assert data["payment_status"] == "UNPAID", \
        f"expected payment_status UNPAID, got {data['payment_status']}"


def test_cancel_completed_booking_terminal_lockdown(api):
    """PRD §3.6: "`COMPLETED` and `CANCELLED` are the two terminal booking
    states."
    PRD §3.6: "A booking may be cancelled from `DRAFT`, `RESERVED`, or `PAID`,
    always advancing it to `CANCELLED` and incrementing its `version`."

    Design: Corner/state_machines/cancel_completed_booking_terminal_lockdown
    """
    s = setup_completed_departure(seat_capacity=12, party_size=4)
    assert s["booking"]["status"] == "COMPLETED", \
        f"setup expected COMPLETED booking, got {s['booking']['status']}"
    resp = api.cancel_booking(s["booking"]["id"], make_guest_headers(s["guest"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_venue_confirmation_declined_is_terminal(api):
    """PRD §3.4: "`DECLINED` and `RELEASED` are both terminal"

    Design: Corner/state_machines/venue_confirmation_declined_is_terminal
    """
    s = setup_requested_venue_confirmation(requested_headcount=8,
                                           venue_overrides={"name": "Hop", "kind": "BREWERY",
                                                            "commission_pct": 0.10,
                                                            "tasting_cost_per_guest_cents": 1000})
    venue_headers = make_partner_venue_headers(s["venue"]["id"])
    get_success_data(api.decline_venue_confirmation(
        s["confirmation"]["id"], venue_headers, decline_note="fully booked"))
    resp = api.confirm_venue_confirmation(s["confirmation"]["id"], venue_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
