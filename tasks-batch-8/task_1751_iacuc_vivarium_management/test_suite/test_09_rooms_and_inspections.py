"""Procedure-room scheduling and semiannual inspections: turnover-buffer
conflict boundaries, past-dated bookings, cancellation clearing conflicts,
inspection due-date computation and lapse (PRD §3.9).
"""
from test_helpers import (
    ADMIN,
    STAFF,
    ApiErrorId,
    api_client,
    assert_inspection,
    assert_room_booking,
    get_success_data,
    parse_instant,
    set_clock,
    setup_booking_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import book_room, complete_inspection_ok, create_inspection


class TestTurnoverBuffer:
    def test_booking_inside_buffer_rejected_but_buffer_end_allowed(self, api):
        """PRD §3.9: "Conflict detection adds a thirty-minute turnover buffer:
        each booking effectively occupies its interval extended thirty minutes
        past its end, so a new booking conflicts with an existing `CONFIRMED`
        booking in the same room whenever the new `start_at` falls earlier
        than thirty minutes after the existing booking's `end_at` and,
        simultaneously, the existing booking's start falls earlier than thirty
        minutes after the new booking's `end_at`. Such a conflict is rejected
        with `ERR_ROOM_CONFLICT` (HTTP 409), while a new booking starting
        exactly thirty minutes after an existing booking ends is permitted."

        Design: Difficulty/resource_temporal_overlap/room_booking_turnover_buffer_half_open
        """
        scenario = setup_booking_scenario()
        proto_id = scenario["protocol"]["id"]
        booker_id = scenario["booker"]["id"]

        first = validate_success(book_room(
            proto_id, booker_id, "PROC-1",
            "2026-08-15T09:00:00Z", "2026-08-15T10:00:00Z",
        ), expected_status=201)
        assert_room_booking(first)
        assert first["state"] == "CONFIRMED"

        inside_buffer = book_room(
            proto_id, booker_id, "PROC-1",
            "2026-08-15T10:15:00Z", "2026-08-15T11:00:00Z",
        )
        validate_error(inside_buffer, ApiErrorId.ERR_ROOM_CONFLICT)

        at_buffer_end = validate_success(book_room(
            proto_id, booker_id, "PROC-1",
            "2026-08-15T10:30:00Z", "2026-08-15T11:30:00Z",
        ), expected_status=201)
        assert at_buffer_end["state"] == "CONFIRMED", (
            "starting exactly thirty minutes after the existing end is "
            "permitted (buffer end is exclusive)"
        )

    def test_booking_ending_exactly_buffer_before_existing_allowed(self, api):
        """PRD §3.9: "a new booking conflicts with an existing `CONFIRMED`
        booking in the same room whenever the new `start_at` falls earlier
        than thirty minutes after the existing booking's `end_at` and,
        simultaneously, the existing booking's start falls earlier than thirty
        minutes after the new booking's `end_at`."

        Design: Difficulty/resource_temporal_overlap/room_booking_turnover_buffer_half_open
        """
        scenario = setup_booking_scenario()
        proto_id = scenario["protocol"]["id"]
        booker_id = scenario["booker"]["id"]
        validate_success(book_room(
            proto_id, booker_id, "PROC-3",
            "2026-08-15T09:00:00Z", "2026-08-15T10:00:00Z",
        ), expected_status=201)

        # One minute inside the buffer on the early side: 08:31 + 30m = 09:01
        # is later than the existing 09:00 start -> conflict.
        early_conflict = book_room(
            proto_id, booker_id, "PROC-3",
            "2026-08-15T08:00:00Z", "2026-08-15T08:31:00Z",
        )
        validate_error(early_conflict, ApiErrorId.ERR_ROOM_CONFLICT)

        # Ending exactly 30 minutes before the existing start: 08:30 + 30m =
        # 09:00 is not earlier than 09:00 -> allowed.
        early_ok = validate_success(book_room(
            proto_id, booker_id, "PROC-3",
            "2026-08-15T08:00:00Z", "2026-08-15T08:30:00Z",
        ), expected_status=201)
        assert early_ok["state"] == "CONFIRMED"


class TestBookingTemporalRules:
    def test_booking_starting_in_the_past_rejected(self, api):
        """PRD §3.9: "`start_at` must not precede the current logical clock
        time (else `ERR_BOOKING_IN_PAST`, HTTP 422)."

        Design: Corner/endpoints/room_booking_in_past_rejected
        """
        scenario = setup_booking_scenario()
        set_clock("2026-08-10T00:00:00Z")

        resp = book_room(
            scenario["protocol"]["id"], scenario["booker"]["id"], "PROC-9",
            "2026-08-09T09:00:00Z", "2026-08-09T10:00:00Z",
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_IN_PAST)

    def test_cancelled_booking_releases_its_slot(self, api):
        """PRD §3.9: "Cancellation by an `AnimalCareStaff` member or the
        `AttendingVeterinarian` moves the booking from `CONFIRMED` to
        `CANCELLED`, terminal, and removes it from the conflict candidate
        set."

        Design: Corner/endpoints/cancel_booking_removes_conflict
        """
        scenario = setup_booking_scenario()
        proto_id = scenario["protocol"]["id"]
        booker_id = scenario["booker"]["id"]

        booking = validate_success(book_room(
            proto_id, booker_id, "PROC-2",
            "2026-08-20T09:00:00Z", "2026-08-20T10:00:00Z",
        ), expected_status=201)

        cancelled = validate_success(
            api_client.cancel_room_booking(booking["id"], STAFF)
        )
        assert cancelled["state"] == "CANCELLED"

        rebooked = validate_success(book_room(
            proto_id, booker_id, "PROC-2",
            "2026-08-20T09:15:00Z", "2026-08-20T10:00:00Z",
        ), expected_status=201)
        assert rebooked["state"] == "CONFIRMED", (
            "the cancelled booking no longer participates in conflict "
            "detection"
        )


class TestInspectionScheduling:
    def test_due_by_is_180_days_and_boundary_is_inclusive(self, api):
        """PRD §3.9: "The server computes `due_by` as the completion time of
        the most recent `COMPLETED` inspection of the same kind plus 180 days;
        when no inspection of that kind has ever been completed, `due_by`
        equals the new inspection's own `scheduled_for`, so the first cycle is
        free." and "completion at or before `due_by` moves the inspection to
        `COMPLETED` — the boundary is inclusive, so completion exactly at
        `due_by` is on time".

        Design: Corner/calculations/inspection_due_date_180_days_and_lapse
        """
        set_clock("2026-01-10T00:00:00Z")
        first = create_inspection(
            inspection_kind="FACILITY", scheduled_for="2026-01-15T00:00:00Z",
        )
        assert_inspection(first)
        assert first["state"] == "SCHEDULED"
        assert first["deficiency_count"] == 0, (
            "an optional `deficiency_count` ... defaults to zero (PRD §3.9)"
        )
        assert parse_instant(first["due_by"]) == parse_instant(
            "2026-01-15T00:00:00Z"
        ), "first cycle: due_by equals scheduled_for"

        completed = complete_inspection_ok(first["id"], "2026-01-15T00:00:00Z", 0)
        assert completed["state"] == "COMPLETED"

        follow_up = create_inspection(
            inspection_kind="FACILITY", scheduled_for="2026-07-10T00:00:00Z",
        )
        assert parse_instant(follow_up["due_by"]) == parse_instant(
            "2026-07-14T00:00:00Z"
        ), "due_by = last completion 2026-01-15 + 180 days"

        on_time = complete_inspection_ok(
            follow_up["id"], "2026-07-14T00:00:00Z", 1,
        )
        assert on_time["state"] == "COMPLETED", (
            "completion exactly at due_by is on time (inclusive boundary)"
        )

    def test_completion_one_second_past_due_by_lapses(self, api):
        """PRD §3.9: "completion even one second past `due_by` moves the
        inspection to `LAPSED` and surfaces `ERR_INSPECTION_LAPSED` (HTTP
        422)."

        Design: Corner/calculations/inspection_completion_after_due_by_lapses
        """
        set_clock("2026-01-10T00:00:00Z")
        first = create_inspection(
            inspection_kind="FACILITY", scheduled_for="2026-01-15T00:00:00Z",
        )
        complete_inspection_ok(first["id"], "2026-01-15T00:00:00Z", 0)
        follow_up = create_inspection(
            inspection_kind="FACILITY", scheduled_for="2026-07-10T00:00:00Z",
        )
        # due_by is 2026-07-14T00:00:00Z; the logical clock (2026-01-10) has
        # not passed it, so the inspection still stands SCHEDULED and the
        # completion's own lateness decides.
        resp = api_client.complete_inspection(
            follow_up["id"],
            {"completed_at": "2026-07-14T00:00:01Z", "deficiency_count": 0},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_LAPSED)

        current = get_success_data(
            api_client.get_inspection(follow_up["id"], ADMIN)
        )
        assert current["state"] == "LAPSED"


