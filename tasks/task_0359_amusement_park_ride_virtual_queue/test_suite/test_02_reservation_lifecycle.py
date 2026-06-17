"""Reservation and ReturnWindow lifecycle tests.

Covers initial state, terminal-state lockdown, invalid transitions, the
non-linear BOOKED<->REDISTRIBUTED and OPEN<->EXHAUSTED cycles, the
book-then-cancel compensating invariant, and the redeem-credits-counters flow.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_park, set_clock, create_ride, create_window, create_guest,
    book_vq, confirm, setup_park_ride_window, setup_booked_reservation,
    setup_held_reservation, setup_redistributed_single_window,
    make_park_admin_headers, make_ride_operator_headers, make_guest_headers,
)

ADMIN = make_park_admin_headers()
OPERATOR = make_ride_operator_headers()


def test_reservation_starts_held(api):
    """PRD §3.3: "Every reservation begins `HELD`, with its capacity provisionally
    debited, and records a `redistributed_from_window_id` that is null unless and
    until a ride-down redistribution moves it."

    Design: Corner/state_machines/reservation_starts_in_held_initial_state
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=100)
    guest = create_guest(park["id"], full_name="G1")
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": guest["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": window["version"]},
        make_guest_headers(guest["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["reservation_status"] == "HELD", \
        f"new reservation must be HELD, got {data['reservation_status']}"


def test_confirm_already_booked_reservation_rejected(api):
    """PRD §3.3: "Confirmation is allowed only when the reservation is `HELD`, the
    parent ride is `OPEN`, and — for a `VIRTUAL_QUEUE` reservation — the owning
    window is `OPEN`; otherwise it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_already_booked_reservation_returns_invalid_state
    """
    park, ride, window, guest, booked = setup_booked_reservation()
    resp = api.confirm_reservation(booked["id"], make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_redeem_already_redeemed_reservation_rejected(api):
    """PRD §3.4: "an attempt against a reservation not in `BOOKED` status, or a ride
    not `OPEN`, is rejected with `ERR_INVALID_STATE`."

    A REDEEMED reservation is terminal; a second redeem is rejected.

    Design: Corner/state_machines/redeem_from_terminal_redeemed_returns_invalid_state
    """
    # Clock at 10:30 is inside [10:00, 11:00) so the first redeem succeeds.
    park, ride, window, guest, booked = setup_booked_reservation(clock="2026-06-15T10:30:00.000Z")
    first = api.redeem_reservation(booked["id"], OPERATOR)
    validate_success(first)
    second = api.redeem_reservation(booked["id"], OPERATOR)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)


def test_declare_down_on_down_ride_rejected(api):
    """PRD §3.7: "A `RideOperator` declares a ride down, allowed only when the ride
    is `OPEN`."

    A second declare-down on an already-DOWN ride is rejected.

    Design: Corner/state_machines/declare_down_on_already_down_ride_returns_invalid_state
    """
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=100)
    validate_success(api.declare_down(ride["id"], OPERATOR))
    resp = api.declare_down(ride["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_reservation_cycle_booked_redistributed_booked(api):
    """PRD §3.7: "Every reservation on the ride in `BOOKED` status is redistributed:
    it moves `BOOKED → REDISTRIBUTED`, its `redistributed_from_window_id` is set to
    the window it currently occupies".
    PRD §3.7: "A reservation that finds a replacement has its `return_window_id` set
    to the chosen window, moves `REDISTRIBUTED → BOOKED`, and increments the
    replacement window's `reserved_count` and the ride's `booked_slot_count` each by one".

    Two windows W1 (10:00-11:00) and W2 (11:00-12:00). Book+confirm on W1, declare
    DOWN (reservation REDISTRIBUTED), advance clock to 11:30 so W1 elapses, restore
    (W1 -> EXPIRED, W2 stays valid), redistribute re-homes into W2.

    Design: Difficulty/non_linear_state_machine/reservation_cycle_booked_redistributed_booked
    """
    park = create_park()
    set_clock(park["id"], "2026-06-15T09:00:00.000Z")
    ride = create_ride(park["id"], hourly_throughput=100)
    w1 = create_window(ride["id"], "2026-06-15T10:00:00.000Z", "2026-06-15T11:00:00.000Z")
    w2 = create_window(ride["id"], "2026-06-15T11:00:00.000Z", "2026-06-15T12:00:00.000Z")
    guest = create_guest(park["id"], full_name="G1")
    res = book_vq(ride["id"], guest["id"], w1["id"], w1["version"])
    confirm(res["id"], guest["id"])
    validate_success(api.declare_down(ride["id"], OPERATOR))
    set_clock(park["id"], "2026-06-15T11:30:00.000Z")
    validate_success(api.restore_ride(ride["id"], OPERATOR))
    validate_success(api.redistribute(ride["id"], OPERATOR))

    data = validate_success(api.get_reservation(res["id"], ADMIN))
    assert data["reservation_status"] == "BOOKED", \
        f"redistributed reservation must re-enter BOOKED, got {data['reservation_status']}"
    assert data["return_window_id"] == w2["id"], \
        f"reservation must move to W2, got {data['return_window_id']}"
    assert data["redistributed_from_window_id"] == w1["id"], \
        f"redistributed_from_window_id must record W1, got {data['redistributed_from_window_id']}"


def test_return_window_cycle_open_exhausted_open(api):
    """PRD §3.4: "It tips to `EXHAUSTED` the instant a held reservation drives
    `reserved_count` to `slot_capacity` or above, and it bubbles back to `OPEN`
    whenever a forfeit, cancellation, redemption, or redistribution frees a slot so
    that `reserved_count` falls below `slot_capacity`, provided the park's
    `current_utc` is still before `window_end_utc`."

    Ride R5 (throughput 5) -> 60-min window capacity 2. Two HELD reservations fill
    it to EXHAUSTED; cancelling one frees a slot -> window returns to OPEN.

    Design: Difficulty/non_linear_state_machine/return_window_cycle_open_exhausted_open
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5)
    ga = create_guest(park["id"], full_name="GA")
    gb = create_guest(park["id"], full_name="GB")
    res_a = book_vq(ride["id"], ga["id"], window["id"], window["version"])
    res_b = book_vq(ride["id"], gb["id"], window["id"], res_a["version"])

    exhausted = validate_success(api.get_return_window(window["id"], ADMIN))
    assert exhausted["window_status"] == "EXHAUSTED"
    assert exhausted["reserved_count"] == 2

    validate_success(api.cancel_reservation(res_b["id"], make_guest_headers(gb["id"])))
    data = validate_success(api.get_return_window(window["id"], ADMIN))
    assert data["window_status"] == "OPEN", \
        f"freeing a slot must reopen the window, got {data['window_status']}"
    assert data["reserved_count"] == 1, f"expected reserved_count 1, got {data['reserved_count']}"


def test_window_slot_conserved_under_book_then_cancel(api):
    """PRD §3.3: "Cancellation of a `VIRTUAL_QUEUE` reservation credits the slot back
    — decrementing the window's `reserved_count` and the ride's `booked_slot_count`
    each by one — and if the window had been `EXHAUSTED` and now sits below capacity
    while not yet expired, it bubbles back from `EXHAUSTED` to `OPEN`".

    A booking (reserved_count 0->1) paired with its compensating cancel (1->0)
    leaves reserved_count and booked_slot_count exactly at their pre-book value 0.

    Design: Difficulty/compensating_invariant/window_slot_conserved_under_book_then_cancel
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5)
    guest = create_guest(park["id"], full_name="GA")
    res = book_vq(ride["id"], guest["id"], window["id"], window["version"])
    cancelled = validate_success(api.cancel_reservation(res["id"], make_guest_headers(guest["id"])))
    assert cancelled["reservation_status"] == "FORFEITED"

    win = validate_success(api.get_return_window(window["id"], ADMIN))
    assert win["reserved_count"] == 0, f"reserved_count must return to 0, got {win['reserved_count']}"
    assert win["window_status"] == "OPEN"
    ride_data = validate_success(api.get_ride(ride["id"], ADMIN))
    assert ride_data["booked_slot_count"] == 0, \
        f"booked_slot_count must return to 0, got {ride_data['booked_slot_count']}"


def test_redeem_within_window_credits_counters(api):
    """PRD §3.4: "A successful redemption moves the reservation `BOOKED → REDEEMED`;
    for a `VIRTUAL_QUEUE` reservation it decrements the owning window's
    `reserved_count` by one and the ride's `booked_slot_count` by one".

    Design: Corner/endpoints/redeem_within_window_succeeds_and_credits_counters
    """
    # Ride R5 60-min window capacity 2; clock at 10:30 inside [10:00, 11:00).
    park, ride, window, guest, booked = setup_booked_reservation(
        hourly_throughput=5, clock="2026-06-15T10:30:00.000Z",
    )
    data = validate_success(api.redeem_reservation(booked["id"], OPERATOR))
    assert data["reservation_status"] == "REDEEMED"

    win = validate_success(api.get_return_window(window["id"], ADMIN))
    assert win["reserved_count"] == 0, f"expected reserved_count 0, got {win['reserved_count']}"
    ride_data = validate_success(api.get_ride(ride["id"], ADMIN))
    assert ride_data["booked_slot_count"] == 0, \
        f"expected booked_slot_count 0, got {ride_data['booked_slot_count']}"


def test_single_rider_does_not_consume_slot(api):
    """PRD §3.3: "or `SINGLE_RIDER`, a loose-fill standby for individual seats that
    does not consume any window's `slot_capacity`."
    PRD §3.3: "A `SINGLE_RIDER` reservation consumes no slot and so leaves
    `reserved_count` and the window status untouched."

    Design: Corner/calculations/single_rider_does_not_consume_window_slot
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5, ride_overrides={"single_rider_enabled": True})
    guest = create_guest(park["id"], full_name="G1")
    res = validate_success(
        api.create_reservation(
            {"ride_id": ride["id"], "guest_id": guest["id"], "return_window_id": window["id"],
             "queue_type": "SINGLE_RIDER", "expected_return_window_id_version": window["version"]},
            make_guest_headers(guest["id"]),
        ),
        expected_status=201,
    )
    assert res["reservation_status"] == "HELD"
    win = validate_success(api.get_return_window(window["id"], ADMIN))
    assert win["reserved_count"] == 0, \
        f"SINGLE_RIDER must not debit reserved_count, got {win['reserved_count']}"
    assert win["window_status"] == "OPEN"
