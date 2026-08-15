"""Hangar bay / slot scheduling: half-open intervals, credit gate (PRD §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_program,
    book_slot,
    create_bay,
    create_engagement,
    get_program,
    set_logical_clock,
    setup_booked_program,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_hangar_slot_payload

_PM = TEST_USERS["program_manager_headers"]
_ADMIN = TEST_USERS["center_admin_headers"]


class TestHalfOpenAdjacency:
    def test_adjacent_slot_start_equals_prior_end_allowed(self, api):
        """PRD §3.2: "Slot windows are half-open intervals: the start is
        inclusive, the end exclusive, so two slots on the same bay where one
        ends exactly when the other begins are legal adjacency."

        Design: Difficulty/resource_temporal_overlap/hangar_slot_half_open_adjacency
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        bay = create_bay()
        slot_a = book_slot(bay["id"], ctx["program"]["id"],
                           start_at="2026-08-01T00:00:00Z", end_at="2026-08-10T00:00:00Z")
        assert slot_a["status"] == "BOOKED"

        resp = api.create_hangar_slot(
            create_hangar_slot_payload(
                bay_id=bay["id"], program_id=ctx["program"]["id"],
                start_at="2026-08-10T00:00:00Z", end_at="2026-08-20T00:00:00Z",
            ),
            _PM,
        )
        slot_b = validate_success(resp, 201)
        assert slot_b["status"] == "BOOKED", "end == start is legal adjacency"

    def test_interior_overlap_rejected(self, api):
        """PRD §3.2: "A true overlap — any existing `BOOKED` or `ACTIVE` slot
        on the same bay whose interval intersects the new one under half-open
        semantics — is rejected with `ERR_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/hangar_slot_half_open_adjacency
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        bay = create_bay()
        book_slot(bay["id"], ctx["program"]["id"],
                  start_at="2026-08-01T00:00:00Z", end_at="2026-08-10T00:00:00Z")
        book_slot(bay["id"], ctx["program"]["id"],
                  start_at="2026-08-10T00:00:00Z", end_at="2026-08-20T00:00:00Z")

        resp = api.create_hangar_slot(
            create_hangar_slot_payload(
                bay_id=bay["id"], program_id=ctx["program"]["id"],
                start_at="2026-08-09T00:00:00Z", end_at="2026-08-11T00:00:00Z",
            ),
            _PM,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP)


class TestBookCancelConservation:
    def test_book_then_cancel_restores_bay_availability(self, api):
        """PRD §2.7: "First, book-then-cancel on a hangar slot leaves the bay's
        occupancy set exactly as it was — cancel restores availability rather
        than degrading it."

        Design: Difficulty/compensating_invariant/bay_occupancy_book_cancel_conservation
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        bay = create_bay()
        slot1 = book_slot(bay["id"], ctx["program"]["id"],
                          start_at="2026-08-01T00:00:00Z", end_at="2026-08-10T00:00:00Z")

        cancelled = validate_success(api.cancel_hangar_slot(slot1["id"], _PM))
        assert cancelled["status"] == "CANCELLED"

        rebooked = api.create_hangar_slot(
            create_hangar_slot_payload(
                bay_id=bay["id"], program_id=ctx["program"]["id"],
                start_at="2026-08-01T00:00:00Z", end_at="2026-08-10T00:00:00Z",
            ),
            _PM,
        )
        slot2 = validate_success(rebooked, 201)
        assert slot2["status"] == "BOOKED", (
            "the identical window is free again; the cancelled slot no longer occupies"
        )

    def test_cancelled_slot_does_not_block_bay_deactivation(self, api):
        """PRD §3.2: "A bay may be deactivated — moved from `ACTIVE` to
        `INACTIVE` — but only when it holds no `BOOKED` or `ACTIVE` slots".
        Combined with PRD §2.7: "book-then-cancel on a hangar slot leaves the
        bay's occupancy set exactly as it was — cancel restores availability
        rather than degrading it."

        Design: Difficulty/compensating_invariant/bay_occupancy_book_cancel_conservation
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        bay = create_bay()
        slot1 = book_slot(bay["id"], ctx["program"]["id"],
                          start_at="2026-08-01T00:00:00Z", end_at="2026-08-10T00:00:00Z")
        validate_success(api.cancel_hangar_slot(slot1["id"], _PM))

        resp = api.deactivate_hangar_bay(bay["id"], _ADMIN)
        bay_after = validate_success(resp)
        assert bay_after["status"] == "INACTIVE", (
            "the cancelled slot is not BOOKED/ACTIVE, so deactivation succeeds"
        )


class TestSlotTemporalVsFiscal:
    def test_past_start_error_precedes_credit_hold(self, api):
        """PRD §2.10: "Incoming requests are validated in a fixed priority
        order, so that the error a caller receives is always the
        highest-priority failure present rather than an arbitrary one." —
        temporal rules (item 9, incl. `ERR_SLOT_IN_PAST`) precede fiscal rules
        (item 12, `ERR_CREDIT_HOLD`). PRD §3.2: "A slot whose `start_at` lies
        before the logical clock, or whose `start_at` is not strictly before
        its `end_at`, is rejected with `ERR_SLOT_IN_PAST`."

        Design: Difficulty/priority_pair_validation_conflict/slot_temporal_vs_fiscal_conflict
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        validate_success(
            api.set_customer_credit_status(
                ctx["customer"]["id"], {"credit_status": "CREDIT_HOLD"}, _ADMIN
            )
        )
        bay = create_bay()
        resp = api.create_hangar_slot(
            create_hangar_slot_payload(
                bay_id=bay["id"], program_id=ctx["program"]["id"],
                start_at="2026-07-01T00:00:00Z", end_at="2026-07-10T00:00:00Z",
            ),
            _PM,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_IN_PAST)

    def test_rejected_past_slot_creates_nothing(self, api):
        """PRD §2.7: "All mutations and their cascades are atomic within the
        request: the system never persists a partial application." PRD §3.2:
        "A slot whose `start_at` lies before the logical clock, or whose
        `start_at` is not strictly before its `end_at`, is rejected with
        `ERR_SLOT_IN_PAST`."

        Design: Difficulty/priority_pair_validation_conflict/slot_temporal_vs_fiscal_conflict
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        validate_success(
            api.set_customer_credit_status(
                ctx["customer"]["id"], {"credit_status": "CREDIT_HOLD"}, _ADMIN
            )
        )
        bay = create_bay()
        resp = api.create_hangar_slot(
            create_hangar_slot_payload(
                bay_id=bay["id"], program_id=ctx["program"]["id"],
                start_at="2026-07-01T00:00:00Z", end_at="2026-07-10T00:00:00Z",
            ),
            _PM,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_IN_PAST)
        slots, meta = validate_paginated(api.list_hangar_slots(_PM))
        assert meta["total_count"] == 0, "a rejected booking persists no slot"


class TestSlotLifecycle:
    def test_slot_booked_active_released_walk(self, api):
        """PRD §3.2: "A booked slot is activated once the logical clock falls
        inside its window and the program is `BOOKED` or `INDUCTED` ... An
        active slot is released when the aircraft physically vacates, and a
        still-booked slot may simply be cancelled."

        Design: Corner/state_machines/slot_lifecycle_valid_transitions
        """
        ctx = setup_booked_program()
        assert ctx["slot"]["status"] == "BOOKED", "slot begins BOOKED"

        activated = validate_success(api.activate_hangar_slot(ctx["slot"]["id"], _PM))
        assert activated["status"] == "ACTIVE"

        released = validate_success(api.release_hangar_slot(ctx["slot"]["id"], _PM))
        assert released["status"] == "RELEASED"


class TestBayDeactivation:
    def test_inactive_bay_rejects_new_slot(self, api):
        """PRD §3.2: "A bay may be deactivated — moved from `ACTIVE` to
        `INACTIVE` — but only when it holds no `BOOKED` or `ACTIVE` slots; an
        `INACTIVE` bay rejects new slot bookings, and both directions of this
        rule surface as `ERR_BAY_INACTIVE`."

        Design: Corner/errors/bay_inactive_rejects_new_slot
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        bay = create_bay()
        deactivated = validate_success(api.deactivate_hangar_bay(bay["id"], _ADMIN))
        assert deactivated["status"] == "INACTIVE"

        resp = api.create_hangar_slot(
            create_hangar_slot_payload(
                bay_id=bay["id"], program_id=ctx["program"]["id"],
                start_at="2026-08-02T00:00:00Z", end_at="2026-08-10T00:00:00Z",
            ),
            _PM,
        )
        validate_error(resp, ApiErrorId.ERR_BAY_INACTIVE)


class TestCreditHoldOnSlotBooking:
    def test_credit_hold_blocks_slot_booking(self, api):
        """PRD §3.1: "while a customer is on hold, three things are refused —
        booking a new hangar slot for one of their programs, advancing a
        program from `QUOTED` to `BOOKED`, and advancing a program from
        `SURFACE_REVIEW` to `IN_WORK` — each rejected with `ERR_CREDIT_HOLD`
        (HTTP 402)."

        Design: Corner/validations/credit_hold_blocks_slot_booking
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        validate_success(
            api.set_customer_credit_status(
                ctx["customer"]["id"], {"credit_status": "CREDIT_HOLD"}, _ADMIN
            )
        )
        bay = create_bay()
        resp = api.create_hangar_slot(
            create_hangar_slot_payload(
                bay_id=bay["id"], program_id=ctx["program"]["id"],
                start_at="2026-08-02T00:00:00Z", end_at="2026-08-10T00:00:00Z",
            ),
            _PM,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD)
