"""Validation-priority conflicts, numeric/empty-set boundaries, cross-entity
state dependencies, resource temporal overlaps, and conserved-quantity
invariants.

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_shop_admin_headers, make_instructor_headers,
    create_diver, create_instructor, create_course, create_boat, create_rental,
    create_enrollment, create_session, create_dive_trip, sign_waiver,
    create_waiver_cleared_diver, set_clock, book_seat,
    setup_trip_with_certified_diver,
)
from test_helpers import factories as f
from test_helpers import ApiErrorId

ADMIN = make_shop_admin_headers()


class TestValidationPriorityConflicts:
    def test_state_beats_capacity_on_session_booking(self, api):
        """PRD 2.9: "sixth, state — the target resource is in a state from which
        the requested transition is legal (`ERR_INVALID_STATE`)" ... evaluated
        before "Domain-specific business rules — the medical/waiver gate, the
        certification prerequisite, instructor and boat scheduling conflicts, seat
        capacity, and duplicate-booking checks — are evaluated after these seven
        foundational layers."
        PRD 3.5: "The enrollment must be `ACTIVE` and the session `SCHEDULED`, or
        the request is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_session_booking
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor()
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
        )
        cancelled = validate_success(api.cancel_session(session["id"], ADMIN))
        diver = create_waiver_cleared_diver(full_name="Bo Booker")
        enr = create_enrollment(diver["id"], course["id"])
        resp = api.create_session_booking(
            f.create_session_booking_payload(
                session["id"], enr["id"], cancelled["version"]
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


class TestBoundaryPrecision:
    def test_session_capacity_max_then_over(self, api):
        """PRD 3.4: "For an `OPEN_WATER` session, `max_students` is 4 plus 2 for
        each assistant."
        PRD 3.5: "The seat must fit: the booking must not push the session's
        `confirmed_seats` above its `max_students`, or it is rejected with
        `ERR_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/session_capacity_at_max_then_over
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Cap Inst")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
        )
        assert session["max_students"] == 4, session

        sess_version = session["version"]
        enrollments = []
        for i in range(5):
            diver = create_waiver_cleared_diver(full_name=f"D{i+1}")
            enrollments.append(create_enrollment(diver["id"], course["id"])["id"])

        # First 4 bookings succeed; thread the version forward each time.
        for i in range(4):
            booking = book_seat(session["id"], enrollments[i], sess_version)
            sess_now = get_success_data(api.get_session(session["id"], ADMIN))
            sess_version = sess_now["version"]
        sess_after_four = get_success_data(api.get_session(session["id"], ADMIN))
        assert sess_after_four["confirmed_seats"] == 4, sess_after_four

        # 5th booking is over capacity.
        resp = api.create_session_booking(
            f.create_session_booking_payload(
                session["id"], enrollments[4], sess_version
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value, expected_status=409)

    def test_empty_session_complete_no_attendance(self, api):
        """PRD 3.4: "Completing a session drives it `SCHEDULED → COMPLETED`,
        decrements the lead instructor's `active_session_count`, and converts every
        booking on the session that is still `BOOKED` and was never recorded as
        attended into `NO_SHOW`, with each such conversion decrementing the
        session's `confirmed_seats`."

        Design: Difficulty/boundary_precision_check/empty_session_complete_no_attendance
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Eve Inst")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
        )
        assert session["confirmed_seats"] == 0, session
        set_clock("2026-06-04T09:00:00Z")
        completed = validate_success(
            api.complete_session(session["id"], make_instructor_headers(instructor["id"]))
        )
        assert completed["status"] == "COMPLETED", completed
        assert completed["confirmed_seats"] == 0, completed


class TestCrossEntityStateDependency:
    def test_session_booking_requires_active_enrollment(self, api):
        """PRD 3.5: "The enrollment must be `ACTIVE` and the session `SCHEDULED`,
        or the request is rejected with `ERR_INVALID_STATE` (HTTP 409)."
        PRD 3.3: "Withdrawal is permitted from either the `ACTIVE` or the
        `ELIGIBLE` state and drives the enrollment to the terminal `WITHDRAWN`
        status".

        Design: Difficulty/cross_entity_state_dependency/session_booking_requires_enrollment_active
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Ada Inst")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
        )
        diver = create_waiver_cleared_diver(full_name="Wendy With")
        enr = create_enrollment(diver["id"], course["id"])
        validate_success(api.withdraw_enrollment(enr["id"], ADMIN))
        resp = api.create_session_booking(
            f.create_session_booking_payload(
                session["id"], enr["id"], session["version"]
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_trip_booking_requires_diver_cert_level(self, api):
        """PRD 3.7: "the certification prerequisite — the diver's `cert_level` must
        be at least the trip's `min_cert_level`, else
        `ERR_CERT_PREREQUISITE_NOT_MET` (HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/trip_booking_requires_diver_cert_level
        """
        # Diver certified only to OPEN_WATER, with active waiver; trip is ADVANCED-min.
        boat, trip, diver = setup_trip_with_certified_diver(
            trip_overrides={"min_cert_level": "ADVANCED"},
            diver_full_name="Olive OW",
        )
        assert diver["cert_level"] == "OPEN_WATER", diver
        trip_now = get_success_data(api.get_dive_trip(trip["id"], ADMIN))
        resp = api.create_trip_booking(
            f.create_trip_booking_payload(
                trip["id"], diver["id"], trip_now["version"], tanks=0, party_size=1
            ), ADMIN,
        )
        validate_error(
            resp, ApiErrorId.ERR_CERT_PREREQUISITE_NOT_MET.value, expected_status=422
        )


class TestResourceTemporalOverlap:
    def test_instructor_overlap_half_open_adjacency_allowed(self, api):
        """PRD 3.4: "Overlap is evaluated on a half-open interval basis: each window
        covers from its `starts_at` up to but not including its `ends_at`, so two
        sessions that merely touch at a boundary (one ending exactly when the next
        begins) do not conflict, whereas any genuine overlap does. A
        non-`INSTRUCTOR` rating or a genuine window overlap is rejected with
        `ERR_INSTRUCTOR_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/instructor_session_overlap_half_open
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Tim Time")
        s1 = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T11:00:00Z",
        )
        # Adjacent at the boundary (11:00) is accepted.
        s2 = validate_success(
            api.create_session(
                f.create_session_payload(
                    course["id"], instructor["id"], session_type="OPEN_WATER",
                    starts_at="2026-07-01T11:00:00Z", ends_at="2026-07-01T13:00:00Z",
                ), ADMIN,
            ), expected_status=201,
        )
        assert s2["status"] == "SCHEDULED", s2
        # Genuine overlap (10:30-12:00) is rejected.
        resp = api.create_session(
            f.create_session_payload(
                course["id"], instructor["id"], session_type="OPEN_WATER",
                starts_at="2026-07-01T10:30:00Z", ends_at="2026-07-01T12:00:00Z",
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_CONFLICT.value, expected_status=409)

    def test_boat_overlap_closed_with_buffer(self, api):
        """PRD 3.7: "the boat must have no other non-`CANCELLED` trip whose window,
        expanded by the boat's `turnaround_minutes` on each side, overlaps the
        requested window. This is a closed-with-buffer comparison — the turnaround
        minutes are subtracted from each existing trip's start and added to each
        existing trip's end before testing for overlap, and the endpoints are
        inclusive — so a new trip must clear every existing trip by at least the
        full turnaround buffer on both sides. A conflict is rejected with
        `ERR_BOAT_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/boat_trip_overlap_closed_with_buffer
        """
        set_clock("2026-06-01T00:00:00Z")
        boat = create_boat(name="Buffered Beauty", capacity=8, turnaround_minutes=60)
        create_dive_trip(
            boat["id"], starts_at="2026-07-02T08:00:00Z",
            ends_at="2026-07-02T12:00:00Z", min_cert_level="OPEN_WATER",
            base_fare_cents=12000, fill_addon_cents=1500,
        )
        # 12:30 start is within the 60-min buffer past the 12:00 end -> conflict.
        resp = api.create_dive_trip(
            f.create_dive_trip_payload(
                boat["id"], starts_at="2026-07-02T12:30:00Z",
                ends_at="2026-07-02T16:00:00Z", min_cert_level="OPEN_WATER",
                base_fare_cents=12000, fill_addon_cents=1500,
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_BOAT_CONFLICT.value, expected_status=409)


class TestCompensatingInvariants:
    def test_session_seat_conservation_book_then_cancel(self, api):
        """PRD 2.5: "A `Session` tracks `confirmed_seats`, defined as the count of
        that session's session bookings whose status is `BOOKED`; every booking
        creation, cancellation, no-show, or attendance change that affects this set
        keeps the counter in step."
        PRD 3.5: "A diver or `ShopAdmin` may cancel a `BOOKED` booking, moving it
        `BOOKED → CANCELLED` and decrementing the session's `confirmed_seats`".

        Design: Difficulty/compensating_invariant/session_seat_conservation_book_then_cancel
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Sam Seat")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
        )
        diver = create_waiver_cleared_diver(full_name="Seth Seat")
        enr = create_enrollment(diver["id"], course["id"])
        booking = book_seat(session["id"], enr["id"], session["version"])
        after_book = get_success_data(api.get_session(session["id"], ADMIN))
        assert after_book["confirmed_seats"] == 1, after_book

        cancelled = validate_success(api.cancel_session_booking(booking["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED", cancelled
        after_cancel = get_success_data(api.get_session(session["id"], ADMIN))
        assert after_cancel["confirmed_seats"] == 0, after_cancel  # back to pre-action

    def test_diver_deposit_conservation_checkout_then_void(self, api):
        """PRD 2.5: "A `Diver` tracks `deposit_on_hold_cents`, defined as the sum of
        `deposit_cents` across that diver's rental agreements whose status is
        `ACTIVE`; this ledger is recomputed on every rental checkout, check-in, and
        void so that money debited at checkout is restored exactly when the gear is
        returned or the rental is voided."
        PRD 3.8: "Voiding drives the agreement `ACTIVE → VOIDED`, sets
        `actual_cost_cents` to 0 and `deposit_refund_cents` to the full
        `deposit_cents`, and cascades to recompute the renter's
        `deposit_on_hold_cents`, fully reversing the checkout debit."

        Design: Difficulty/compensating_invariant/diver_deposit_conservation_checkout_then_void
        """
        set_clock("2026-06-10T09:00:00Z")
        diver = create_diver(full_name="Vic Void")
        rental = create_rental(
            diver["id"], item_description="Mask",
            daily_rate_cents=4500, deposit_cents=20000,
            scheduled_return_at="2026-06-12T09:00:00Z",
        )
        held = get_success_data(api.get_diver(diver["id"], ADMIN))
        assert held["deposit_on_hold_cents"] == 20000, held

        voided = validate_success(api.void_rental_agreement(rental["id"], ADMIN))
        assert voided["status"] == "VOIDED", voided
        diver_after = get_success_data(api.get_diver(diver["id"], ADMIN))
        assert diver_after["deposit_on_hold_cents"] == 0, diver_after  # back to 0
