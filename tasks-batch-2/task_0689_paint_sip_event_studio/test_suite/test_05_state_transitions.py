"""Invalid transitions, preconditions, idempotency, and initial state.

Corner queue (B): state_machines section.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_customer_headers, TEST_USERS, ApiErrorId,
    create_studio, create_artist, create_customer,
    setup_open_event_with_customer, book_reservation, event_current_version,
    set_clock,
)

MANAGER = TEST_USERS["manager_headers"]


def test_cancel_reservation_twice_invalid_state(api):
    """PRD §3.9: "A Customer (for their own reservation) or a manager may cancel a
    reservation that is in HELD or CONFIRMED status, provided the parent event is
    neither CLOSED nor CANCELLED; a cancel attempt against a closed or cancelled
    event is rejected with ERR_INVALID_STATE."
    PRD §3.10: "A reservation reaching NO_SHOW is terminal, as is one reaching
    CANCELLED."

    Design: Corner/state_machines/cancel_reservation_twice_invalid_state
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=2)
    ch = make_customer_headers(customer["id"])
    get_success_data(api.cancel_reservation(res["id"], ch))

    resp = api.cancel_reservation(res["id"], ch)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_open_event_from_draft_invalid_state(api):
    """PRD §3.3: "From SCHEDULED, a manager opens the event for booking, advancing it
    SCHEDULED → OPEN ... An attempt to schedule an event that is not in DRAFT, or any
    other transition attempted from an incompatible state, is rejected with
    ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/open_event_from_draft_invalid_state
    """
    studio = create_studio(room_capacity_seats=10, name="SM2")
    event = get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "SM2 Class", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))
    resp = api.open_event(event["id"], MANAGER)  # DRAFT, never SCHEDULED
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_schedule_event_without_artist_invalid_state(api):
    """PRD §3.3: "Scheduling has three preconditions: at least one ArtistAssignment
    in status ASSIGNED must reference the event, the hosting studio must be ACTIVE,
    and there must be no room-time conflict with another non-CANCELLED event in the
    same studio ... any other transition attempted from an incompatible state, is
    rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/schedule_event_without_artist_invalid_state
    """
    studio = create_studio(room_capacity_seats=10, name="SM3")
    event = get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "SM3 Class", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))
    resp = api.schedule_event(event["id"], MANAGER)  # no ASSIGNED artist
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_close_event_before_start_returns_not_started(api):
    """PRD §3.10: "Closing requires that the logical clock has reached or passed the
    event's start_utc; closing before the event has started is rejected with
    ERR_EVENT_NOT_STARTED (HTTP 409)."

    Design: Corner/state_machines/close_event_before_start_returns_not_started
    """
    set_clock("2026-04-01T00:00:00Z")
    event, _customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500,
        clock=None, start_utc="2026-04-10T10:00:00Z", end_utc="2026-04-10T12:00:00Z")
    resp = api.close_event(event["id"], MANAGER)  # clock 2026-04-01 < start 2026-04-10
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_STARTED)


def test_confirm_unpaid_reservation_invalid_state(api):
    """PRD §3.6: "confirmation requires both that payment_status is PAID and that the
    parent event is in OPEN or FULL status, and an attempt that violates either is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/confirm_unpaid_reservation_invalid_state
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=2)  # HELD, UNPAID
    resp = api.confirm_reservation(res["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_new_reservation_initial_state_held_unpaid(api):
    """PRD §3.4: "A new reservation begins with booking status HELD and payment status
    UNPAID."
    PRD §2.4: "The version field is an integer that begins at its initial value and
    increments by one on every mutation."

    Design: Corner/state_machines/new_reservation_initial_state_held_unpaid
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    ver = event_current_version(event["id"])
    resp = api.create_reservation({
        "event_id": event["id"], "customer_id": customer["id"],
        "booking_mode": "PUBLIC", "seats": 1, "expected_event_version": ver},
        make_customer_headers(customer["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "HELD"
    assert data["payment_status"] == "UNPAID"
    assert data["version"] == 1, f"reservation version begins at 1, got {data['version']}"
