"""Blast-freeze cells and bookings: window conflicts, capacity, selector, fees."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cancel_booking,
    complete_booking,
    confirm_excursion,
    create_booking,
    create_booking_payload,
    create_cell,
    create_customer_with_card,
    create_zone,
    get_booking,
    get_open_invoice,
    list_cell_bookings,
    list_lot_pallets,
    receive_stock,
    release_quarantine,
    report_excursion,
    set_clock,
    setup_stocked_account,
    start_booking,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["warehouse_operator_headers"]


class TestTurnaroundBuffer:
    def _setup_cell_with_booking(self):
        sc = setup_stocked_account(customer_name="Blast Co", zone_code="FZ-20",
                                   pallets=4)
        cell = create_cell("BC-2", capacity_pallets=5, turnaround_minutes=30)
        booking1 = create_booking(cell["id"], sc["lot_id"], pallet_count=2,
                                  window_start="2026-08-10T10:00:00Z",
                                  window_end="2026-08-10T12:00:00Z")
        return sc, cell, booking1

    def test_gap_shorter_than_turnaround_conflicts(self, api):
        """PRD §3.4: "a conflict exists whenever an existing booking on the same
        cell standing at `SCHEDULED` or `IN_PROGRESS` is positioned such that the
        new window's start falls before the existing window's end extended by the
        cell's `turnaround_minutes`, and the existing window's start falls before
        the new window's end extended by that same buffer; any such collision is
        rejected `ERR_BOOKING_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/blast_cell_turnaround_buffer_semantics
        """
        sc, cell, _booking1 = self._setup_cell_with_booking()
        # 12:15 < 12:00 + 30min turnaround -> conflict despite zero overlap.
        resp = api.create_blast_freeze_booking(
            create_booking_payload(cell["id"], sc["lot_id"], pallet_count=1,
                                   window_start="2026-08-10T12:15:00Z",
                                   window_end="2026-08-10T13:00:00Z"),
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_BOOKING_WINDOW_CONFLICT,
                       expected_status=409)

    def test_gap_equal_to_turnaround_is_allowed(self, api):
        """PRD §3.4: "The practical reading is that the gap between two bookings
        on one cell must be at least the cell's turnaround, so when the
        turnaround is positive even back-to-back adjacency conflicts."

        Design: Difficulty/resource_temporal_overlap/blast_cell_turnaround_buffer_semantics
        """
        sc, cell, _booking1 = self._setup_cell_with_booking()
        # 12:30 == 12:00 + 30min: "start falls before end + turnaround" is false.
        booking = validate_success(
            api.create_blast_freeze_booking(
                create_booking_payload(cell["id"], sc["lot_id"], pallet_count=1,
                                       window_start="2026-08-10T12:30:00Z",
                                       window_end="2026-08-10T13:30:00Z"),
                OPERATOR),
            expected_status=201)
        assert booking["status"] == "SCHEDULED"


class TestCancelledBookingCandidateSet:
    def _setup_cancelled_booking(self):
        sc = setup_stocked_account(customer_name="Cancel Co", zone_code="FZ-22",
                                   pallets=4)
        cell = create_cell("BC-3", capacity_pallets=5, turnaround_minutes=30)
        booking1 = create_booking(cell["id"], sc["lot_id"], pallet_count=2,
                                  window_start="2026-08-10T10:00:00Z",
                                  window_end="2026-08-10T12:00:00Z")
        cancel_booking(booking1["id"])
        return sc, cell, booking1

    def test_identical_window_rebookable_after_cancel(self, api):
        """PRD §3.4: "A booking still at `SCHEDULED` may instead be cancelled,
        moving it to `CANCELLED` and freeing its window: a cancelled booking no
        longer participates in the overlap check, whose candidate set is exactly
        the bookings at `SCHEDULED` or `IN_PROGRESS`."

        Design: Difficulty/resource_temporal_overlap/cancelled_booking_excluded_from_overlap_candidate_set
        """
        sc, cell, _booking1 = self._setup_cancelled_booking()
        booking2 = validate_success(
            api.create_blast_freeze_booking(
                create_booking_payload(cell["id"], sc["lot_id"], pallet_count=2,
                                       window_start="2026-08-10T10:00:00Z",
                                       window_end="2026-08-10T12:00:00Z"),
                OPERATOR),
            expected_status=201)
        assert booking2["status"] == "SCHEDULED"

    def test_cancelled_booking_excluded_from_active_listing(self, api):
        """PRD §3.4: "a cancelled booking no longer participates in the overlap
        check, whose candidate set is exactly the bookings at `SCHEDULED` or
        `IN_PROGRESS`."

        Design: Difficulty/resource_temporal_overlap/cancelled_booking_excluded_from_overlap_candidate_set
        """
        sc, cell, booking1 = self._setup_cancelled_booking()
        create_booking(cell["id"], sc["lot_id"], pallet_count=2,
                       window_start="2026-08-10T10:00:00Z",
                       window_end="2026-08-10T12:00:00Z")
        bookings = list_cell_bookings(cell["id"])
        by_status = {}
        for b in bookings:
            by_status.setdefault(b["status"], []).append(b["id"])
        assert len(by_status.get("CANCELLED", [])) == 1
        assert by_status["CANCELLED"][0] == booking1["id"]
        assert len(by_status.get("SCHEDULED", [])) == 1, (
            "exactly one SCHEDULED booking on the cell")


class TestBookingCancelConservation:
    def _setup_scenario(self):
        sc = setup_stocked_account(customer_name="Cal Co", zone_code="FZ-25",
                                   pallets=2)
        cell = create_cell("BC-4", capacity_pallets=5, turnaround_minutes=30)
        return sc, cell

    def test_cancel_frees_window_and_charges_nothing(self, api):
        """PRD §3.4: "A booking still at `SCHEDULED` may instead be cancelled,
        moving it to `CANCELLED` and freeing its window: a cancelled booking no
        longer participates in the overlap check, whose candidate set is exactly
        the bookings at `SCHEDULED` or `IN_PROGRESS`."
        PRD §3.4: "the booking's `customer_id` is denormalized from the lot, and
        its `fee_cents` stays null until completion."

        Design: Difficulty/compensating_invariant/booking_schedule_cancel_conserves_cell_calendar_and_fees
        """
        sc, cell = self._setup_scenario()
        booking1 = create_booking(cell["id"], sc["lot_id"], pallet_count=1,
                                  window_start="2026-08-10T10:00:00Z",
                                  window_end="2026-08-10T12:00:00Z")
        cancel_booking(booking1["id"])
        booking2 = validate_success(
            api.create_blast_freeze_booking(
                create_booking_payload(cell["id"], sc["lot_id"], pallet_count=1,
                                       window_start="2026-08-10T10:00:00Z",
                                       window_end="2026-08-10T12:00:00Z"),
                OPERATOR),
            expected_status=201)
        assert booking2["status"] == "SCHEDULED", "calendar time restored"
        invoice = get_open_invoice(sc["customer"]["id"])
        assert invoice["blast_freeze_cents"] == 0, "no fee without a completion"

    def test_cell_calendar_shows_one_cancelled_one_scheduled(self, api):
        """PRD §3.4: "A booking still at `SCHEDULED` may instead be cancelled,
        moving it to `CANCELLED` and freeing its window: a cancelled booking no
        longer participates in the overlap check, whose candidate set is exactly
        the bookings at `SCHEDULED` or `IN_PROGRESS`."
        PRD §2.3: "Unless otherwise specified, all list endpoints return resources
        sorted by their creation timestamp in ascending order."

        Design: Difficulty/compensating_invariant/booking_schedule_cancel_conserves_cell_calendar_and_fees
        """
        sc, cell = self._setup_scenario()
        booking1 = create_booking(cell["id"], sc["lot_id"], pallet_count=1,
                                  window_start="2026-08-10T10:00:00Z",
                                  window_end="2026-08-10T12:00:00Z")
        cancel_booking(booking1["id"])
        booking2 = create_booking(cell["id"], sc["lot_id"], pallet_count=1,
                                  window_start="2026-08-10T10:00:00Z",
                                  window_end="2026-08-10T12:00:00Z")
        bookings = list_cell_bookings(cell["id"])
        assert [b["id"] for b in bookings] == [booking1["id"], booking2["id"]]
        assert bookings[0]["status"] == "CANCELLED"
        assert bookings[1]["status"] == "SCHEDULED"


class TestBookingStartWindow:
    def test_start_outside_window_rejected_then_inside_accepted(self, api):
        """PRD §3.4: "The logical clock must read within the booking window,
        inclusive of both `window_start` and `window_end`; a start attempted
        outside is rejected `ERR_OUTSIDE_WINDOW`."

        Design: Corner/validations/booking_start_outside_window_rejected
        """
        sc = setup_stocked_account(customer_name="Win Co", zone_code="FZ-WN",
                                   pallets=2)
        cell = create_cell("BC-WN", capacity_pallets=5, turnaround_minutes=30)
        booking = create_booking(cell["id"], sc["lot_id"], pallet_count=1,
                                 window_start="2026-08-10T10:00:00Z",
                                 window_end="2026-08-10T12:00:00Z")
        set_clock("2026-08-10T09:00:00Z")
        early = api.start_blast_freeze_booking(booking["id"], OPERATOR)
        validate_error(early, ApiErrorId.ERR_OUTSIDE_WINDOW, expected_status=409)
        assert get_booking(booking["id"])["status"] == "SCHEDULED"

        set_clock("2026-08-10T10:00:00Z")
        started = validate_success(
            api.start_blast_freeze_booking(booking["id"], OPERATOR))
        assert started["status"] == "IN_PROGRESS", (
            "window_start itself is inside the window (inclusive boundary)")


class TestInsufficientFreezableStock:
    def test_start_with_too_few_ok_pallets_rejected(self, api):
        """PRD §3.4: "The pallet selector then draws from the booking's lot the
        pallets standing at `STORED` with quality `OK`, ordered by `received_at`
        ascending with ties broken by `created_at` ascending, taking
        `pallet_count` of them; if fewer qualify, the start fails with
        `ERR_INSUFFICIENT_FREEZABLE_STOCK`."

        Design: Corner/validations/insufficient_freezable_stock_at_booking_start
        """
        sc = setup_stocked_account(customer_name="Ins Co", zone_code="FZ-IS",
                                   pallets=2)
        # Quarantine both, then release one: exactly 1 of 2 lot pallets eligible.
        excursion = report_excursion(sc["zone"]["id"], observed_temp_c=-2.0,
                                     window_start="2026-08-02T12:00:00Z",
                                     window_end="2026-08-02T13:00:00Z")
        confirm_excursion(excursion["id"])
        pallets = list_lot_pallets(sc["lot_id"])
        release_quarantine(pallets[0]["id"])
        cell = create_cell("BC-IS", capacity_pallets=5, turnaround_minutes=30)
        booking = create_booking(cell["id"], sc["lot_id"], pallet_count=2,
                                 window_start="2026-08-05T10:00:00Z",
                                 window_end="2026-08-05T12:00:00Z")
        set_clock("2026-08-05T10:30:00Z")
        resp = api.start_blast_freeze_booking(booking["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FREEZABLE_STOCK,
                       expected_status=409)
        assert get_booking(booking["id"])["status"] == "SCHEDULED"


class TestCellCapacity:
    def test_pallet_count_above_capacity_rejected_boundary_inclusive(self, api):
        """PRD §3.4: "The requested `pallet_count` must not exceed the cell's
        `capacity_pallets`, else `ERR_CELL_CAPACITY_EXCEEDED`."

        Design: Corner/validations/cell_capacity_exceeded_on_booking_create
        """
        sc = setup_stocked_account(customer_name="Cell Co", zone_code="FZ-CE",
                                   capacity_pallets=5, pallets=4)
        cell = create_cell("BC-CE", capacity_pallets=3, turnaround_minutes=30)
        over = api.create_blast_freeze_booking(
            create_booking_payload(cell["id"], sc["lot_id"], pallet_count=4),
            OPERATOR)
        validate_error(over, ApiErrorId.ERR_CELL_CAPACITY_EXCEEDED,
                       expected_status=409)
        at_capacity = validate_success(
            api.create_blast_freeze_booking(
                create_booking_payload(cell["id"], sc["lot_id"], pallet_count=3),
                OPERATOR),
            expected_status=201)
        assert at_capacity["status"] == "SCHEDULED", (
            "pallet_count == capacity is allowed (boundary inclusive)")


class TestBlastFee:
    def test_fee_constants_applied_at_completion(self, api):
        """PRD §3.4: "The booking's `fee_cents` is fixed at completion as the
        card's `blast_base_cents` plus the booking's `pallet_count` multiplied by
        the card's `blast_per_pallet_cents`, and that fee accrues immediately into
        the customer's `OPEN` invoice under `blast_freeze_cents`."

        Design: Corner/calculations/blast_fee_constants_applied
        """
        sc = setup_stocked_account(customer_name="Fee Co", zone_code="FZ-FE",
                                   capacity_pallets=5, pallets=2)
        cell = create_cell("BC-FE", capacity_pallets=5, turnaround_minutes=30)
        booking = create_booking(cell["id"], sc["lot_id"], pallet_count=2,
                                 window_start="2026-08-05T10:00:00Z",
                                 window_end="2026-08-05T12:00:00Z")
        set_clock("2026-08-05T10:30:00Z")
        start_booking(booking["id"])
        completed = complete_booking(booking["id"])
        # Standard card: 2000 base + 2 * 300 per pallet.
        assert completed["fee_cents"] == 2600, (
            f"2000 + 2*300 == 2600, got {completed['fee_cents']}")
        invoice = get_open_invoice(sc["customer"]["id"])
        assert invoice["blast_freeze_cents"] == 2600, (
            "the fee accrues immediately onto the OPEN invoice")
