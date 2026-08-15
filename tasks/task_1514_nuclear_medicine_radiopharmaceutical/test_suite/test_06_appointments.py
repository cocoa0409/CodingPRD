"""Procedure appointments: buffered half-open overlap, room-posture precedence,
and the administration completion bubble-up."""
from test_helpers import (
    TEST_USERS,
    assert_procedure_appointment,
    book_appointment,
    create_order,
    create_procedure_appointment_payload,
    get_appointment,
    get_order,
    get_room,
    make_technologist_headers,
    report_spill,
    setup_f18_administered,
    setup_f18_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
TECH1 = make_technologist_headers("tech-1")


def _two_orders(ctx):
    """Second ORDERED order for the same patient/isotope."""
    return create_order(
        ctx["patient"]["id"],
        ctx["isotope"]["id"],
        ctx["authorized_user"],
        administration_scheduled_at="2026-08-01T12:00:00Z",
    )


class TestBufferedHalfOpenOverlap:
    """Existing booking 09:00-09:30 in a room with a 15-minute cleanup buffer
    occupies [09:00, 09:45) for overlap purposes."""

    def test_booking_inside_buffer_rejected(self, api):
        """PRD §3.5: "For overlap checking, every existing `BOOKED` appointment
        in the same room is treated as occupying an interval extended by the
        room's `cleanup_buffer_minutes` — from its start up to but not including
        its end plus the buffer. A conflict exists whenever the new booking's
        start falls before an existing booking's buffer-extended end and that
        existing booking's start falls before the new booking's end... A
        conflicting booking is rejected with `ERR_APPOINTMENT_OVERLAP`
        (HTTP 409)."

        New booking 09:44-10:00 starts before the buffer-extended end 09:45.

        Design: Difficulty/resource_temporal_overlap/room_booking_buffer_half_open
        """
        ctx = setup_f18_order()
        order2 = _two_orders(ctx)
        book_appointment(
            ctx["order"]["id"], ctx["room"]["id"],
            start_at="2026-08-01T09:00:00Z", end_at="2026-08-01T09:30:00Z",
        )
        res = api.create_procedure_appointment(
            create_procedure_appointment_payload(
                order2["id"], ctx["room"]["id"],
                start_at="2026-08-01T09:44:00Z", end_at="2026-08-01T10:00:00Z",
            ),
            TECH1,
        )
        validate_error(res, "ERR_APPOINTMENT_OVERLAP", expected_status=409)

    def test_booking_starting_at_buffer_end_allowed(self, api):
        """PRD §3.5: "a new booking that starts exactly at another's
        buffer-extended end does not conflict, because half-open intervals that
        share only an endpoint have an empty intersection."

        New booking 09:45-10:15 touches the occupied interval [09:00, 09:45)
        only at its endpoint and is accepted.

        Design: Difficulty/resource_temporal_overlap/room_booking_buffer_half_open
        """
        ctx = setup_f18_order()
        order2 = _two_orders(ctx)
        book_appointment(
            ctx["order"]["id"], ctx["room"]["id"],
            start_at="2026-08-01T09:00:00Z", end_at="2026-08-01T09:30:00Z",
        )
        res = api.create_procedure_appointment(
            create_procedure_appointment_payload(
                order2["id"], ctx["room"]["id"],
                start_at="2026-08-01T09:45:00Z", end_at="2026-08-01T10:15:00Z",
            ),
            TECH1,
        )
        appt = validate_success(res, 201)
        assert_procedure_appointment(appt)
        assert appt["status"] == "BOOKED"


class TestRoomPostureBeatsOverlap:
    """Both violations present: booking targets a CONTAMINATED room and also
    overlaps an existing buffered booking. The pipeline of PRD §2.9 ranks room
    contamination (safety family) ahead of appointment overlap (temporal
    family)."""

    def test_contaminated_room_reports_room_error(self, api):
        """PRD §2.9: "When several rules guard the same call, evaluation proceeds
        in this global precedence order: ... then the safety family in rank
        order — ... room contamination (`ERR_ROOM_CONTAMINATED`), ... then the
        temporal family — ... appointment overlap (`ERR_APPOINTMENT_OVERLAP`),
        ..." and PRD §3.6: "Every `BOOKED` appointment in that room whose
        `end_at` is later than the spill's `occurred_at` transitions to
        `AUTO_VOIDED`..." — the 07:00-07:30 booking ended before the 08:00
        spill and therefore stays BOOKED.

        Design: Difficulty/priority_pair_validation_conflict/room_safety_beats_overlap_temporal
        """
        ctx = setup_f18_order()
        order2 = _two_orders(ctx)
        appt1 = book_appointment(
            ctx["order"]["id"], ctx["room"]["id"],
            start_at="2026-08-01T07:00:00Z", end_at="2026-08-01T07:30:00Z",
        )
        # Spill at 08:00 contaminates the room; A1 (end 07:30) is not voided.
        report_spill(
            ctx["room"]["id"], ctx["isotope"]["id"],
            reporter_headers=TECH1, occurred_at="2026-08-01T08:00:00Z",
        )
        assert get_room(ctx["room"]["id"])["status"] == "CONTAMINATED"
        assert get_appointment(appt1["id"])["status"] == "BOOKED"

        # 07:15-07:45 also overlaps A1's buffered occupation [07:00, 07:45).
        res = api.create_procedure_appointment(
            create_procedure_appointment_payload(
                order2["id"], ctx["room"]["id"],
                start_at="2026-08-01T07:15:00Z", end_at="2026-08-01T07:45:00Z",
            ),
            TECH1,
        )
        validate_error(res, "ERR_ROOM_CONTAMINATED", expected_status=409)
        assert get_appointment(appt1["id"])["status"] == "BOOKED"

    def test_overlap_alone_reports_overlap_error(self, api):
        """PRD §3.5: "A conflicting booking is rejected with
        `ERR_APPOINTMENT_OVERLAP` (HTTP 409)." With the room OPERATIONAL the
        safety check passes and the temporal rule reports — the control leg of
        the precedence pair.

        Design: Difficulty/priority_pair_validation_conflict/room_safety_beats_overlap_temporal
        """
        ctx = setup_f18_order()
        order2 = _two_orders(ctx)
        book_appointment(
            ctx["order"]["id"], ctx["room"]["id"],
            start_at="2026-08-01T07:00:00Z", end_at="2026-08-01T07:30:00Z",
        )
        res = api.create_procedure_appointment(
            create_procedure_appointment_payload(
                order2["id"], ctx["room"]["id"],
                start_at="2026-08-01T07:15:00Z", end_at="2026-08-01T07:45:00Z",
            ),
            TECH1,
        )
        validate_error(res, "ERR_APPOINTMENT_OVERLAP", expected_status=409)


class TestAdministrationBubbleUp:
    def test_administration_completes_appointment_and_order(self, api):
        """PRD §3.5: "The vial moves from `CALIBRATED` to `ADMINISTERED`, the
        order moves from `DOSE_PREPARED` to `ADMINISTERED`, and the completion
        bubbles up: the order's `BOOKED` appointment whose half-open interval
        contains the administration instant becomes `COMPLETED`."

        Administration at 10:20 falls inside the 10:00-10:30 booking.

        Design: Corner/state_machines/appointment_completes_on_administration_bubble_up
        """
        ctx = setup_f18_administered(with_appointment=True)
        appt = get_appointment(ctx["appointment"]["id"])
        assert appt["status"] == "COMPLETED"
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "ADMINISTERED"
