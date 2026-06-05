"""Booking creation gates and lifecycle: initial state, invalid transitions,
terminal lockdown, idempotency, OCC on the calendar version, min-nights,
listing-bookability, date-range, availability overlap, and body-FK integrity.

Covers difficulty rules boundary_precision_check (min-nights half) and the
optimistic-concurrency / corner state_machines / validations booking instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    make_host_headers, make_guest_headers,
    create_host, create_guest, create_listed_listing, create_draft_listing,
    add_rate_plan, get_calendar_version, create_booking,
    create_booking_payload,
)


# ==========================================================================
# Difficulty: boundary_precision_check (min_nights >= boundary)
# ==========================================================================
def test_min_nights_below_boundary_rejected(api):
    """PRD §3.4: "The stay length, `nights`, is the number of nights from
    check-in to checkout; it must be at least the listing's `min_nights`, and a
    shorter stay is rejected with `ERR_MIN_NIGHTS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/min_nights_boundary_on_create_booking
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host, listing_overrides={"min_nights": 3})
    cv = get_calendar_version(listing["id"], headers=make_guest_headers(guest["id"]))
    resp = api.create_booking(
        create_booking_payload(listing["id"], guest["id"], cv,
                               check_in="2026-07-10", check_out="2026-07-12"),
        headers=make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_MIN_NIGHTS.value)


def test_min_nights_at_boundary_succeeds(api):
    """PRD §3.4: "it must be at least the listing's `min_nights`, and a shorter
    stay is rejected with `ERR_MIN_NIGHTS` (HTTP 422)."

    Boundary precision: nights == min_nights (>= not >) must succeed.

    Design: Difficulty/boundary_precision_check/min_nights_boundary_on_create_booking
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host, listing_overrides={"min_nights": 3})
    cv = get_calendar_version(listing["id"], headers=make_guest_headers(guest["id"]))
    resp = api.create_booking(
        create_booking_payload(listing["id"], guest["id"], cv,
                               check_in="2026-07-10", check_out="2026-07-13"),
        headers=make_guest_headers(guest["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["nights"] == 3, f"3 nights == min_nights should pass, got {data['nights']}"


# ==========================================================================
# Cross-cutting: optimistic concurrency on the calendar version
# ==========================================================================
def test_booking_correct_calendar_version_succeeds_and_bumps(api):
    """PRD §2.6: "creating a booking (which synthesizes a booking-origin calendar
    block) requires `expected_listing_calendar_version` to equal the listing's
    live `calendar_version`; if the calendar has moved forward since the guest
    read availability, the booking request is rejected with
    `ERR_STALE_CALENDAR_VERSION` (HTTP 412)."
    PRD §2.4: "`calendar_version` ... starts at 1 and advances by 1 every time
    an `ACTIVE` calendar block is created on the listing or an `ACTIVE` block is
    released."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_booking_succeeds_and_bumps
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    cv = get_calendar_version(listing["id"], headers=make_host_headers(host["id"]))
    resp = api.create_booking(
        create_booking_payload(listing["id"], guest["id"], cv),
        headers=make_guest_headers(guest["id"]))
    booking = validate_success(resp, expected_status=201)
    assert booking["status"] == "REQUESTED"
    after_cv = get_calendar_version(listing["id"], headers=make_host_headers(host["id"]))
    assert after_cv == cv + 1, \
        f"calendar_version should advance by 1 (was {cv}), got {after_cv}"


# ==========================================================================
# Corner: state_machines (booking)
# ==========================================================================
def test_booking_initial_state_is_requested(api):
    """PRD §3.4: "Reservation completes the step: a fresh `BOOKING`-source
    calendar block is created `ACTIVE`, the booking's `calendar_block_id` is set
    to it, the listing's `calendar_version` advances by 1, each `CONNECTED` or
    `ERROR` channel's `pending_sync_count` is bumped by 1, and the booking enters
    `REQUESTED`."

    Design: Corner/state_machines/booking_initial_state_is_requested
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    booking = create_booking(host, listing, guest)
    assert booking["status"] == "REQUESTED", \
        f"Fresh booking should be REQUESTED, got {booking['status']}"


def test_confirm_from_requested_invalid_state(api):
    """PRD §3.6: "Once a booking is `APPROVED`, the booking's own guest confirms
    it, advancing `APPROVED` to `CONFIRMED`."
    PRD §2.9: "then whether the requested state transition is defined from the
    resource's current state (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/confirm_from_requested_invalid_state
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    booking = create_booking(host, listing, guest)
    resp = api.confirm_booking(booking["id"], headers=make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_declined_terminal_lockdown(api):
    """PRD §3.5: "Or the host may decline, advancing `SCREENING` to `DECLINED`
    (a terminal state)."
    PRD §2.9: "then whether the requested state transition is defined from the
    resource's current state (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/cancel_already_declined_terminal_lockdown
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    booking = create_booking(host, listing, guest)
    api.screen_booking(booking["id"], headers=make_host_headers(host["id"]))
    api.decline_booking(booking["id"], headers=make_host_headers(host["id"]))
    resp = api.cancel_booking(booking["id"], headers=make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_screen_twice_idempotency_invalid_state(api):
    """PRD §3.5: "Screening begins when the owning host moves a booking from
    `REQUESTED` to `SCREENING`. This is permitted only while the booking is
    `REQUESTED` and only for the host who owns the booking's listing; otherwise
    `ERR_INVALID_STATE` or `ERR_NOT_RESOURCE_OWNER` applies."

    Design: Corner/state_machines/screen_twice_idempotency_invalid_state
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    booking = create_booking(host, listing, guest)
    api.screen_booking(booking["id"], headers=make_host_headers(host["id"]))
    resp = api.screen_booking(booking["id"], headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Corner: validations (booking creation gates)
# ==========================================================================
def test_booking_on_snoozed_listing_not_bookable(api):
    """PRD §3.4: "The target listing must be `LISTED` — a `SNOOZED` or `DRAFT`
    listing rejects the request with `ERR_LISTING_NOT_BOOKABLE` (HTTP 409)."

    Design: Corner/validations/booking_on_snoozed_listing_not_bookable
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    api.snooze_listing(listing["id"], headers=make_host_headers(host["id"]))
    cv = get_calendar_version(listing["id"], headers=make_guest_headers(guest["id"]))
    resp = api.create_booking(
        create_booking_payload(listing["id"], guest["id"], cv),
        headers=make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_BOOKABLE.value)


def test_booking_inverted_date_range_rejected(api):
    """PRD §3.4: "The `check_out` must be strictly after `check_in` and both must
    be valid dates, else `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/booking_inverted_date_range_rejected
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    cv = get_calendar_version(listing["id"], headers=make_guest_headers(guest["id"]))
    resp = api.create_booking(
        create_booking_payload(listing["id"], guest["id"], cv,
                               check_in="2026-07-13", check_out="2026-07-10"),
        headers=make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)


def test_booking_overlap_dates_unavailable(api):
    """PRD §3.4: "The requested half-open interval must not overlap any `ACTIVE`
    block and must honor the `gap_nights` buffer on both sides, else
    `ERR_DATES_UNAVAILABLE`."

    Design: Corner/validations/booking_overlap_exact_dates_unavailable
    """
    host = create_host()
    guest_a = create_guest(email="ga@x.com", govt_id_verified=True)
    guest_b = create_guest(email="gb@x.com", govt_id_verified=True)
    _, listing = create_listed_listing(host=host, listing_overrides={"gap_nights": 0})
    create_booking(host, listing, guest_a, check_in="2026-07-10", check_out="2026-07-13")
    cv = get_calendar_version(listing["id"], headers=make_guest_headers(guest_b["id"]))
    resp = api.create_booking(
        create_booking_payload(listing["id"], guest_b["id"], cv,
                               check_in="2026-07-11", check_out="2026-07-14"),
        headers=make_guest_headers(guest_b["id"]))
    validate_error(resp, ApiErrorId.ERR_DATES_UNAVAILABLE.value)


def test_booking_fk_guest_not_found(api):
    """PRD §2.8: "Body foreign keys — `listing_id`, `guest_id`,
    `security_deposit_id`, `channel_connection_id`, and `booking_id` where they
    appear in a request body — are validated separately: if a body foreign key
    names a resource that does not exist, the request is rejected with
    `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_booking_fk_guest_not_found_returns_404
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    cv = get_calendar_version(listing["id"], headers=make_guest_headers(guest["id"]))
    resp = api.create_booking(
        create_booking_payload(listing["id"], NON_EXISTENT_UUID, cv),
        headers=make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


def test_booking_computed_nights_from_dates(api):
    """PRD §3.4: "The stay length, `nights`, is the number of nights from
    check-in to checkout."

    Design: Corner/entities/booking_computed_nights_ignores_client_input
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_listed_listing(host=host)
    booking = create_booking(host, listing, guest, check_in="2026-07-10", check_out="2026-07-13")
    assert booking["nights"] == 3, f"Expected 3 computed nights, got {booking['nights']}"
