"""Validation precedence, studio/artist temporal overlap, and the zero-seat
boundary.

Difficulty queue (A): priority_pair_validation_conflict, resource_temporal_overlap,
boundary_precision_check (last-seat half).
"""
from test_helpers import (
    validate_success, get_success_data, validate_error,
    make_customer_headers, TEST_USERS, ApiErrorId,
    create_studio, create_artist, create_customer,
    setup_open_event_with_customer, book_reservation, event_current_version,
    set_clock,
)

MANAGER = TEST_USERS["manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ─── priority_pair_validation_conflict ──────────────────────────────────────

def test_reservation_on_draft_event_oversold_reports_invalid_state(api):
    """PRD §2.6: "then the target's state is checked for transition validity
    (ERR_INVALID_STATE), and then operation-specific business rules apply."
    PRD §3.4: "The parent event must be in OPEN or FULL status for a reservation to
    be created; otherwise the create is rejected with ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_seats
    """
    set_clock("2026-04-01T00:00:00Z")
    studio = create_studio(room_capacity_seats=10, name="P1")
    # Event stays DRAFT (never scheduled/opened); capacity 5, request 99 seats.
    event = get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "Draft Class", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 5, "price_cents_per_seat": 4500}, MANAGER))
    customer = create_customer(email="p1@x.com")

    resp = api.create_reservation({
        "event_id": event["id"], "customer_id": customer["id"],
        "booking_mode": "PUBLIC", "seats": 99,
        "expected_event_version": event["version"]}, make_customer_headers(customer["id"]))
    # State gate (universal, §2.6) precedes the seat-capacity business rule.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_reservation_on_draft_event_oversold_is_409(api):
    """PRD §2.6: "then the target's state is checked for transition validity
    (ERR_INVALID_STATE), and then operation-specific business rules apply."
    PRD §3.4: "The parent event must be in OPEN or FULL status for a reservation to
    be created; otherwise the create is rejected with ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_seats
    """
    set_clock("2026-04-01T00:00:00Z")
    studio = create_studio(room_capacity_seats=10, name="P1b")
    event = get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "Draft Class B", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T13:00:00Z", "end_utc": "2026-04-05T15:00:00Z",
        "seats_capacity": 3, "price_cents_per_seat": 4500}, MANAGER))
    customer = create_customer(email="p1b@x.com")

    resp = api.create_reservation({
        "event_id": event["id"], "customer_id": customer["id"],
        "booking_mode": "PUBLIC", "seats": 50,
        "expected_event_version": event["version"]}, make_customer_headers(customer["id"]))
    assert resp.status_code == 409, f"ERR_INVALID_STATE is HTTP 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ─── resource_temporal_overlap ──────────────────────────────────────────────

def test_studio_halfopen_overlap_rejected(api):
    """PRD §3.2: "At creation, and again when the event is scheduled, the system
    rejects the event if any other non-CANCELLED StudioEvent in the same studio
    occupies an overlapping time window. Windows are half-open: two events overlap
    when one starts strictly before the other ends and ends strictly after the other
    starts ... A conflict is rejected with ERR_STUDIO_TIME_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_studio_halfopen_overlap
    """
    set_clock("2026-04-01T00:00:00Z")
    studio = create_studio(room_capacity_seats=10, name="T1")
    get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "First", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))

    resp = api.create_event({
        "studio_id": studio["id"], "title": "Overlap", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T11:00:00Z", "end_utc": "2026-04-05T13:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_STUDIO_TIME_CONFLICT)


def test_studio_adjacent_event_end_equals_start_allowed(api):
    """PRD §3.2: "back-to-back events where one's end_utc exactly equals the next's
    start_utc are adjacent and allowed, not a conflict."

    Design: Difficulty/resource_temporal_overlap/rto_studio_halfopen_overlap
    """
    set_clock("2026-04-01T00:00:00Z")
    studio = create_studio(room_capacity_seats=10, name="T1adj")
    get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "First", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))

    resp = api.create_event({
        "studio_id": studio["id"], "title": "Adjacent", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T12:00:00Z", "end_utc": "2026-04-05T14:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER)
    validate_success(resp, expected_status=201)


def test_artist_double_booking_inside_30m_buffer_rejected(api):
    """PRD §3.2: "an artist may not hold another ASSIGNED assignment on an event whose
    time window, widened by a 30-minute travel buffer on each side, overlaps this
    event's window ... a clear gap of exactly 30 minutes between two events is
    permitted, but anything closer is a double-booking and is rejected with
    ERR_ARTIST_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_artist_buffered_gap
    """
    set_clock("2026-04-01T00:00:00Z")
    sa = create_studio(room_capacity_seats=10, name="SA")
    sb = create_studio(room_capacity_seats=10, name="SB")
    artist = create_artist(full_name="Ne")
    ea = get_success_data(api.create_event({
        "studio_id": sa["id"], "title": "A", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-06T10:00:00Z", "end_utc": "2026-04-06T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))
    # Event B in a different studio (no studio conflict), 15-min gap from A's end.
    eb = get_success_data(api.create_event({
        "studio_id": sb["id"], "title": "B", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-06T12:15:00Z", "end_utc": "2026-04-06T14:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))
    get_success_data(api.create_assignment({"event_id": ea["id"], "artist_id": artist["id"]}, MANAGER))

    resp = api.create_assignment({"event_id": eb["id"], "artist_id": artist["id"]}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_ARTIST_DOUBLE_BOOKED)


def test_artist_exactly_30m_gap_allowed(api):
    """PRD §3.2: "a clear gap of exactly 30 minutes between two events is permitted,
    but anything closer is a double-booking and is rejected with
    ERR_ARTIST_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_artist_buffered_gap
    """
    set_clock("2026-04-01T00:00:00Z")
    sa = create_studio(room_capacity_seats=10, name="SA2")
    sb = create_studio(room_capacity_seats=10, name="SB2")
    artist = create_artist(full_name="Ne2")
    ea = get_success_data(api.create_event({
        "studio_id": sa["id"], "title": "A", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-06T10:00:00Z", "end_utc": "2026-04-06T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))
    # Event B starts 12:30 — exactly a 30-minute gap from A's 12:00 end.
    eb = get_success_data(api.create_event({
        "studio_id": sb["id"], "title": "B", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-06T12:30:00Z", "end_utc": "2026-04-06T14:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))
    get_success_data(api.create_assignment({"event_id": ea["id"], "artist_id": artist["id"]}, MANAGER))

    resp = api.create_assignment({"event_id": eb["id"], "artist_id": artist["id"]}, MANAGER)
    validate_success(resp, expected_status=201)


# ─── boundary_precision_check (last-seat / zero-available) ───────────────────

def test_last_seat_fills_event_full(api):
    """PRD §3.3: "whenever a seat-consuming mutation drives seats_available to
    exactly 0, the system transitions the event OPEN → FULL."

    Design: Difficulty/boundary_precision_check/bpc_last_seat_zero_available
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=2, seats_capacity=2, price_cents_per_seat=4500, clock=None)
    book_reservation(event["id"], customer["id"], seats=2)

    after = get_success_data(api.get_event(event["id"], MANAGER))
    assert after["seats_available"] == 0, f"booking the last 2 of 2 seats -> 0 available"
    assert after["status"] == "FULL"


def test_walk_in_rejected_when_zero_seats_available(api):
    """PRD §2.8: "when a walk-in is registered, its party_size must not exceed the
    current seats_available. A request that would exceed available seats is rejected
    with ERR_INSUFFICIENT_SEATS (HTTP 409). Because a FULL event has zero seats
    available, it still rejects further seat-consuming bookings on this rule."

    Design: Difficulty/boundary_precision_check/bpc_last_seat_zero_available
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=2, seats_capacity=2, price_cents_per_seat=4500, clock=None)
    book_reservation(event["id"], customer["id"], seats=2)  # fills to FULL

    resp = api.create_walk_in(
        {"event_id": event["id"], "party_name": "Late", "party_size": 1}, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SEATS)
