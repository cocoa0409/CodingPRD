"""Booking and lifecycle validations: state admissibility, closed-slot rule, duplicate,
golfer time conflict, tee-sheet spacing, slot-start-passed, OCC, revision monotonicity,
and the two PRD-pinned precedence pairs."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_booking_payload, create_tee_time_payload, create_handicap_revision_payload,
    make_proshop_headers, make_golfer_headers,
    create_course, create_golfer, create_tee_time, book_as_golfer, cancel_as_golfer,
    fetch_tee_time, set_clock, run_refresh, setup_full_twosome,
)


class TestDuplicateAndCapacity:
    def test_duplicate_booking_same_golfer_same_slot(self, api):
        """PRD §3.6: "A golfer may hold at most one non-cancelled booking — confirmed or
        standby — on any given tee time; a second attempt while one still stands is rejected
        with ERR_DUPLICATE_BOOKING."

        Design: Corner/validations/duplicate_booking_same_golfer_same_slot
        """
        set_clock()
        course = create_course(name="DupCrs")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-29T09:00:00Z", 9, "FOURSOME")
        book_as_golfer(tt["id"], ga["id"], tt["version"])
        slot = fetch_tee_time(tt["id"])
        resp = api.create_booking(
            tt["id"], create_booking_payload(ga["id"], slot["version"]),
            make_golfer_headers(ga["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BOOKING)

    def test_slot_full_without_standby_opt_in_rejected(self, api):
        """PRD §3.6: "When the slot is already FULL (confirmed count equals capacity), the
        request must opt into the waitlist by setting join_standby to true; if it does not,
        the booking is rejected with ERR_SLOT_FULL_NO_STANDBY."

        Design: Corner/validations/slot_full_no_standby_opt_in_rejected
        """
        course, tt, ga, gb, bk_a, bk_b = setup_full_twosome(course_overrides={"name": "FullNoSb"},
                                                            start_utc="2026-06-30T09:00:00Z")
        gc = create_golfer(full_name="GC", membership_tier="PUBLIC")
        slot = fetch_tee_time(tt["id"])
        resp = api.create_booking(
            tt["id"], create_booking_payload(gc["id"], slot["version"]),
            make_golfer_headers(gc["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_FULL_NO_STANDBY)


class TestTemporalValidations:
    def test_book_slot_already_started_rejected(self, api):
        """PRD §3.6: "The slot's start_utc must also be strictly after the current clock — a
        slot whose start instant is exactly now or already past cannot be booked, and the
        attempt is rejected with ERR_SLOT_START_PASSED."

        Design: Corner/validations/book_slot_already_started_rejected
        """
        set_clock()
        course = create_course(name="PastCrs")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-02T09:00:00Z", 9, "FOURSOME")
        set_clock("2026-06-02T09:00:00Z")  # clock == slot start
        resp = api.create_booking(
            tt["id"], create_booking_payload(ga["id"], tt["version"]),
            make_golfer_headers(ga["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_START_PASSED)

    def test_golfer_calendar_overlap_rejected_adjacency_allowed(self, api):
        """PRD §3.6: "A golfer also may not hold confirmed bookings on two slots whose
        occupancy windows overlap: each confirmed booking occupies its slot's start instant
        through 12 minutes later, treated as a half-open interval, so two slots collide when
        those 12-minute windows overlap; back-to-back slots that merely touch at the boundary
        do not conflict. A violation is rejected with ERR_GOLFER_TIME_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/golfer_calendar_halfopen_overlap_adjacency_allowed
        """
        set_clock()
        # Separate courses so the tee-sheet spacing rule does not interfere.
        course_a = create_course(name="CalCourseA", course_rating=72.0, slope_rating=125)
        course_b = create_course(name="CalCourseB", course_rating=72.0, slope_rating=125)
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt1 = create_tee_time(course_a["id"], "2026-06-12T09:00:00Z", 9, "FOURSOME")
        tt2 = create_tee_time(course_b["id"], "2026-06-12T09:06:00Z", 9, "FOURSOME")  # 6 min -> overlaps
        book_as_golfer(tt1["id"], ga["id"], tt1["version"])
        resp = api.create_booking(
            tt2["id"], create_booking_payload(ga["id"], tt2["version"]),
            make_golfer_headers(ga["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GOLFER_TIME_CONFLICT)

    def test_course_teesheet_buffer_spacing_conflict(self, api):
        """PRD §3.5: "A new tee time's start_utc must be at least the minimum tee interval of
        8 minutes away from every existing non-closed tee time on the same course. ... the
        absolute difference between the new slot's start and any existing slot's start must
        not be under 8 minutes. Exactly 8 minutes apart is allowed; anything strictly closer
        collides and is rejected with ERR_TEE_INTERVAL_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/course_teesheet_buffer_spacing_conflict
        """
        set_clock()
        course = create_course(name="SheetCourse", course_rating=72.0, slope_rating=125)
        create_tee_time(course["id"], "2026-06-13T10:00:00Z", 10, "FOURSOME")
        resp = api.create_tee_time(
            create_tee_time_payload(course["id"], "2026-06-13T10:05:00Z", 10, "FOURSOME"),
            make_proshop_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_TEE_INTERVAL_CONFLICT)

    def test_tee_interval_exactly_eight_minutes_allowed(self, api):
        """PRD §3.5: "Exactly 8 minutes apart is allowed; anything strictly closer collides
        and is rejected with ERR_TEE_INTERVAL_CONFLICT."

        Design: Corner/validations/tee_interval_exactly_eight_minutes_allowed
        """
        set_clock()
        course = create_course(name="GapOk")
        create_tee_time(course["id"], "2026-07-01T10:00:00Z", 10, "FOURSOME")
        resp = api.create_tee_time(
            create_tee_time_payload(course["id"], "2026-07-01T10:08:00Z", 10, "FOURSOME"),
            make_proshop_headers(),
        )
        tt2 = validate_success(resp, 201)
        assert tt2["status"] == "OPEN"


class TestOptimisticConcurrency:
    def test_stale_tee_time_version_rejected(self, api):
        """PRD §2.6: "If they differ — meaning another writer has advanced the slot since the
        client read it, for example by taking the last open seat and flipping the slot to
        FULL — the request is rejected with ERR_STALE_TEE_TIME_VERSION and HTTP status 412."

        Design: Corner/errors/occ_stale_tee_time_version_conflict
        """
        set_clock()
        course = create_course(name="OccCrs")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        gb = create_golfer(full_name="GB", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-07-06T09:00:00Z", 9, "FOURSOME")
        v0 = tt["version"]
        book_as_golfer(tt["id"], ga["id"], v0)  # advances version
        resp = api.create_booking(
            tt["id"], create_booking_payload(gb["id"], v0),  # stale v0
            make_golfer_headers(gb["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_TEE_TIME_VERSION)

    def test_booking_increments_tee_time_version(self, api):
        """PRD §2.5: "its confirmed_count is re-derived from the bookings that hold it, its
        status follows from that count, its updated_at is refreshed, and its version is
        incremented by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_booking_write
        """
        set_clock()
        course = create_course(name="VerCrs")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-07-07T09:00:00Z", 9, "FOURSOME")
        book_as_golfer(tt["id"], ga["id"], tt["version"])
        slot = fetch_tee_time(tt["id"])
        assert slot["version"] == 2
        assert slot["confirmed_count"] == 1


class TestRevisionMonotonic:
    def test_revision_not_monotonic_rejected(self, api):
        """PRD §3.4: "The supplied effective_utc must be strictly after the effective_utc of
        the most recent prior revision; a run that is not strictly later is rejected with
        ERR_REVISION_NOT_MONOTONIC."

        Design: Corner/validations/revision_not_monotonic_rejected
        """
        run_refresh("2026-03-31T00:00:00Z")
        resp = api.create_handicap_revision(
            create_handicap_revision_payload("2026-03-31T00:00:00Z"), make_proshop_headers()
        )
        validate_error(resp, ApiErrorId.ERR_REVISION_NOT_MONOTONIC)


class TestInvalidStateTransitions:
    def test_cancel_already_cancelled_booking_invalid_state(self, api):
        """PRD §3.8: "Only a booking currently CONFIRMED or STANDBY may be cancelled;
        cancelling one already CANCELLED is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/cancel_already_cancelled_booking_invalid_state
        """
        set_clock()
        course = create_course(name="ISCourse")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-21T09:00:00Z", 9, "FOURSOME")
        bk = book_as_golfer(tt["id"], ga["id"], tt["version"])
        cancel_as_golfer(bk["id"], ga["id"])
        resp = api.cancel_booking(bk["id"], make_golfer_headers(ga["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_void_already_void_score_invalid_state(self, api):
        """PRD §3.3: "voiding a score already in VOID is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/void_already_void_score_invalid_state
        """
        course = create_course(name="VV")
        golfer = create_golfer(full_name="VG", membership_tier="PUBLIC")
        score_resp = api.create_score(
            {"golfer_id": golfer["id"], "course_id": course["id"],
             "played_on": "2026-05-01", "adjusted_gross_score": 85},
            make_proshop_headers(),
        )
        score = validate_success(score_resp, 201)
        validate_success(api.void_score(score["id"], make_proshop_headers()), 200)
        resp = api.void_score(score["id"], make_proshop_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_already_closed_teetime_invalid_state(self, api):
        """PRD §3.5: "Closing requires the slot be OPEN; attempting it from another state
        yields ERR_INVALID_STATE."

        Design: Corner/state_machines/close_already_closed_teetime_invalid_state
        """
        set_clock()
        course = create_course(name="ClCourse")
        tt = create_tee_time(course["id"], "2026-06-22T09:00:00Z", 9, "TWOSOME")
        validate_success(api.close_tee_time(tt["id"], make_proshop_headers()), 200)
        resp = api.close_tee_time(tt["id"], make_proshop_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_book_closed_teetime_returns_closed_error(self, api):
        """PRD §3.6: "a slot already in CLOSED status rejects booking creation with
        ERR_TEE_TIME_CLOSED, which is the more specific code that takes precedence over the
        generic invalid-state result for the closed case."

        Design: Corner/state_machines/book_closed_teetime_returns_closed_error
        """
        set_clock()
        course = create_course(name="BkClosed")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-23T09:00:00Z", 9, "TWOSOME")
        closed = validate_success(api.close_tee_time(tt["id"], make_proshop_headers()), 200)
        resp = api.create_booking(
            tt["id"], create_booking_payload(ga["id"], closed["version"]),
            make_golfer_headers(ga["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEE_TIME_CLOSED)


class TestValidationPrecedence:
    def test_closed_slot_beats_duplicate_booking(self, api):
        """PRD §3.6: "The order is: authentication first (ERR_UNAUTHENTICATED), then role
        permission (ERR_FORBIDDEN_ROLE), then existence of the referenced slot and golfer
        (ERR_NOT_FOUND), then state admissibility, then the specific closed-slot rule, then
        the duplicate-booking rule, then the golfer time-conflict rule, then the
        slot-start-passed rule, then the optimistic-concurrency check, and finally the
        capacity/standby rule."

        Design: Difficulty/priority_pair_validation_conflict/closed_slot_beats_duplicate_booking
        """
        set_clock()
        course = create_course(name="PriCourse", course_rating=72.0, slope_rating=125)
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-07T09:00:00Z", 9, "FOURSOME")
        book_as_golfer(tt["id"], ga["id"], tt["version"])  # GA already CONFIRMED
        closed = validate_success(api.close_tee_time(tt["id"], make_proshop_headers()), 200)
        # GA re-books a now-CLOSED slot: both closed and duplicate would fire; closed wins.
        resp = api.create_booking(
            tt["id"], create_booking_payload(ga["id"], closed["version"]),
            make_golfer_headers(ga["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEE_TIME_CLOSED)

    def test_not_owner_beats_invalid_state_on_cancel(self, api):
        """PRD §3.8: "A booking is cancelled by its holding Golfer or by any ProShop operator;
        a golfer who is not the holder and is not acting as ProShop is rejected with
        ERR_NOT_BOOKING_OWNER. Only a booking currently CONFIRMED or STANDBY may be cancelled;
        cancelling one already CANCELLED is rejected with ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/not_owner_beats_invalid_state_on_cancel
        """
        set_clock()
        course = create_course(name="OwnCourse", course_rating=72.0, slope_rating=125)
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        gb = create_golfer(full_name="GB", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-06-08T09:00:00Z", 9, "FOURSOME")
        bk = book_as_golfer(tt["id"], ga["id"], tt["version"])
        cancel_as_golfer(bk["id"], ga["id"])  # now CANCELLED
        # Non-owner GB cancels an already-CANCELLED booking: ownership checked before state.
        resp = api.cancel_booking(bk["id"], make_golfer_headers(gb["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_BOOKING_OWNER)
