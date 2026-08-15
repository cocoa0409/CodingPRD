"""Assessment windows, test sites, seat booking, and proctor assignments."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_proctor_seat,
    create_assessment_window,
    create_district,
    create_enrolled_student,
    create_test_site,
    get_test_site,
    set_clock,
    setup_booked_proctor_seat,
    validate_error,
    validate_paginated,
    validate_success,
)

PROCTOR = TEST_USERS["proctor_coordinator_headers"]


class TestWindowListing:
    def test_assessment_window_list_filter_by_status(self, api):
        """PRD §3.7: "`CLOSED` is the terminal window state, and the window
        list accepts a `window_status` filter."
        PRD §3.7: "A new window is `SCHEDULED`."

        Design: Corner/endpoints/assessment_window_list_filter_by_status
        """
        set_clock("2026-08-01T00:00:00Z")
        create_assessment_window(assessment_name="W1", subject="ELA",
                                 window_start="2026-08-10T08:00:00Z",
                                 window_end="2026-08-12T17:00:00Z")
        create_assessment_window(assessment_name="W2", subject="MATH",
                                 window_start="2026-08-15T08:00:00Z",
                                 window_end="2026-08-17T17:00:00Z")
        data, meta = validate_paginated(
            api.list_assessment_windows(PROCTOR,
                                        params={"window_status": "SCHEDULED"}))
        assert meta["total_count"] == 2
        assert all(w["window_status"] == "SCHEDULED" for w in data)


class TestSeatCapacityBoundary:
    def _setup_full_single_seat_site(self):
        """Site capacity 1; S1 holds the only seat; S2 enrolled and waiting.
        The site dict returned is refreshed after S1's booking."""
        ctx = setup_booked_proctor_seat(district_state="FL", seat_capacity=1)
        _, s2 = create_enrolled_student(district=ctx["district"],
                                        legal_name="Olivia")
        return ctx, s2

    def test_booking_beyond_capacity_rejected(self, api):
        """PRD §3.7: "a seat must be free — `seats_booked` plus the new
        booking must not exceed `seat_capacity`, so the final seat may be
        taken but never one more, with overflow rejected as
        `ERR_NO_SEAT_AVAILABLE`"

        Design: Difficulty/boundary_precision_check/test_site_seat_capacity_at_exact_boundary
        """
        ctx, s2 = self._setup_full_single_seat_site()
        assert ctx["site"]["seats_booked"] == 1
        resp = book_proctor_seat(s2["id"], ctx["window"]["id"], ctx["site"])
        validate_error(resp, ApiErrorId.ERR_NO_SEAT_AVAILABLE)

    def test_rejected_overflow_keeps_seats_booked_unchanged(self, api):
        """PRD §3.7: "a seat must be free — `seats_booked` plus the new
        booking must not exceed `seat_capacity`, so the final seat may be
        taken but never one more, with overflow rejected as
        `ERR_NO_SEAT_AVAILABLE`"
        PRD §3.7: "A site's `seats_booked` is derived: the count of proctor
        assignments currently `BOOKED` at that site."

        Design: Difficulty/boundary_precision_check/test_site_seat_capacity_at_exact_boundary
        """
        ctx, s2 = self._setup_full_single_seat_site()
        validate_error(
            book_proctor_seat(s2["id"], ctx["window"]["id"], ctx["site"]),
            ApiErrorId.ERR_NO_SEAT_AVAILABLE,
        )
        site = get_test_site(ctx["site"]["id"])
        assert site["seats_booked"] == 1, (
            "the rejected booking must not consume a seat")


class TestSeatOccupancyPerWindow:
    def test_seat_occupied_for_window_blocks_second_booking(self, api):
        """PRD §3.7: "a seat must be free — `seats_booked` plus the new
        booking must not exceed `seat_capacity`, so the final seat may be
        taken but never one more, with overflow rejected as
        `ERR_NO_SEAT_AVAILABLE`"
        PRD §3.7: "A site's `seats_booked` is derived: the count of proctor
        assignments currently `BOOKED` at that site."

        Design: Difficulty/resource_temporal_overlap/proctor_seat_capacity_per_window
        """
        ctx = setup_booked_proctor_seat(district_state="WA", seat_capacity=1)
        _, s2 = create_enrolled_student(district=ctx["district"],
                                        legal_name="Sam")
        resp = book_proctor_seat(s2["id"], ctx["window"]["id"], ctx["site"])
        validate_error(resp, ApiErrorId.ERR_NO_SEAT_AVAILABLE)

    def test_cancelled_seat_becomes_available_again(self, api):
        """PRD §3.7: "Cancelling a booking releases the seat, dropping the
        site's `seats_booked` by one; student withdrawal cancels all of the
        student's outstanding bookings through the same release, per §3.3."
        PRD §3.7: "a seat must be free — `seats_booked` plus the new booking
        must not exceed `seat_capacity`, so the final seat may be taken but
        never one more, with overflow rejected as `ERR_NO_SEAT_AVAILABLE`"

        Design: Difficulty/resource_temporal_overlap/proctor_seat_capacity_per_window
        """
        ctx = setup_booked_proctor_seat(district_state="WA", seat_capacity=1)
        _, s2 = create_enrolled_student(district=ctx["district"],
                                        legal_name="Sam")
        validate_error(
            book_proctor_seat(s2["id"], ctx["window"]["id"], ctx["site"]),
            ApiErrorId.ERR_NO_SEAT_AVAILABLE,
        )
        validate_success(
            api.cancel_proctor_assignment(ctx["assignment"]["id"], PROCTOR), 200)
        site = get_test_site(ctx["site"]["id"])
        assert site["seats_booked"] == 0

        resp = book_proctor_seat(s2["id"], ctx["window"]["id"], site)
        assignment = validate_success(resp, 201)
        assert assignment["assignment_status"] == "BOOKED"
        assert get_test_site(site["id"])["seats_booked"] == 1


class TestBookingCancelConservation:
    def _setup_single_booking(self):
        return setup_booked_proctor_seat(district_state="OR", seat_capacity=3)

    def test_booking_raises_seats_booked(self, api):
        """PRD §3.7: "A successful booking lands in `BOOKED` status with
        `booked_at` stamped from the clock, raises the site's `seats_booked`
        by one, and increments the site's `version`."

        Design: Difficulty/compensating_invariant/proctor_seat_booking_and_cancel_conserve_occupancy
        """
        ctx = self._setup_single_booking()
        assert ctx["assignment"]["assignment_status"] == "BOOKED"
        assert ctx["site"]["seats_booked"] == 1

    def test_cancel_releases_seat_and_conserves_occupancy(self, api):
        """PRD §3.7: "Cancelling a booking releases the seat, dropping the
        site's `seats_booked` by one; student withdrawal cancels all of the
        student's outstanding bookings through the same release, per §3.3."

        Design: Difficulty/compensating_invariant/proctor_seat_booking_and_cancel_conserve_occupancy
        """
        ctx = self._setup_single_booking()
        cancelled = validate_success(
            api.cancel_proctor_assignment(ctx["assignment"]["id"], PROCTOR), 200)
        assert cancelled["assignment_status"] == "CANCELLED"
        site = get_test_site(ctx["site"]["id"])
        assert site["seats_booked"] == 0, (
            "book-then-cancel leaves occupancy at its pre-booking value")


class TestCompletionGating:
    def _setup_booking_in_scheduled_window(self):
        """Booking made while the window is still SCHEDULED (booking ahead of
        a window's opening is expressly allowed)."""
        return setup_booked_proctor_seat(
            district_state="TX", seat_capacity=5,
            window_start="2026-08-20T08:00:00Z",
            window_end="2026-08-22T17:00:00Z")

    def test_mark_completed_before_window_opens_rejected(self, api):
        """PRD §3.7: "A `ProctorCoordinator` marks a booking completed —
        `completed_at`, null since booking, is stamped from the clock — only
        while its window is `OPEN`; completion attempts against a window in
        any other state are rejected with `ERR_ASSESSMENT_WINDOW_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/proctor_assignment_completion_gated_on_window_open
        """
        ctx = self._setup_booking_in_scheduled_window()
        resp = api.mark_proctor_completed(ctx["assignment"]["id"], PROCTOR)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_WINDOW_NOT_OPEN)

    def test_rejected_completion_keeps_booking_booked(self, api):
        """PRD §3.7: "A `ProctorCoordinator` marks a booking completed —
        `completed_at`, null since booking, is stamped from the clock — only
        while its window is `OPEN`; completion attempts against a window in
        any other state are rejected with `ERR_ASSESSMENT_WINDOW_NOT_OPEN`."
        PRD §3.7: "A successful booking lands in `BOOKED` status with
        `booked_at` stamped from the clock, raises the site's `seats_booked`
        by one, and increments the site's `version`."

        Design: Difficulty/cross_entity_state_dependency/proctor_assignment_completion_gated_on_window_open
        """
        ctx = self._setup_booking_in_scheduled_window()
        validate_error(
            api.mark_proctor_completed(ctx["assignment"]["id"], PROCTOR),
            ApiErrorId.ERR_ASSESSMENT_WINDOW_NOT_OPEN,
        )
        assignment = validate_success(
            api.get_proctor_assignment(ctx["assignment"]["id"], PROCTOR))
        assert assignment["assignment_status"] == "BOOKED"
        assert assignment["completed_at"] is None


class TestSiteVersionConcurrency:
    def test_stale_site_version_on_booking_rejected(self, api):
        """PRD §3.7: "Booking a seat is a `ProctorCoordinator` action carrying
        the `student_id`, the `assessment_window_id`, the `test_site_id`, and
        — as the system's second optimistic-concurrency guard (§2.9) —
        `expected_test_site_version`, which must match the site's current
        `version`. A site whose version has advanced since the client last
        read it rejects the booking with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_site_version_on_proctor_booking_rejected
        """
        district = create_district(district_code="D-132", state_code="TX",
                                   funding_rate_cents=400, enrollment_cap=50)
        site = create_test_site(site_name="S1", state_code="TX",
                                seat_capacity=5)
        stale_version = site["version"]
        window = create_assessment_window(assessment_name="W1", subject="MATH",
                                          window_start="2026-08-20T08:00:00Z",
                                          window_end="2026-08-22T17:00:00Z")
        _, s1 = create_enrolled_student(district=district, legal_name="StA")
        resp = book_proctor_seat(s1["id"], window["id"], site)
        validate_success(resp, 201)
        site = get_test_site(site["id"])
        assert site["version"] != stale_version, (
            "the first booking must advance the site version")

        _, s2 = create_enrolled_student(district=district, legal_name="StB")
        resp = book_proctor_seat(s2["id"], window["id"],
                                 (site["id"], stale_version))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestTerminalProctorAssignment:
    def test_mark_completed_on_cancelled_assignment_rejected(self, api):
        """PRD §3.7: "From `BOOKED` there are exactly three exits, and all
        three landing states — `COMPLETED`, `NO_SHOW`, and `CANCELLED` — are
        terminal."
        PRD §2.7: "The target entity must be in a state that admits the
        requested transition. This stage also covers the enrollment-dependent
        creation rules: scheduling a special-education session, issuing a
        stipend, creating a teacher assignment, and booking a proctored seat
        each require the referenced student to be `ENROLLED`. Violations yield
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/errors/err_invalid_state_on_terminal_proctor_assignment
        """
        ctx = setup_booked_proctor_seat(district_state="WA", seat_capacity=5)
        validate_success(
            api.cancel_proctor_assignment(ctx["assignment"]["id"], PROCTOR), 200)
        # Move the clock inside the window so only the assignment's terminal
        # state can fail the request.
        set_clock("2026-08-11T10:00:00Z")
        window = validate_success(
            api.get_assessment_window(ctx["window"]["id"], PROCTOR))
        assert window["window_status"] == "OPEN"
        resp = api.mark_proctor_completed(ctx["assignment"]["id"], PROCTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
