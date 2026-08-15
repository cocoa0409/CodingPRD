"""Venue booking intervals, program locking gates, and piece confirm gates."""
from test_helpers import (
    ApiErrorId,
    activate_member,
    advance_posture,
    contract_in_state,
    create_booking,
    create_booking_payload,
    create_concert,
    create_contract,
    create_open_season_with_section,
    create_piece,
    create_piece_payload,
    create_venue,
    enroll_member,
    issue_invoice,
    offer_contract,
    set_clock,
    setup_concert_with_confirmed_booking,
    setup_rehearsing_season_with_active_member,
    validate_error,
    validate_success,
)


class TestVenueHalfOpenOverlap:
    def test_venue_booking_half_open_overlap(self, api, director_headers):
        """PRD §3.6: "a `start_at` and `end_at` defining a half-open interval —
        the start is inclusive, the end exclusive, so back-to-back bookings
        that merely touch are permitted — and a `deposit_cents`. The interval
        must not intersect any existing non-terminal booking of the same venue,
        else `ERR_VENUE_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/venue_booking_half_open_overlap
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())
        venue = create_venue()
        c1 = create_concert(season["id"], "Gala", 80)
        first = create_booking(c1["id"], venue["id"],
                               "2026-09-10T18:00:00Z", "2026-09-10T21:00:00Z")
        assert first["status"] == "REQUESTED"

        # Adjacent half-open interval [21:00, 23:00): touches, does not
        # intersect — permitted.
        c2 = create_concert(season["id"], "Late Show", 50)
        adjacent = validate_success(api.create_booking(
            create_booking_payload(c2["id"], venue["id"],
                                   "2026-09-10T21:00:00Z",
                                   "2026-09-10T23:00:00Z"),
            director_headers), 201)
        assert adjacent["status"] == "REQUESTED"

        # [20:00, 22:00) genuinely intersects the first booking.
        c3 = create_concert(season["id"], "Clash", 50)
        resp = api.create_booking(
            create_booking_payload(c3["id"], venue["id"],
                                   "2026-09-10T20:00:00Z",
                                   "2026-09-10T22:00:00Z"),
            director_headers)
        validate_error(resp, ApiErrorId.ERR_VENUE_OVERLAP)

    def test_venue_booking_touching_at_start_boundary_allowed(
            self, api, director_headers):
        """PRD §3.6: "the start is inclusive, the end exclusive, so
        back-to-back bookings that merely touch are permitted"

        Design: Difficulty/resource_temporal_overlap/venue_booking_half_open_overlap
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())
        venue = create_venue()
        c1 = create_concert(season["id"], "Evening", 80)
        create_booking(c1["id"], venue["id"],
                       "2026-09-10T18:00:00Z", "2026-09-10T21:00:00Z")

        # [17:00, 18:00) ends exactly where the existing booking begins.
        c2 = create_concert(season["id"], "Matinee", 50)
        touching = validate_success(api.create_booking(
            create_booking_payload(c2["id"], venue["id"],
                                   "2026-09-10T17:00:00Z",
                                   "2026-09-10T18:00:00Z"),
            director_headers), 201)
        assert touching["status"] == "REQUESTED"

        # [17:30, 18:30) crosses the boundary and intersects.
        c3 = create_concert(season["id"], "Overlap", 50)
        resp = api.create_booking(
            create_booking_payload(c3["id"], venue["id"],
                                   "2026-09-10T17:30:00Z",
                                   "2026-09-10T18:30:00Z"),
            director_headers)
        validate_error(resp, ApiErrorId.ERR_VENUE_OVERLAP)


class TestValidationTierOrdering:
    def test_venue_overlap_beats_lead_time(self, api, director_headers):
        """PRD §2.8: "Eleventh, business constraints (uniqueness, capacity,
        overlap). Twelfth, temporal rules (lead times and clock comparisons)."
        and "A failure in an earlier tier masks every later check, so a caller
        always sees the highest-priority applicable error."
        PRD §3.6: "the `start_at` must be at least 72 hours — three full days —
        in the future, else `ERR_BOOKING_LEAD_TIME`"

        Design: Difficulty/priority_pair_validation_conflict/venue_overlap_beats_lead_time
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())
        venue = create_venue()
        c1 = create_concert(season["id"], "Gala", 80)
        create_booking(c1["id"], venue["id"],
                       "2026-09-10T18:00:00Z", "2026-09-10T21:00:00Z")
        c2 = create_concert(season["id"], "Gala 2", 50)

        # Clock 2026-09-08: a 2026-09-10 start violates the 72-hour lead AND
        # the 20:00-22:00 window intersects the existing 18:00-21:00 booking.
        set_clock("2026-09-08T00:00:00Z")
        resp = api.create_booking(
            create_booking_payload(c2["id"], venue["id"],
                                   "2026-09-10T20:00:00Z",
                                   "2026-09-10T22:00:00Z"),
            director_headers)
        # Overlap (constraint tier) masks the lead-time (temporal tier) error.
        validate_error(resp, ApiErrorId.ERR_VENUE_OVERLAP)

    def test_venue_capacity_beats_lead_time(self, api, director_headers):
        """PRD §2.8: "Eleventh, business constraints (uniqueness, capacity,
        overlap). Twelfth, temporal rules (lead times and clock comparisons)."
        PRD §3.6: "the concert's `expected_attendance` must not exceed the
        venue's `capacity`, else `ERR_VENUE_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/venue_overlap_beats_lead_time
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())
        venue = create_venue(capacity=50)
        concert = create_concert(season["id"], "Too Big", 80)

        set_clock("2026-09-08T00:00:00Z")  # 2026-09-10 start violates 72h lead
        resp = api.create_booking(
            create_booking_payload(concert["id"], venue["id"],
                                   "2026-09-10T18:00:00Z",
                                   "2026-09-10T21:00:00Z"),
            director_headers)
        # Capacity (constraint tier) masks the lead-time (temporal tier) error.
        validate_error(resp, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED)


class TestBookingCreationGates:
    def test_archived_venue_blocks_booking(self, api, director_headers,
                                           president_headers):
        """PRD §3.6: "Archiving is terminal, makes the venue reject all new
        bookings with `ERR_VENUE_ARCHIVED`, and leaves existing `CONFIRMED`
        bookings unaffected."

        Design: Corner/validations/archived_venue_blocks_booking
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())
        venue = create_venue("Old Hall")
        archived = validate_success(api.archive_venue(venue["id"],
                                                      president_headers))
        assert archived["status"] == "ARCHIVED"
        concert = create_concert(season["id"])

        resp = api.create_booking(
            create_booking_payload(concert["id"], venue["id"]),
            director_headers)
        validate_error(resp, ApiErrorId.ERR_VENUE_ARCHIVED)

    def test_venue_capacity_exceeded_rejected(self, api, director_headers):
        """PRD §3.6: "the concert's `expected_attendance` must not exceed the
        venue's `capacity`, else `ERR_VENUE_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/venue_capacity_exceeded_rejected
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())
        venue = create_venue(capacity=100)
        concert = create_concert(season["id"], "Gala", 150)
        resp = api.create_booking(
            create_booking_payload(concert["id"], venue["id"]),
            director_headers)
        validate_error(resp, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED)


class TestProgramSequenceAndLength:
    def test_program_sequence_conflict_rejected(self, api, director_headers):
        """PRD §3.6: "The `sequence_no` must be unique within its concert among
        pieces that are not `VOID`, a constraint enforced both at creation and
        on update, else `ERR_PROGRAM_SEQUENCE_CONFLICT`."

        Design: Corner/validations/program_sequence_conflict_rejected
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())
        concert = create_concert(season["id"])
        create_piece(concert["id"], "Suite", 600, 1)

        resp = api.create_piece(
            create_piece_payload(concert["id"], "Other", 600, 1),
            director_headers)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_SEQUENCE_CONFLICT)

    def test_program_too_long_rejected_at_lock(self, api, director_headers):
        """PRD §3.6: "and requires the total program duration to fit the
        booking window with a 900-second — fifteen-minute — buffer to spare:
        `program_duration_seconds` must not exceed the gap between the
        booking's `end_at` and `start_at` minus 900 seconds, else
        `ERR_PROGRAM_TOO_LONG` (HTTP 422)."

        Design: Corner/validations/program_too_long_rejected_at_lock
        """
        # Booking window 18:00-19:00 = 3600s; minus 900s buffer leaves 2700s.
        season, _section, _member, _venue, concert, _booking = (
            setup_concert_with_confirmed_booking(
                start_at="2026-09-10T18:00:00Z",
                end_at="2026-09-10T19:00:00Z"))
        piece = create_piece(concert["id"], "Long Work", 3600, 1)
        confirmed = validate_success(api.confirm_piece(piece["id"],
                                                       director_headers))
        assert confirmed["status"] == "CONFIRMED"

        resp = api.transition_concert(concert["id"], "LOCK_PROGRAM",
                                      director_headers)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_TOO_LONG)


class TestConcertTransitionGates:
    def test_concert_lock_program_without_confirmed_booking_rejected(
            self, api, director_headers):
        """PRD §3.6: "Locking the program — `VENUE_BOOKED` to `PROGRAM_LOCKED`
        — requires the booking to be `CONFIRMED`, else
        `ERR_BOOKING_NOT_CONFIRMED`"

        Design: Corner/state_machines/concert_lock_program_without_confirmed_booking_rejected
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())
        venue = create_venue()
        concert = create_concert(season["id"])
        booking = create_booking(concert["id"], venue["id"])
        assert booking["status"] == "REQUESTED"  # never confirmed
        piece = create_piece(concert["id"], "Suite", 3600, 1)
        validate_success(api.confirm_piece(piece["id"], director_headers))

        resp = api.transition_concert(concert["id"], "LOCK_PROGRAM",
                                      director_headers)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CONFIRMED)

        concert_data = validate_success(api.get_concert(concert["id"],
                                                        director_headers))
        assert concert_data["status"] == "PLANNING"

    def test_concert_mark_ready_with_unpaid_contract_rejected(
            self, api, director_headers):
        """PRD §3.6: "Marking ready — `PROGRAM_LOCKED` to `READY` — requires
        every `CONFIRMED` piece carrying a `guest_contract_id` to have that
        contract in `PAID`, else `ERR_CONTRACT_UNPAID`."

        Design: Corner/state_machines/concert_mark_ready_with_unpaid_contract_rejected
        """
        season, _section, _member, _venue, concert, _booking = (
            setup_concert_with_confirmed_booking())
        contract = contract_in_state(season["id"], "ACCEPTED",
                                     rate_cents=10000,
                                     concert_id=concert["id"])
        piece = create_piece(concert["id"], "Suite", 3600, 1,
                             guest_contract_id=contract["id"])
        validate_success(api.confirm_piece(piece["id"], director_headers))
        locked = validate_success(api.transition_concert(
            concert["id"], "LOCK_PROGRAM", director_headers))
        assert locked["status"] == "PROGRAM_LOCKED"

        # The linked contract is ACCEPTED, not PAID.
        resp = api.transition_concert(concert["id"], "MARK_READY",
                                      director_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_UNPAID)

        concert_data = validate_success(api.get_concert(concert["id"],
                                                        director_headers))
        assert concert_data["status"] == "PROGRAM_LOCKED"

    def test_concert_perform_before_booking_start_rejected(
            self, api, director_headers):
        """PRD §3.6: "Performing — `READY` to `PERFORMED` — requires the clock
        to have reached the booking's `start_at`, else
        `ERR_CONCERT_TOO_EARLY`."

        Design: Corner/state_machines/concert_perform_before_booking_start_rejected
        """
        season, _section, _member, _venue, concert, _booking = (
            setup_concert_with_confirmed_booking())
        piece = create_piece(concert["id"], "Suite", 3600, 1)
        validate_success(api.confirm_piece(piece["id"], director_headers))
        validate_success(api.transition_concert(concert["id"], "LOCK_PROGRAM",
                                                director_headers))
        ready = validate_success(api.transition_concert(
            concert["id"], "MARK_READY", director_headers))
        assert ready["status"] == "READY"

        # 2026-09-01 is before the 2026-09-10 18:00 booking start.
        set_clock("2026-09-01T00:00:00Z")
        resp = api.transition_concert(concert["id"], "PERFORM",
                                      director_headers)
        validate_error(resp, ApiErrorId.ERR_CONCERT_TOO_EARLY)

        concert_data = validate_success(api.get_concert(concert["id"],
                                                        director_headers))
        assert concert_data["status"] == "READY"


class TestPieceConfirmGates:
    def test_program_piece_requires_contract_accepted(self, api,
                                                      director_headers):
        """PRD §3.6: "and if a `guest_contract_id` is linked, that contract
        must be `ACCEPTED`, `APPROVED`, or `PAID`, else
        `ERR_CONTRACT_NOT_ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/program_piece_requires_contract_accepted
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())
        concert = create_concert(season["id"])
        contract = create_contract(season["id"],
                                   service_lines=[{"kind": "CONCERT",
                                                   "units": 1,
                                                   "rate_cents": 30000}],
                                   concert_id=concert["id"])
        offer_contract(contract["id"])  # OFFERED, not yet ACCEPTED
        piece = create_piece(concert["id"], "Suite", 3600, 1,
                             guest_contract_id=contract["id"])

        resp = api.confirm_piece(piece["id"], director_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACCEPTED)

        accepted = validate_success(api.accept_contract(contract["id"],
                                                        director_headers))
        assert accepted["status"] == "ACCEPTED"
        confirmed = validate_success(api.confirm_piece(piece["id"],
                                                       director_headers))
        assert confirmed["status"] == "CONFIRMED"

    def test_program_piece_confirm_allows_approved_contract(
            self, api, director_headers, president_headers):
        """PRD §3.6: "and if a `guest_contract_id` is linked, that contract
        must be `ACCEPTED`, `APPROVED`, or `PAID`, else
        `ERR_CONTRACT_NOT_ACCEPTED`." — an APPROVED contract also satisfies
        the gate.

        Design: Difficulty/cross_entity_state_dependency/program_piece_requires_contract_accepted
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())
        concert = create_concert(season["id"])
        contract = contract_in_state(season["id"], "APPROVED",
                                     rate_cents=10000,
                                     concert_id=concert["id"],
                                     approver_headers=president_headers)
        piece = create_piece(concert["id"], "Suite", 3600, 1,
                             guest_contract_id=contract["id"])
        confirmed = validate_success(api.confirm_piece(piece["id"],
                                                       director_headers))
        assert confirmed["status"] == "CONFIRMED"

    def test_ineligible_featured_member_blocks_piece_confirm(
            self, api, director_headers):
        """PRD §3.6: "every member named in `featured_member_ids` must be
        `performance_eligible` at that moment, else
        `ERR_MEMBER_NOT_ELIGIBLE`"
        PRD §3.3: "`performance_eligible` is true exactly when the member's
        status is `ACTIVE`, their `attendance_rate` is at least the season's
        `attendance_threshold`, and their `dues_balance_cents` is zero."

        Design: Corner/validations/ineligible_featured_member_blocks_piece_confirm
        """
        season, section = create_open_season_with_section(target_max=4)
        # Anchor member pays up so the balance gate can pass to REHEARSING.
        activate_member(season["id"], section["id"], "Anchor", "anchor@x.org",
                        "2026-08-02T10:00:00Z")
        advance_posture(season["id"], "REHEARSING")
        # Second member is ENROLLED but has an unpaid invoice: not eligible.
        m2 = enroll_member(season["id"], section["id"], "Ben", "ben@x.org",
                           "2026-08-09T10:00:00Z")
        issue_invoice(m2["id"])
        member_data = validate_success(api.get_member(m2["id"],
                                                      director_headers))
        assert member_data["performance_eligible"] is False

        concert = create_concert(season["id"])
        piece = create_piece(concert["id"], "Duet", 600, 1,
                             featured_member_ids=[m2["id"]])
        resp = api.confirm_piece(piece["id"], director_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE)

        piece_data = validate_success(api.get_piece(piece["id"],
                                                    director_headers))
        assert piece_data["status"] == "DRAFT"
