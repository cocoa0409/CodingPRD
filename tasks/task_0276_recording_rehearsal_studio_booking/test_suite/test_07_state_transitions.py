"""State-machine precondition and invalid-transition corners (Corner: state_machines)."""
from test_helpers import (
    setup_studio_room_client,
    setup_gear_item,
    create_booking,
    pay_deposit,
    confirm,
    set_clock,
    check_in,
    check_out,
    add_gear_rental,
    api_client,
    TEST_USERS,
    make_client_headers,
    get_success_data,
    validate_success,
    validate_error,
    get_booking,
)

SM = TEST_USERS["studio_manager_headers"]


def test_confirm_without_deposit_returns_invalid_state():
    """PRD §3.2: "It is permitted only when the booking is currently HELD, when its
    settlement_status is DEPOSIT_PAID (the deposit payment has cleared), and when the room is
    bookable".
    PRD §3.2: "If the booking is not in HELD when confirmation is attempted, the transition is
    undefined and the request fails with ERR_INVALID_STATE."

    Design: Corner/state_machines/confirm_without_deposit_returns_invalid_state
    """
    studio, room, client = setup_studio_room_client(studio_overrides={"deposit_pct": 0.60})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    res = api_client.confirm_booking(booking["id"], SM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_already_cancelled_booking_returns_invalid_state():
    """PRD §3.7: "A cancel against a booking in any other schedule state is an undefined
    transition and fails with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_already_cancelled_booking_returns_invalid_state
    """
    studio, room, client = setup_studio_room_client(studio_overrides={"deposit_pct": 0.60})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    headers = make_client_headers(client["id"])
    get_success_data(api_client.cancel_booking(booking["id"], headers))
    res = api_client.cancel_booking(booking["id"], headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_confirmed_after_start_returns_cancel_too_late():
    """PRD §3.7: "Cancelling a CONFIRMED booking carries one extra guard: the clock must still be
    before start_at, because a session cannot be cancelled once it has begun; a cancel attempted
    on a CONFIRMED booking at or after start_at is rejected with ERR_CANCEL_TOO_LATE."

    Design: Corner/state_machines/cancel_confirmed_after_start_returns_cancel_too_late
    """
    studio, room, client = setup_studio_room_client(
        studio_overrides={"deposit_pct": 0.60, "cancellation_tier_hours": 48})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    pay_deposit(booking, client, 14400)
    confirm(booking)
    set_clock("2026-07-10T09:30:00Z")  # after start_at
    res = api_client.cancel_booking(booking["id"], make_client_headers(client["id"]))
    validate_error(res, "ERR_CANCEL_TOO_LATE", expected_status=409)


def test_check_in_before_start_returns_invalid_state():
    """PRD §3.3: "Check-in is permitted only when the booking is CONFIRMED, when the clock has
    reached or passed start_at (the current instant is at or after the scheduled start)".
    PRD §2.7: "Any attempt to drive a transition that is not defined from the resource's current
    schedule_status, settlement_status, contract status, or delivery status is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/check_in_before_start_returns_invalid_state
    """
    studio, room, client = setup_studio_room_client(studio_overrides={"deposit_pct": 0.60})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    pay_deposit(booking, client, 14400)
    confirm(booking)
    # clock still at base 2026-07-01, before start_at
    res = api_client.check_in_booking(booking["id"], SM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_check_in_requires_engineer_for_gear_returns_engineer_required():
    """PRD §3.3: "every GearRental on the booking whose underlying GearItem has requires_engineer
    set to true must be matched by at least one ASSIGNED EngineerAssignment on the same booking.
    If a piece of engineer-required gear is reserved with no engineer present, check-in is refused
    with ERR_ENGINEER_REQUIRED."

    Design: Corner/state_machines/check_in_requires_engineer_for_gear_returns_engineer_required
    """
    studio, room, client = setup_studio_room_client(studio_overrides={"deposit_pct": 0.60})
    gear = setup_gear_item(studio["id"], name="Console", total_units=1, daily_rate_cents=2000,
                           requires_engineer=True)
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    add_gear_rental(booking, gear, 1, expected_version=booking["version"])
    pay_deposit(booking, client, 14400)
    confirm(booking)
    set_clock("2026-07-10T09:05:00Z")
    res = api_client.check_in_booking(booking["id"], SM)
    validate_error(res, "ERR_ENGINEER_REQUIRED", expected_status=422)


def test_hold_expiry_sweep_auto_cancels_unconfirmed_booking():
    """PRD §3.7: "a sweep capability releases every still-HELD booking whose hold_expires_at has
    fallen before the current clock instant. Each swept booking has its schedule_status driven to
    CANCELLED and its children released".
    PRD §3.7: "The sweep reports how many bookings it released and which ones, returning a
    released_count and the list of released_booking_ids."

    Design: Corner/state_machines/hold_expiry_sweep_auto_cancels_unconfirmed_booking
    """
    studio, room, client = setup_studio_room_client(studio_overrides={"deposit_pct": 0.60})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    set_clock("2026-07-02T09:00:00Z")  # past hold_expires_at (created at 2026-07-01T08:00 + 24h)
    res = api_client.release_expired_holds(SM)
    data = validate_success(res, 200)
    assert data["released_count"] == 1, data["released_count"]
    assert get_booking(booking["id"])["schedule_status"] == "CANCELLED"


def test_terminal_completed_booking_rejects_further_cancel():
    """PRD §3.7: "A cancel against a booking in any other schedule state is an undefined
    transition and fails with ERR_INVALID_STATE."
    PRD §2.7: "The terminal calendar states are `COMPLETED` and `CANCELLED`".

    Design: Corner/state_machines/terminal_completed_booking_rejects_further_cancel
    """
    studio, room, client = setup_studio_room_client(
        studio_overrides={"deposit_pct": 0.60, "overtime_grace_minutes": 10})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    pay_deposit(booking, client, 14400)
    confirm(booking)
    set_clock("2026-07-10T09:05:00Z")
    check_in(booking)
    check_out(booking, "2026-07-10T12:30:00Z")  # COMPLETED (terminal)
    res = api_client.cancel_booking(booking["id"], make_client_headers(client["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
