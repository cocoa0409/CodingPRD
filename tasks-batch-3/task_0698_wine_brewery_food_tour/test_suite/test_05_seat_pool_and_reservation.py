"""Seat-pool capacity boundaries, charter exclusivity, the empty-booking confirm
edge, and the seat-count conservation invariant.

Queue A: boundary_precision_check (seat fill/overflow, empty headcount),
resource_temporal_overlap (aggregate pool, charter whole-van),
compensating_invariant (seat-count conserved).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_operator_headers, make_partner_venue_headers, make_guest_headers,
    get_success_data,
    create_pickup_point_payload, create_guest_payload, create_booking_payload,
    setup_scheduled_departure, setup_scheduled_departure_with_confirmed_stop,
)
from test_helpers import api_client

OP = make_operator_headers()


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check
# ---------------------------------------------------------------------------
def test_seat_capacity_exact_fill_vs_overflow(api):
    """PRD §3.6: "the sum of its current `seats_taken` plus this booking's
    `party_size` must not exceed the departure's `seat_capacity`, and a
    reservation that would overflow the pool is rejected with
    `ERR_SEAT_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/seat_capacity_exact_fill_vs_overflow
    """
    s = setup_scheduled_departure(seat_capacity=12)
    dep_id = s["departure"]["id"]
    pickup_id = s["pickup"]["id"]
    g1 = get_success_data(api.create_guest(create_guest_payload(full_name="G1"), OP))
    g2 = get_success_data(api.create_guest(create_guest_payload(full_name="G2"), OP))
    g3 = get_success_data(api.create_guest(create_guest_payload(full_name="G3"), OP))
    b1 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g1["id"], pickup_id, 6), make_guest_headers(g1["id"])))
    b2 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g2["id"], pickup_id, 6), make_guest_headers(g2["id"])))
    b3 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g3["id"], pickup_id, 1), make_guest_headers(g3["id"])))
    # First reserve: seats_taken 0 -> 6.
    r1 = get_success_data(api.reserve_booking(
        b1["id"], s["departure"]["version"], make_guest_headers(g1["id"])))
    dep_v1 = get_success_data(api.get_departure(dep_id, OP))["version"]
    # Boundary equal: 6 + 6 == 12 -> succeeds.
    r2 = validate_success(api.reserve_booking(b2["id"], dep_v1, make_guest_headers(g2["id"])))
    assert r2["status"] == "RESERVED", f"6+6==12 should reserve, got {r2['status']}"
    dep_after = get_success_data(api.get_departure(dep_id, OP))
    assert dep_after["seats_taken"] == 12, \
        f"expected seats_taken 12, got {dep_after['seats_taken']}"
    # Overflow: 12 + 1 > 12 -> rejected.
    resp = api.reserve_booking(b3["id"], dep_after["version"], make_guest_headers(g3["id"]))
    validate_error(resp, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED.value, expected_status=409)


def test_confirm_empty_booking_set_zero_headcount_edge(api):
    """PRD §3.8: "the departure must have at least one expected guest — its
    `expected_headcount` must be at least 1, meaning at least one booking is
    `RESERVED` or `PAID` — failing which the confirm is rejected with
    `ERR_NO_BOOKINGS`."

    Design: Difficulty/boundary_precision_check/confirm_empty_booking_set_zero_headcount_edge
    """
    # SCHEDULED departure with one CONFIRMED stop but ZERO bookings.
    s = setup_scheduled_departure_with_confirmed_stop(seat_capacity=12, requested_headcount=4)
    resp = api.confirm_departure(s["departure"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_NO_BOOKINGS.value, expected_status=409)


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_shared_van_seat_pool_aggregate_capacity_overlap(api):
    """PRD §3.6: "the sum of its current `seats_taken` plus this booking's
    `party_size` must not exceed the departure's `seat_capacity`, and a
    reservation that would overflow the pool is rejected with
    `ERR_SEAT_CAPACITY_EXCEEDED`."
    PRD §3.3: "the departure reports `seats_taken` as the sum of `party_size`
    over its bookings in `RESERVED`, `PAID`, or `CHECKED_IN`"

    Design: Difficulty/resource_temporal_overlap/shared_van_seat_pool_aggregate_capacity_overlap
    """
    # seat_capacity 10; two reserved party-4 (seats_taken 8); third party-4 (8+4>10) rejected.
    s = setup_scheduled_departure(seat_capacity=10)
    dep_id = s["departure"]["id"]
    pickup_id = s["pickup"]["id"]
    g1 = get_success_data(api.create_guest(create_guest_payload(full_name="G1"), OP))
    g2 = get_success_data(api.create_guest(create_guest_payload(full_name="G2"), OP))
    g3 = get_success_data(api.create_guest(create_guest_payload(full_name="G3"), OP))
    b1 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g1["id"], pickup_id, 4), make_guest_headers(g1["id"])))
    b2 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g2["id"], pickup_id, 4), make_guest_headers(g2["id"])))
    b3 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g3["id"], pickup_id, 4), make_guest_headers(g3["id"])))
    v0 = s["departure"]["version"]
    get_success_data(api.reserve_booking(b1["id"], v0, make_guest_headers(g1["id"])))
    v1 = get_success_data(api.get_departure(dep_id, OP))["version"]
    get_success_data(api.reserve_booking(b2["id"], v1, make_guest_headers(g2["id"])))
    v2 = get_success_data(api.get_departure(dep_id, OP))["version"]
    resp = api.reserve_booking(b3["id"], v2, make_guest_headers(g3["id"]))
    validate_error(resp, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED.value, expected_status=409)
    dep_after = get_success_data(api.get_departure(dep_id, OP))
    assert dep_after["seats_taken"] == 8, \
        f"expected seats_taken 8 after rejected overflow, got {dep_after['seats_taken']}"


def test_private_charter_whole_van_exclusive_occupation(api):
    """PRD §3.6: "If the departure is a private charter, the booking must take
    the whole van — its `party_size` must equal the departure's `seat_capacity`
    — and it must be the only non-terminal booking on that departure; a charter
    booking that does not take every seat, or that is not the sole booking, is
    rejected with `ERR_CHARTER_WHOLE_VAN_REQUIRED`."

    Design: Difficulty/resource_temporal_overlap/private_charter_whole_van_exclusive_occupation
    """
    s = setup_scheduled_departure(seat_capacity=12, is_private_charter=True,
                                  product_overrides={"charter_fee_cents": 5000})
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    # party 6 < seat_capacity 12 on a charter -> rejected.
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 6),
        make_guest_headers(guest["id"])))
    resp = api.reserve_booking(booking["id"], s["departure"]["version"],
                               make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_CHARTER_WHOLE_VAN_REQUIRED.value, expected_status=409)


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant (seat count)
# ---------------------------------------------------------------------------
def test_seat_pool_conserved_under_reserve_then_cancel(api):
    """PRD §3.6: "Cancelling a `RESERVED` booking returns its seats: the
    departure's `seats_taken` and `expected_headcount` are each reduced by the
    booking's `party_size`, and the departure's `version` is incremented."

    Design: Difficulty/compensating_invariant/seat_pool_conserved_under_reserve_then_cancel
    """
    s = setup_scheduled_departure(seat_capacity=12)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 6),
        make_guest_headers(guest["id"])))
    get_success_data(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    seats_after_reserve = get_success_data(api.get_departure(s["departure"]["id"], OP))["seats_taken"]
    assert seats_after_reserve == 6, f"expected 6 after reserve, got {seats_after_reserve}"
    get_success_data(api.cancel_booking(booking["id"], make_guest_headers(guest["id"])))
    dep_final = get_success_data(api.get_departure(s["departure"]["id"], OP))
    assert dep_final["seats_taken"] == 0, \
        f"seat pool not conserved: expected 0, got {dep_final['seats_taken']}"
