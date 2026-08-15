"""Paint booth bookings: dual-variant fees and cure-buffer geometry (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_booth_window,
    create_booth,
    create_engagement,
    get_program,
    set_logical_clock,
    setup_in_work_program,
    setup_surface_review_program,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_booth_booking_payload

_PM = TEST_USERS["program_manager_headers"]
_TECH = TEST_USERS["shop_technician_headers"]


class TestBoothFeeVariants:
    def test_scheduled_fee_computed_at_booking(self, api):
        """PRD §3.2: "At booking time, `scheduled_fee_cents` is computed as the
        scheduled hours — the whole-hour difference between `end_at` and
        `start_at` — multiplied by the booth's hourly rate."

        Design: Difficulty/dual_variant_calc/booth_fee_scheduled_vs_actual_diverge
        """
        ctx = setup_in_work_program()  # books 2026-08-10T08:00 -> 16:00 at 25,000/h
        booking = ctx["booking"]
        assert booking["status"] == "BOOKED"
        assert booking["scheduled_fee_cents"] == 8 * 25000 == 200000

    def test_actual_fee_bills_overrun_at_premium(self, api):
        """PRD §3.2: "if actual occupancy did not exceed the scheduled hours,
        the fee is simply the actual hours times the rate; otherwise the fee is
        the scheduled hours times the rate plus the overrun hours times the
        rate times a 1.25 premium multiplier, with the overrun term rounded
        half-up to integer cents."

        Design: Difficulty/dual_variant_calc/booth_fee_scheduled_vs_actual_diverge
        """
        ctx = setup_in_work_program()
        booking = ctx["booking"]
        resp = api.complete_booth_booking(booking["id"], {"actual_hours": 11}, _TECH)
        completed = validate_success(resp)
        assert completed["status"] == "COMPLETED"
        # 8 scheduled x 25000 + 3 overrun x 25000 x 1.25 = 200000 + 93750.
        assert completed["actual_fee_cents"] == 293750
        assert completed["scheduled_fee_cents"] == 200000
        assert completed["actual_fee_cents"] != completed["scheduled_fee_cents"], (
            "the lifecycle moment selects the variant"
        )


class TestCureBufferBoundary:
    def test_gap_exactly_equal_to_buffer_allowed(self, api):
        """PRD §3.2: "A gap exactly equal to the buffer is acceptable; anything
        less is not."

        Design: Difficulty/boundary_precision_check/booth_buffer_exact_gap_allowed
        """
        ctx = create_engagement()
        booth = create_booth()  # cure_buffer_hours 6
        book_booth_window(booth["id"], ctx["program"]["id"],
                          start_at="2026-08-10T08:00:00Z", end_at="2026-08-10T16:00:00Z")
        resp = api.create_booth_booking(
            create_booth_booking_payload(
                booth_id=booth["id"], program_id=ctx["program"]["id"],
                start_at="2026-08-10T22:00:00Z", end_at="2026-08-10T23:00:00Z",
            ),
            _PM,
        )
        booking_b = validate_success(resp, 201)
        assert booking_b["status"] == "BOOKED", "gap == 6h buffer is inclusive-allowed"

    def test_gap_one_hour_short_of_buffer_rejected(self, api):
        """PRD §3.2: "a new booking is rejected with `ERR_BOOTH_BUFFER_VIOLATION`
        unless, for every existing `BOOKED` or `COMPLETED` booking on that
        booth, the new booking starts at or after the existing booking's end
        plus the buffer ... A gap exactly equal to the buffer is acceptable;
        anything less is not."

        Design: Difficulty/boundary_precision_check/booth_buffer_exact_gap_allowed
        """
        ctx = create_engagement()
        booth = create_booth()
        book_booth_window(booth["id"], ctx["program"]["id"],
                          start_at="2026-08-10T08:00:00Z", end_at="2026-08-10T16:00:00Z")
        book_booth_window(booth["id"], ctx["program"]["id"],
                          start_at="2026-08-10T22:00:00Z", end_at="2026-08-10T23:00:00Z")
        resp = api.create_booth_booking(
            create_booth_booking_payload(
                booth_id=booth["id"], program_id=ctx["program"]["id"],
                start_at="2026-08-11T04:00:00Z", end_at="2026-08-11T05:00:00Z",
            ),
            _PM,
        )
        # 04:00 starts only 5h after the 23:00 end — one hour short of the 6h buffer.
        validate_error(resp, ApiErrorId.ERR_BOOTH_BUFFER_VIOLATION)


class TestBufferGapSemantics:
    def test_zero_gap_adjacency_rejected(self, api):
        """PRD §3.2: "a new booking is rejected with `ERR_BOOTH_BUFFER_VIOLATION`
        unless, for every existing `BOOKED` or `COMPLETED` booking on that
        booth, the new booking starts at or after the existing booking's end
        plus the buffer, or the new booking's end plus the buffer falls at or
        before the existing booking's start."

        Design: Difficulty/resource_temporal_overlap/booth_booking_buffer_gap_semantics
        """
        ctx = create_engagement()
        booth = create_booth()
        book_booth_window(booth["id"], ctx["program"]["id"],
                          start_at="2026-08-10T08:00:00Z", end_at="2026-08-10T16:00:00Z")
        resp = api.create_booth_booking(
            create_booth_booking_payload(
                booth_id=booth["id"], program_id=ctx["program"]["id"],
                start_at="2026-08-10T16:00:00Z", end_at="2026-08-10T20:00:00Z",
            ),
            _PM,
        )
        validate_error(resp, ApiErrorId.ERR_BOOTH_BUFFER_VIOLATION)

    def test_earlier_booking_also_needs_buffer(self, api):
        """PRD §3.2: "The buffer rule is symmetric: a new booking is rejected
        with `ERR_BOOTH_BUFFER_VIOLATION` unless, for every existing `BOOKED`
        or `COMPLETED` booking on that booth, the new booking starts at or
        after the existing booking's end plus the buffer, or the new booking's
        end plus the buffer falls at or before the existing booking's start."

        Design: Difficulty/resource_temporal_overlap/booth_booking_buffer_gap_semantics
        """
        ctx = create_engagement()
        booth = create_booth()
        book_booth_window(booth["id"], ctx["program"]["id"],
                          start_at="2026-08-10T08:00:00Z", end_at="2026-08-10T16:00:00Z")
        # Ends exactly 6h before the existing 08:00 start: 02:00 + 6h == 08:00.
        ok = api.create_booth_booking(
            create_booth_booking_payload(
                booth_id=booth["id"], program_id=ctx["program"]["id"],
                start_at="2026-08-10T01:00:00Z", end_at="2026-08-10T02:00:00Z",
            ),
            _PM,
        )
        assert validate_success(ok, 201)["status"] == "BOOKED"
        # Ends at 03:00: 03:00 + 6h = 09:00 > 08:00 — violates the buffer.
        bad = api.create_booth_booking(
            create_booth_booking_payload(
                booth_id=booth["id"], program_id=ctx["program"]["id"],
                start_at="2026-08-10T02:00:00Z", end_at="2026-08-10T03:00:00Z",
            ),
            _PM,
        )
        validate_error(bad, ApiErrorId.ERR_BOOTH_BUFFER_VIOLATION)


class TestBoothBookingGate:
    def test_in_work_advance_requires_booth_booking(self, api, program_manager_headers):
        """PRD §3.5: "From `SURFACE_REVIEW` to `IN_WORK`: four gates. ... at
        least one booth booking must be `BOOKED` (`ERR_BOOTH_BOOKING_REQUIRED`)".

        Design: Corner/errors/in_work_requires_booth_booking
        """
        ctx = setup_surface_review_program()  # assessment DECIDED, scheme APPROVED
        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "IN_WORK"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_BOOTH_BOOKING_REQUIRED)
