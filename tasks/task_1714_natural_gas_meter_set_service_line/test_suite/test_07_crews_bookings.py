"""Crew booking confirmation: buffered overlap, daily capacity, and temporal order."""
from test_helpers import (
    ApiErrorId,
    confirm_booking,
    create_booking,
    create_crew,
    refresh_application,
    refresh_booking,
    set_clock,
    setup_ciac_pending_app,
    setup_draft_app,
    validate_error,
    validate_success,
)


class TestCrewCapacityBoundary:
    def test_exact_capacity_fit_confirms(self, api, supervisor_headers):
        """PRD §3.5: "Second, the capacity rule: the sum of the durations of that crew's `CONFIRMED` bookings on that date, plus the new booking's duration, must not exceed the crew's `daily_capacity_minutes`; a total exactly equal to capacity is allowed, anything larger is rejected with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/crew_capacity_exact_fit_then_overflow
        """
        ctx = setup_draft_app()
        crew = create_crew(specialty="GENERAL", capacity=480)
        booking = create_booking(ctx["app"]["id"], crew["id"], start=540, end=1020)
        assert booking["end_minute"] - booking["start_minute"] == 480

        resp = api.confirm_booking(booking["id"], supervisor_headers)
        confirmed = validate_success(resp)
        assert confirmed["status"] == "CONFIRMED", (
            "a booking whose duration equals daily_capacity_minutes confirms (<= semantics)"
        )

    def test_one_minute_over_capacity_rejected(self, api, supervisor_headers):
        """PRD §3.5: "Second, the capacity rule: the sum of the durations of that crew's `CONFIRMED` bookings on that date, plus the new booking's duration, must not exceed the crew's `daily_capacity_minutes`; a total exactly equal to capacity is allowed, anything larger is rejected with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/crew_capacity_exact_fit_then_overflow
        """
        ctx = setup_draft_app()
        crew = create_crew(specialty="GENERAL", capacity=480)
        first = create_booking(ctx["app"]["id"], crew["id"], start=540, end=1020)
        confirm_booking(first["id"])
        # 1050 - 1020 = 30 minutes of gap: the buffer rule is satisfied, so only
        # capacity can reject this booking (480 + 30 = 510 > 480).
        second = create_booking(ctx["app"]["id"], crew["id"], start=1050, end=1080)

        resp = api.confirm_booking(second["id"], supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED, expected_status=422)

        assert refresh_booking(first["id"])["status"] == "CONFIRMED"
        assert refresh_booking(second["id"])["status"] == "REQUESTED"


class TestCrewWindowBuffer:
    def test_adjacent_booking_within_buffer_conflicts(self, api, supervisor_headers):
        """PRD §3.5: "First, the buffered-overlap rule: crew windows behave as closed intervals padded by a thirty-minute turnaround buffer, so the new booking conflicts with any already-`CONFIRMED` booking of the same crew on the same date whenever the new start falls before the existing window's end plus thirty minutes and the new end plus thirty minutes falls after the existing window's start — adjacency closer than thirty minutes is a conflict (`ERR_CREW_WINDOW_CONFLICT`, HTTP 409), while a gap of exactly thirty minutes or more is allowed."

        Design: Difficulty/resource_temporal_overlap/crew_windows_buffered_thirty_minutes
        """
        ctx = setup_draft_app()
        crew = create_crew(specialty="GENERAL", capacity=480)
        first = create_booking(ctx["app"]["id"], crew["id"], start=540, end=660)
        confirm_booking(first["id"])
        # Starts exactly when the confirmed window ends: 660 < 660 + 30 conflicts.
        adjacent = create_booking(ctx["app"]["id"], crew["id"], start=660, end=780)

        resp = api.confirm_booking(adjacent["id"], supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT, expected_status=409)
        assert refresh_booking(adjacent["id"])["status"] == "REQUESTED"

    def test_exact_thirty_minute_gap_confirms(self, api, supervisor_headers):
        """PRD §3.5: "adjacency closer than thirty minutes is a conflict (`ERR_CREW_WINDOW_CONFLICT`, HTTP 409), while a gap of exactly thirty minutes or more is allowed."

        Design: Difficulty/resource_temporal_overlap/crew_windows_buffered_thirty_minutes
        """
        ctx = setup_draft_app()
        crew = create_crew(specialty="GENERAL", capacity=480)
        first = create_booking(ctx["app"]["id"], crew["id"], start=540, end=660)
        confirm_booking(first["id"])
        # 690 = 660 + 30: the buffer is exactly satisfied; 120 + 90 <= 480 capacity.
        spaced = create_booking(ctx["app"]["id"], crew["id"], start=690, end=780)

        resp = api.confirm_booking(spaced["id"], supervisor_headers)
        confirmed = validate_success(resp)
        assert confirmed["status"] == "CONFIRMED"


class TestTemporalBeforeOverlap:
    def test_past_work_date_beats_window_conflict(self, api, supervisor_headers):
        """PRD §2.6: "9. **Temporal rules** — quote freshness and not-in-the-past date checks (`ERR_QUOTE_EXPIRED`, `ERR_DATE_IN_PAST`), guarding quote acceptance, crew-booking confirmation, inspection creation, inspection rescheduling, commitment revision proposals, and permit decision recording."
        PRD §3.5: "Confirming requires the `work_date` to be today or later (`ERR_DATE_IN_PAST`), the crew to be active (`ERR_INVALID_STATE`), and the window to fit the crew's day twice over."

        Design: Difficulty/priority_pair_validation_conflict/past_date_beats_crew_overlap
        """
        ctx = setup_draft_app()
        crew = create_crew(specialty="GENERAL", capacity=480)
        first = create_booking(ctx["app"]["id"], crew["id"], start=540, end=660)
        confirm_booking(first["id"])
        # 630 < 660 + 30: this window buffered-overlaps the confirmed one.
        overlapping = create_booking(ctx["app"]["id"], crew["id"], start=630, end=720)

        set_clock("2026-08-15T09:00:00Z")  # work_date 2026-08-10 is now in the past
        resp = api.confirm_booking(overlapping["id"], supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_DATE_IN_PAST, expected_status=422)

    def test_temporal_rejection_leaves_bookings_untouched(self, api, supervisor_headers):
        """PRD §3.5: "Confirming requires the `work_date` to be today or later (`ERR_DATE_IN_PAST`), the crew to be active (`ERR_INVALID_STATE`), and the window to fit the crew's day twice over."

        Design: Difficulty/priority_pair_validation_conflict/past_date_beats_crew_overlap
        """
        ctx = setup_draft_app()
        crew = create_crew(specialty="GENERAL", capacity=480)
        first = create_booking(ctx["app"]["id"], crew["id"], start=540, end=660)
        confirm_booking(first["id"])
        overlapping = create_booking(ctx["app"]["id"], crew["id"], start=630, end=720)

        set_clock("2026-08-15T09:00:00Z")
        resp = api.confirm_booking(overlapping["id"], supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_DATE_IN_PAST, expected_status=422)

        assert refresh_booking(overlapping["id"])["status"] == "REQUESTED"
        assert refresh_booking(first["id"])["status"] == "CONFIRMED"


class TestCapacityConservation:
    def test_overflow_rejected_while_day_is_full(self, api, supervisor_headers):
        """PRD §3.5: "Second, the capacity rule: the sum of the durations of that crew's `CONFIRMED` bookings on that date, plus the new booking's duration, must not exceed the crew's `daily_capacity_minutes`; a total exactly equal to capacity is allowed, anything larger is rejected with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/compensating_invariant/crew_confirm_cancel_conserves_day_capacity
        """
        ctx = setup_draft_app()
        crew = create_crew(specialty="GENERAL", capacity=480)
        a = create_booking(ctx["app"]["id"], crew["id"], start=540, end=780)   # 240
        confirm_booking(a["id"])
        b = create_booking(ctx["app"]["id"], crew["id"], start=810, end=930)   # 120
        confirm_booking(b["id"])
        c = create_booking(ctx["app"]["id"], crew["id"], start=990, end=1120)  # 130

        resp = api.confirm_booking(c["id"], supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED, expected_status=422)
        # 240 + 120 + 130 = 490 > 480 while the buffer is satisfied throughout.
        assert refresh_booking(c["id"])["status"] == "REQUESTED"

    def test_cancel_releases_minutes_for_the_same_window(self, api, supervisor_headers):
        """PRD §3.5: "A confirmed booking can be rescheduled — a new `work_date`, `start_minute`, and `end_minute` are stored and the booking drops back to `REQUESTED`, requiring fresh confirmation — or cancelled, and cancelling a confirmed booking releases its minutes back into the crew-day capacity."

        Design: Difficulty/compensating_invariant/crew_confirm_cancel_conserves_day_capacity
        """
        ctx = setup_draft_app()
        crew = create_crew(specialty="GENERAL", capacity=480)
        a = create_booking(ctx["app"]["id"], crew["id"], start=540, end=780)   # 240
        confirm_booking(a["id"])
        b = create_booking(ctx["app"]["id"], crew["id"], start=810, end=930)   # 120
        confirm_booking(b["id"])
        c = create_booking(ctx["app"]["id"], crew["id"], start=990, end=1120)  # 130
        resp = api.confirm_booking(c["id"], supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED, expected_status=422)

        resp = api.cancel_booking(b["id"], supervisor_headers)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"

        # After the cancel the crew-day holds exactly A's 240 minutes again, so
        # the identical 130-minute window now fits: 240 + 130 = 370 <= 480.
        resp = api.confirm_booking(c["id"], supervisor_headers)
        confirmed = validate_success(resp)
        assert confirmed["status"] == "CONFIRMED"


class TestScheduleConstructionBookingGate:
    def test_schedule_without_confirmed_booking_rejected(self, api, supervisor_headers):
        """PRD §3.5: "at least one of the application's bookings must be `CONFIRMED` (`ERR_NO_CONFIRMED_BOOKING`, HTTP 422)"

        Design: Corner/validations/schedule_without_confirmed_booking_rejected
        """
        # Zero-CIAC path leaves the application APPROVED_FOR_CONSTRUCTION with the
        # invoice PAID; no permits are needed because the design has no crossings.
        ctx = setup_ciac_pending_app(design_footage_ft=100, crossings=[])
        assert ctx["app"]["status"] == "APPROVED_FOR_CONSTRUCTION"

        crew = create_crew(specialty="SERVICE_LINE")
        create_booking(ctx["app"]["id"], crew["id"], scope="SERVICE_INSTALL")  # REQUESTED

        resp = api.schedule_construction(ctx["app"]["id"], supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_NO_CONFIRMED_BOOKING, expected_status=422)
        assert refresh_application(ctx["app"]["id"])["status"] == "APPROVED_FOR_CONSTRUCTION"
