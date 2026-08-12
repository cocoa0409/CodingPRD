"""Booking scheduling: capacity boundaries, buffers, window adjacency, state guards,
AUTO matcher."""
from test_helpers import (
    COORD,
    ApiErrorId,
    add_window,
    assert_booking,
    confirm_booking,
    create_active_caregiver,
    create_active_provider,
    create_booking_payload,
    create_explicit_booking,
    create_program,
    api_client,
    issue_voucher,
    make_caregiver_headers,
    make_provider_headers,
    run_ops_run,
    set_clock,
    setup_service_world,
    book_and_confirm,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWindowCapacityBoundary:
    def test_overlap_at_capacity_rejected(self, api):
        """PRD §3.6: "The named window must contain the booking's interval, and adding
        the new booking must keep the window's overlap count of non-cancelled bookings
        strictly below the window's `capacity` — a violation is rejected with
        `ERR_WINDOW_CAPACITY_FULL`."
        PRD §2.9: "(14) window capacity (`ERR_WINDOW_CAPACITY_FULL`)" precedes
        "(15) caregiver double-booking buffer (`ERR_CAREGIVER_DOUBLE_BOOKED`)".

        Design: Difficulty/boundary_precision_check/booking_overlap_count_at_capacity_boundary
        """
        ctx = setup_service_world(window_start="2026-05-06T08:00:00Z",
                                  window_end="2026-05-06T14:00:00Z",
                                  window_capacity=1)
        book_and_confirm(ctx, "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
        # Second booking overlaps: overlap count 1 == capacity is NOT strictly below.
        res = api.create_booking(
            create_booking_payload(ctx["voucher"]["id"], ctx["caregiver"]["id"],
                                   "2026-05-06T11:00:00Z", "2026-05-06T12:30:00Z",
                                   match_mode="EXPLICIT", provider_id=ctx["provider"]["id"],
                                   window_id=ctx["window"]["id"]),
            make_caregiver_headers(ctx["caregiver"]["id"]))
        validate_error(res, ApiErrorId.ERR_WINDOW_CAPACITY_FULL, expected_status=409)

    def test_zero_overlap_booking_succeeds(self, api):
        """PRD §3.6: "adding the new booking must keep the window's overlap count of
        non-cancelled bookings strictly below the window's `capacity`"
        PRD §3.6: "the new booking's interval padded by thirty minutes on each side
        must not intersect any existing non-cancelled booking interval of the same
        caregiver."
        PRD §3.6: "A successful create lands the booking in `PENDING_CONFIRMATION`"

        Design: Difficulty/boundary_precision_check/booking_overlap_count_at_capacity_boundary
        """
        ctx = setup_service_world(window_start="2026-05-06T08:00:00Z",
                                  window_end="2026-05-06T14:00:00Z",
                                  window_capacity=1)
        book_and_confirm(ctx, "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
        # Starts exactly 30 minutes after the first ends: zero overlap, buffer met.
        booking = validate_success(
            api.create_booking(
                create_booking_payload(ctx["voucher"]["id"], ctx["caregiver"]["id"],
                                       "2026-05-06T12:30:00Z", "2026-05-06T13:30:00Z",
                                       match_mode="EXPLICIT",
                                       provider_id=ctx["provider"]["id"],
                                       window_id=ctx["window"]["id"]),
                make_caregiver_headers(ctx["caregiver"]["id"])),
            201)
        assert_booking(booking)
        assert booking["status"] == "PENDING_CONFIRMATION"
        assert booking["committed_minutes"] == 60


class TestCaregiverBufferThirtyMinutes:
    def _world_with_first_booking(self, api):
        ctx = setup_service_world(window_start="2026-05-06T08:00:00Z",
                                  window_end="2026-05-06T20:00:00Z",
                                  window_capacity=3)
        create_explicit_booking(ctx["voucher"]["id"], ctx["caregiver"]["id"],
                                ctx["provider"]["id"], ctx["window"]["id"],
                                "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
        return ctx

    def test_thirty_minute_gap_booking_allowed(self, api):
        """PRD §3.6: "the new booking's interval padded by thirty minutes on each side
        must not intersect any existing non-cancelled booking interval of the same
        caregiver. A violation is rejected with `ERR_CAREGIVER_DOUBLE_BOOKED` (HTTP 409)."
        A 12:30 start pads to [12:00, 15:00); the existing [10:00, 12:00) only touches.

        Design: Difficulty/resource_temporal_overlap/caregiver_booking_buffer_thirty_minutes
        """
        ctx = self._world_with_first_booking(api)
        booking = validate_success(
            api.create_booking(
                create_booking_payload(ctx["voucher"]["id"], ctx["caregiver"]["id"],
                                       "2026-05-06T12:30:00Z", "2026-05-06T14:30:00Z",
                                       match_mode="EXPLICIT",
                                       provider_id=ctx["provider"]["id"],
                                       window_id=ctx["window"]["id"]),
                make_caregiver_headers(ctx["caregiver"]["id"])),
            201)
        assert booking["status"] == "PENDING_CONFIRMATION"

    def test_fifteen_minute_gap_rejected(self, api):
        """PRD §3.6: "the new booking's interval padded by thirty minutes on each side
        must not intersect any existing non-cancelled booking interval of the same
        caregiver. A violation is rejected with `ERR_CAREGIVER_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/caregiver_booking_buffer_thirty_minutes
        """
        ctx = self._world_with_first_booking(api)
        # 12:15 start pads to [11:45, ...), intersecting the existing [10:00, 12:00).
        res = api.create_booking(
            create_booking_payload(ctx["voucher"]["id"], ctx["caregiver"]["id"],
                                   "2026-05-06T12:15:00Z", "2026-05-06T14:00:00Z",
                                   match_mode="EXPLICIT",
                                   provider_id=ctx["provider"]["id"],
                                   window_id=ctx["window"]["id"]),
            make_caregiver_headers(ctx["caregiver"]["id"]))
        validate_error(res, ApiErrorId.ERR_CAREGIVER_DOUBLE_BOOKED, expected_status=409)


class TestWindowHalfOpenAdjacency:
    def test_adjacent_windows_allowed(self, api):
        """PRD §3.5: "The window's interval is half-open — it covers the period from
        `start_at` up to but not including `end_at`. Within a single provider, windows
        must not overlap; touching endpoints are allowed."

        Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
        """
        create_program()
        provider = create_active_provider()
        add_window(provider["id"], "2026-05-04T08:00:00Z", "2026-05-04T12:00:00Z", 1)
        adjacent = validate_success(
            api.create_availability_window(
                provider["id"],
                {"start_at": "2026-05-04T12:00:00Z", "end_at": "2026-05-04T16:00:00Z",
                 "capacity": 1},
                make_provider_headers(provider["id"])),
            201)
        assert adjacent["status"] == "OPEN"

    def test_overlapping_window_rejected(self, api):
        """PRD §3.5: "Within a single provider, windows must not overlap; touching
        endpoints are allowed. An overlap is rejected with `ERR_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
        """
        create_program()
        provider = create_active_provider()
        add_window(provider["id"], "2026-05-04T08:00:00Z", "2026-05-04T12:00:00Z", 1)
        add_window(provider["id"], "2026-05-04T12:00:00Z", "2026-05-04T16:00:00Z", 1)
        res = api.create_availability_window(
            provider["id"],
            {"start_at": "2026-05-04T11:00:00Z", "end_at": "2026-05-04T13:00:00Z",
             "capacity": 1},
            make_provider_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_WINDOW_OVERLAP, expected_status=409)


class TestCheckinUnconfirmedGuard:
    def _unconfirmed_booking(self, api):
        ctx = setup_service_world(window_start="2026-05-06T08:00:00Z",
                                  window_end="2026-05-06T20:00:00Z",
                                  window_capacity=1, voucher_hours=10)
        booking = create_explicit_booking(ctx["voucher"]["id"], ctx["caregiver"]["id"],
                                          ctx["provider"]["id"], ctx["window"]["id"],
                                          "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
        set_clock("2026-05-06T10:00:00Z")  # inside [start-15m, end]
        return ctx, booking

    def test_checkin_unconfirmed_rejected(self, api):
        """PRD §3.7: "It is performed by the owning provider on a booking in
        `CONFIRMED` status — attempting it on any other status is rejected with
        `ERR_BOOKING_NOT_CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/checkin_rejected_when_booking_unconfirmed
        """
        ctx, booking = self._unconfirmed_booking(api)
        res = api.check_in_booking(booking["id"], {"check_in_location": "37.77,-122.41"},
                                   make_provider_headers(ctx["provider"]["id"]))
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_CONFIRMED, expected_status=409)
        after = validate_success(api.get_booking(booking["id"], COORD), 200)
        assert after["status"] == "PENDING_CONFIRMATION"

    def test_checkin_unconfirmed_leaves_no_visit(self, api):
        """PRD §3.7: "A successful check-in creates a `VisitRecord` in `OPEN` status"
        — a rejected check-in creates none.

        Design: Difficulty/cross_entity_state_dependency/checkin_rejected_when_booking_unconfirmed
        """
        ctx, booking = self._unconfirmed_booking(api)
        res = api.check_in_booking(booking["id"], {"check_in_location": "37.77,-122.41"},
                                   make_provider_headers(ctx["provider"]["id"]))
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_CONFIRMED, expected_status=409)
        visits = validate_success(api.list_booking_visit_records(booking["id"], COORD), 200)
        assert visits == []


class TestExpiredVoucherBookingGuard:
    def _expired_voucher_world(self, api):
        ctx = setup_service_world(window_start="2026-07-01T00:00:00Z",
                                  window_end="2026-08-15T00:00:00Z",
                                  window_capacity=1, voucher_hours=10)
        # Voucher issued at the 2026-05-01 default clock expires 2026-07-30T00:00:00Z.
        set_clock("2026-07-30T00:00:01Z")
        run_ops_run(ctx["program"]["id"], "STANDARD")
        return ctx

    def test_booking_with_expired_voucher_rejected(self, api):
        """PRD §3.13: "Vouchers in `ISSUED` whose `expires_at` is at or before now
        transition to `EXPIRED`"
        PRD §3.6: "The voucher must be in `ISSUED` status with sufficient unconsumed
        hours: the existing `committed_hours` plus the new booking's duration must not
        exceed `authorized_hours` minus `consumed_hours` minus `released_hours` minus
        `forfeited_hours`."
        PRD §3.6: "A violation is rejected with `ERR_VOUCHER_NOT_ISSUABLE`."

        Design: Difficulty/cross_entity_state_dependency/booking_rejected_when_voucher_expired
        """
        ctx = self._expired_voucher_world(api)
        voucher = validate_success(api.get_voucher(ctx["voucher"]["id"], COORD), 200)
        assert voucher["status"] == "EXPIRED"
        # Booking interval precedes the expiry timestamp; the state rule still fires.
        res = api.create_booking(
            create_booking_payload(ctx["voucher"]["id"], ctx["caregiver"]["id"],
                                   "2026-07-15T10:00:00Z", "2026-07-15T12:00:00Z",
                                   match_mode="EXPLICIT",
                                   provider_id=ctx["provider"]["id"],
                                   window_id=ctx["window"]["id"]),
            make_caregiver_headers(ctx["caregiver"]["id"]))
        validate_error(res, ApiErrorId.ERR_VOUCHER_NOT_ISSUABLE, expected_status=422)

    def test_expired_voucher_has_no_bookings(self, api):
        """PRD §3.6: "The voucher must be in `ISSUED` status with sufficient unconsumed
        hours: the existing `committed_hours` plus the new booking's duration must not
        exceed `authorized_hours` minus `consumed_hours` minus `released_hours` minus
        `forfeited_hours`."
        PRD §3.6: "A violation is rejected with `ERR_VOUCHER_NOT_ISSUABLE`." — the
        rejected create leaves no booking rows for the voucher.

        Design: Difficulty/cross_entity_state_dependency/booking_rejected_when_voucher_expired
        """
        ctx = self._expired_voucher_world(api)
        res = api.create_booking(
            create_booking_payload(ctx["voucher"]["id"], ctx["caregiver"]["id"],
                                   "2026-07-15T10:00:00Z", "2026-07-15T12:00:00Z",
                                   match_mode="EXPLICIT",
                                   provider_id=ctx["provider"]["id"],
                                   window_id=ctx["window"]["id"]),
            make_caregiver_headers(ctx["caregiver"]["id"]))
        validate_error(res, ApiErrorId.ERR_VOUCHER_NOT_ISSUABLE, expected_status=422)
        bookings, meta = validate_paginated(
            api.list_bookings(COORD, params={"voucher_id": ctx["voucher"]["id"]}))
        assert bookings == []
        assert meta["total_count"] == 0


def test_auto_match_empty_pool_rejected(api):
    """PRD §3.6: "In `AUTO` match mode the request omits `provider_id` and `window_id`,
    and the system runs the auto-match selector."
    PRD §3.6: "An empty pool is rejected with `ERR_NO_PROVIDER_AVAILABLE`."

    Design: Corner/errors/auto_match_empty_pool_rejected
    """
    ctx = create_active_caregiver()
    voucher = issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], 10)
    res = api.create_booking(
        create_booking_payload(voucher["id"], ctx["caregiver"]["id"],
                               "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z",
                               match_mode="AUTO"),
        make_caregiver_headers(ctx["caregiver"]["id"]))
    validate_error(res, ApiErrorId.ERR_NO_PROVIDER_AVAILABLE, expected_status=422)


def test_auto_match_tiebreak_created_at(api):
    """PRD §3.6: "The pool is ranked by `quality_score_weighted` descending with nulls
    last, with ties broken by provider `created_at` ascending (never by `id`)."
    PRD §3.6: "A booking created this way has `auto_matched` true."
    PRD §3.6: "The selected window is the chosen provider's eligible window with the
    earliest `start_at`, with ties broken by window `created_at` ascending."

    Design: Corner/complexity_layers/selector_tiebreak_created_at_asc
    """
    program = create_program()
    ctx = create_active_caregiver(program=program)
    voucher = issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], 10)
    prov1 = create_active_provider(name="Prov First")
    set_clock("2026-05-01T00:01:00Z")
    prov2 = create_active_provider(name="Prov Second")
    win1 = add_window(prov1["id"], "2026-05-06T08:00:00Z", "2026-05-06T20:00:00Z", 1)
    add_window(prov2["id"], "2026-05-06T08:00:00Z", "2026-05-06T20:00:00Z", 1)

    booking = validate_success(
        api.create_booking(
            create_booking_payload(voucher["id"], ctx["caregiver"]["id"],
                                   "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z",
                                   match_mode="AUTO"),
            make_caregiver_headers(ctx["caregiver"]["id"])),
        201)
    # Both providers have null quality scores; the earlier-created provider wins.
    assert booking["provider_id"] == prov1["id"]
    assert booking["window_id"] == win1["id"]
    assert booking["auto_matched"] is True
    assert booking["status"] == "PENDING_CONFIRMATION"


class TestProviderSafetyBeatsWindowCapacity:
    def _suspended_provider_world(self, api):
        """Cap-1 window already holding a CONFIRMED booking; provider then SUSPENDED
        (existing bookings are not cascaded)."""
        ctx = setup_service_world(window_start="2026-05-06T08:00:00Z",
                                  window_end="2026-05-06T20:00:00Z",
                                  window_capacity=1, voucher_hours=10)
        book_and_confirm(ctx, "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
        return ctx

    def test_suspended_provider_error_beats_capacity_error(self, api):
        """PRD §2.9: "(9) provider credential requirements for window, booking,
        confirm, and check-in (`ERR_PROVIDER_NOT_ACTIVE`)" precedes "(14) window
        capacity (`ERR_WINDOW_CAPACITY_FULL`)".
        PRD §2.9: "A request that fails several of these surfaces the error whose rule
        sits earliest in this list."
        PRD §3.5: "suspension only gates new bookings and new windows; existing
        bookings and existing windows are not cascaded".

        Design: Difficulty/priority_pair_validation_conflict/provider_safety_beats_window_capacity
        """
        ctx = self._suspended_provider_world(api)
        validate_success(
            api.transition_provider(
                ctx["provider"]["id"],
                {"target_status": "SUSPENDED", "reason": "audit hold"}, COORD),
            200)
        voucher2 = issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], 10)
        # Violates provider-safety (9) AND capacity (14) AND caregiver buffer (15).
        res = api.create_booking(
            create_booking_payload(voucher2["id"], ctx["caregiver"]["id"],
                                   "2026-05-06T11:00:00Z", "2026-05-06T13:00:00Z",
                                   match_mode="EXPLICIT",
                                   provider_id=ctx["provider"]["id"],
                                   window_id=ctx["window"]["id"]),
            make_caregiver_headers(ctx["caregiver"]["id"]))
        validate_error(res, ApiErrorId.ERR_PROVIDER_NOT_ACTIVE, expected_status=422)

    def test_capacity_error_when_provider_active(self, api):
        """PRD §3.6: "adding the new booking must keep the window's overlap count of
        non-cancelled bookings strictly below the window's `capacity` — a violation is
        rejected with `ERR_WINDOW_CAPACITY_FULL`."

        Design: Difficulty/priority_pair_validation_conflict/provider_safety_beats_window_capacity
        """
        ctx = self._suspended_provider_world(api)
        voucher2 = issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], 10)
        res = api.create_booking(
            create_booking_payload(voucher2["id"], ctx["caregiver"]["id"],
                                   "2026-05-06T11:00:00Z", "2026-05-06T13:00:00Z",
                                   match_mode="EXPLICIT",
                                   provider_id=ctx["provider"]["id"],
                                   window_id=ctx["window"]["id"]),
            make_caregiver_headers(ctx["caregiver"]["id"]))
        validate_error(res, ApiErrorId.ERR_WINDOW_CAPACITY_FULL, expected_status=409)
