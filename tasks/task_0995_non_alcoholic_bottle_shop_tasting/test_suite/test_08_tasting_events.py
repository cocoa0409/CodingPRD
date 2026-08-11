"""Tasting events and seats: time-range validation, capacity boundary,
booking-window dependency on event status, seat-cancel compensation, seat
booking OCC, and event terminal lockdown (PRD §3.5, §3.6, §2.4, §2.7).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_tasting_seat,
    book_seat_for_member,
    book_seat_payload,
    create_tasting_event_payload,
    get_event,
    get_member,
    make_category,
    make_lot,
    make_member,
    make_member_headers,
    make_published_event,
    make_sku,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
STAFF = TEST_USERS["shop_staff_headers"]


class TestEventTimeRange:
    def test_equal_start_and_end_rejected(self, api):
        """PRD §3.5: "a `starts_at` and `ends_at` (both ISO-8601 UTC, with
        `ends_at` strictly after `starts_at` — anything else is rejected with
        `ERR_INVALID_TIME_RANGE`)"

        Design: Difficulty/resource_temporal_overlap/tasting_event_time_range_validation_half_open
        """
        set_clock()
        host = make_member(email="host15@x.com", date_of_birth="1980-01-01")
        payload = create_tasting_event_payload(
            host["id"],
            starts_at="2026-05-10T10:00:00Z",
            ends_at="2026-05-10T10:00:00Z",
        )
        resp = api.create_tasting_event(payload, STAFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)

    def test_end_before_start_rejected(self, api):
        """PRD §3.5: "a `starts_at` and `ends_at` (both ISO-8601 UTC, with
        `ends_at` strictly after `starts_at` — anything else is rejected with
        `ERR_INVALID_TIME_RANGE`)"

        Design: Difficulty/resource_temporal_overlap/tasting_event_time_range_validation_half_open
        """
        set_clock()
        host = make_member(email="host15b@x.com", date_of_birth="1980-01-01")
        payload = create_tasting_event_payload(
            host["id"],
            starts_at="2026-05-10T12:00:00Z",
            ends_at="2026-05-10T10:00:00Z",
        )
        resp = api.create_tasting_event(payload, STAFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)


def _setup_full_event(api):
    """Published capacity-2 event with two booked seats. Returns event."""
    set_clock()
    member_a = make_member(email="a12@x.com")
    member_b = make_member(email="b12@x.com")
    event, _host, _sku = make_published_event(
        capacity=2, flight_price_cents=1000,
        starts_at="2026-05-10T10:00:00Z", ends_at="2026-05-10T12:00:00Z",
    )
    book_seat_for_member(event["id"], member_a["id"])
    book_seat_for_member(event["id"], member_b["id"])
    return get_event(event["id"])


class TestCapacityBoundary:
    def test_third_booking_at_capacity_rejected(self, api):
        """PRD §2.7: "11. Capacity — `seats_booked` below `capacity`,
        `active_subscription_count` below `max_active_subscriptions`
        (`ERR_CAPACITY_EXCEEDED`)."
        PRD §3.6: "the event's `seats_booked` must be strictly less than its
        `capacity` (violation surfaces as `ERR_CAPACITY_EXCEEDED`)".

        Design: Difficulty/boundary_precision_check/tasting_event_capacity_zero_remaining_seats
        """
        event = _setup_full_event(api)
        assert event["seats_booked"] == 2
        member_c = make_member(email="c12@x.com")
        payload = book_seat_payload(member_c["id"], event["version"])
        resp = api.book_seat(
            event["id"], payload, make_member_headers(member_c["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    def test_rejected_booking_preserves_seats_booked(self, api):
        """PRD §2.7: "11. Capacity — `seats_booked` below `capacity`,
        `active_subscription_count` below `max_active_subscriptions`
        (`ERR_CAPACITY_EXCEEDED`)."
        PRD §3.6: "Successful confirmation increments the event's
        `seats_booked` by one."

        Design: Difficulty/boundary_precision_check/tasting_event_capacity_zero_remaining_seats
        """
        event = _setup_full_event(api)
        member_c = make_member(email="c12@x.com")
        payload = book_seat_payload(member_c["id"], event["version"])
        resp = api.book_seat(
            event["id"], payload, make_member_headers(member_c["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
        after = get_event(event["id"])
        assert after["seats_booked"] == 2, (
            "a rejected booking must not change seats_booked"
        )
        assert after["version"] == event["version"]


def _setup_locked_event_with_reserved_seat(api):
    """Event published with one RESERVED seat, then clock advanced past the
    24-hour lock threshold (but before starts_at) so the event is LOCKED."""
    set_clock("2026-04-30T09:00:00Z")
    member = make_member(email="m14@x.com")
    event, _host, _sku = make_published_event(
        capacity=5, flight_price_cents=1000,
        starts_at="2026-05-02T10:00:00Z", ends_at="2026-05-02T12:00:00Z",
    )
    seat = book_seat_for_member(event["id"], member["id"])
    # Lock threshold is starts_at - 24h = 2026-05-01T10:00; 11:00 is past it.
    set_clock("2026-05-01T11:00:00Z")
    return event, seat, member


class TestBookingWindow:
    def test_confirm_on_locked_event_rejected(self, api):
        """PRD §3.6: "Three preconditions guard the transition: the event's
        status must be `PUBLISHED` or `RESCHEDULED` (not `LOCKED` or any later
        state — violation surfaces as `ERR_BOOKING_WINDOW_CLOSED`)".
        PRD §3.5: "The clock reaching `starts_at` minus 24 hours transitions
        the event automatically to `LOCKED`, after which no new seat
        reservations are accepted."

        Design: Difficulty/cross_entity_state_dependency/seat_confirm_depends_on_tasting_event_status
        """
        event, seat, member = _setup_locked_event_with_reserved_seat(api)
        assert get_event(event["id"])["status"] == "LOCKED"
        resp = api.confirm_seat(seat["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_WINDOW_CLOSED)

    def test_failed_confirm_leaves_seat_reserved(self, api):
        """PRD §3.6: "Confirmation of a `RESERVED` seat transitions it to
        `CONFIRMED`."
        PRD §3.6: "the event's status must be `PUBLISHED` or `RESCHEDULED`
        (not `LOCKED` or any later state — violation surfaces as
        `ERR_BOOKING_WINDOW_CLOSED`)".

        Design: Difficulty/cross_entity_state_dependency/seat_confirm_depends_on_tasting_event_status
        """
        event, seat, member = _setup_locked_event_with_reserved_seat(api)
        resp = api.confirm_seat(seat["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_WINDOW_CLOSED)
        seat_after = validate_success(api.get_seat(seat["id"], STAFF), 200)
        assert seat_after["status"] == "RESERVED"


def _setup_confirmed_seat(api):
    """Published event (flight price 2500, capacity 5) with one CONFIRMED
    seat. Returns (event, seat, member)."""
    set_clock()
    member = make_member(email="m18@x.com")
    event, _host, _sku = make_published_event(
        capacity=5, flight_price_cents=2500,
        starts_at="2026-05-10T10:00:00Z", ends_at="2026-05-10T12:00:00Z",
    )
    seat = book_seat_for_member(event["id"], member["id"])
    validate_success(
        api.confirm_seat(seat["id"], make_member_headers(member["id"])), 200
    )
    return get_event(event["id"]), seat, member


class TestSeatCancelCompensation:
    def test_cancel_restores_capacity_count(self, api):
        """PRD §3.6: "Cancellation is available from `RESERVED` or `CONFIRMED`
        provided the parent event is not `IN_SESSION` and not `COMPLETED`.
        Cancelling transitions the seat to `CANCELLED`, decrements the event's
        `seats_booked` by one, and — if the seat had been `CONFIRMED` —
        refunds the `price_paid_cents` to the member's
        `wallet_credit_cents`."

        Design: Difficulty/compensating_invariant/seat_cancel_conserves_wallet_and_capacity
        """
        event, seat, member = _setup_confirmed_seat(api)
        assert event["seats_booked"] == 1
        cancelled = validate_success(
            api.cancel_seat(seat["id"], make_member_headers(member["id"])), 200
        )
        assert_tasting_seat(cancelled)
        assert cancelled["status"] == "CANCELLED"
        assert get_event(event["id"])["seats_booked"] == 0

    def test_cancel_confirmed_seat_credits_wallet_exactly(self, api):
        """PRD §3.6: "Cancelling transitions the seat to `CANCELLED`,
        decrements the event's `seats_booked` by one, and — if the seat had
        been `CONFIRMED` — refunds the `price_paid_cents` to the member's
        `wallet_credit_cents`."
        PRD §3.6: "The seat begins in `RESERVED` status with a
        `price_paid_cents` locked in at booking time after applying the
        member's tier discount — the locked price is never re-priced even if
        the member's tier later changes — and a system-stamped `booked_at`."

        Design: Difficulty/compensating_invariant/seat_cancel_conserves_wallet_and_capacity
        """
        event, seat, member = _setup_confirmed_seat(api)
        wallet_before = get_member(member["id"])["wallet_credit_cents"]
        seat_fresh = validate_success(api.get_seat(seat["id"], STAFF), 200)
        price_paid = seat_fresh["price_paid_cents"]
        validate_success(
            api.cancel_seat(seat["id"], make_member_headers(member["id"])), 200
        )
        wallet_after = get_member(member["id"])["wallet_credit_cents"]
        assert wallet_after == wallet_before + price_paid, (
            "wallet must be credited by exactly price_paid_cents"
        )


class TestSeatBookingOcc:
    def test_stale_event_version_rejected_on_booking(self, api):
        """PRD §2.4: "Booking a seat on a tasting event requires the request
        to carry `expected_event_version`, equal to the `TastingEvent`'s
        `version` the client last observed. If another seat was booked or
        cancelled since that read, the booking is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_tasting_event_stale_version_on_seat_book
        """
        set_clock()
        m1 = make_member(email="moc1@x.com")
        m2 = make_member(email="moc2@x.com")
        event, _host, _sku = make_published_event(
            capacity=5, flight_price_cents=1000,
            starts_at="2026-05-10T10:00:00Z", ends_at="2026-05-10T12:00:00Z",
        )
        stale_version = get_event(event["id"])["version"]
        book_seat_for_member(event["id"], m1["id"])  # bumps event version
        payload = book_seat_payload(m2["id"], stale_version)
        resp = api.book_seat(event["id"], payload, make_member_headers(m2["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestEventTerminalLockdown:
    def test_completed_event_cannot_be_cancelled(self, api):
        """PRD §3.5: "A `ShopStaff` operator may cancel a `PUBLISHED` event,
        which transitions it to `CANCELLED`, cascade-cancels every
        `TastingSeat` in `RESERVED` or `CONFIRMED`, restores the reserved
        `InventoryLot.qty_remaining`, recomputes the affected SKUs'
        `on_hand_cached`, and bumps the event's `version`."
        PRD §3.5: "the clock reaching `ends_at` and every seat being in a
        terminal state (`ATTENDED`, `NO_SHOW`, `CANCELLED`, or `REFUNDED`)
        together trigger the transition to `COMPLETED`".
        PRD §2.7: "5. State — the target entity's current state permits the
        requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/tasting_event_terminal_completed_lockdown
        """
        set_clock("2026-04-30T09:00:00Z")
        event, _host, _sku = make_published_event(
            capacity=2, flight_price_cents=1000,
            starts_at="2026-05-02T10:00:00Z", ends_at="2026-05-02T12:00:00Z",
        )
        # No seats booked; every seat is vacuously terminal, so the event
        # completes once the clock passes ends_at.
        set_clock("2026-05-02T13:00:00Z")
        assert get_event(event["id"])["status"] == "COMPLETED"
        resp = api.cancel_tasting_event(event["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
