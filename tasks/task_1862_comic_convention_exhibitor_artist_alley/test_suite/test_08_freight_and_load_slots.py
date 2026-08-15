"""Freight bookings: phase gates, placement gate, dock-door buffer, slot
capacity sharing, slot OPEN/FULL cycling, and run-ops freight sweeps."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_phase,
    confirm_freight_booking,
    create_freight_booking,
    create_load_slot,
    find_dock_door,
    get_application,
    get_load_slot,
    make_exhibitor_headers,
    release_placement,
    run_ops,
    set_clock,
    setup_contracted_application,
    setup_freight_ready,
    setup_placed_application,
    validate_error,
    validate_paginated,
    validate_success,
)

SLOT_WINDOW = {
    "starts_at": "2026-10-14T08:00:00Z",
    "ends_at": "2026-10-14T12:00:00Z",
}


class TestFreightPhaseAndPlacementGates:
    def test_freight_booking_requires_placed_application(self, api):
        """PRD §3.8: "The application must be `PLACED`
        (`ERR_APPLICATION_NOT_PLACED`)."

        Design: Difficulty/cross_entity_state_dependency/freight_booking_requires_application_placed
        """
        # CONTRACTED but never PLACED: the only placement is released.
        bundle = setup_contracted_application(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
        )
        release_placement(bundle["placement"]["id"])
        conv_id = bundle["convention"]["id"]
        advance_phase(conv_id)  # PLACEMENT -> LOGISTICS (no TENTATIVE left)
        slot = create_load_slot(conv_id, pallet_capacity=10)
        door = find_dock_door(conv_id, "D1")
        assert get_application(bundle["application"]["id"])["status"] == "CONTRACTED"

        resp = api.create_freight_booking(
            {
                "application_id": bundle["application"]["id"],
                "load_slot_id": slot["id"],
                "dock_door_id": door["id"],
                "door_starts_at": "2026-10-14T08:00:00Z",
                "door_ends_at": "2026-10-14T09:00:00Z",
                "pallet_count": 2,
            },
            make_exhibitor_headers(bundle["exhibitor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_PLACED)

    def test_rejected_freight_booking_creates_no_record(self, api, director_headers):
        """PRD §3.8: "The application must be `PLACED`
        (`ERR_APPLICATION_NOT_PLACED`)."
        PRD §3.8: "The `reserved_pallets` counter sums the `pallet_count` of the
        slot's bookings in `REQUESTED`, `CONFIRMED`, or `CHECKED_IN` status
        only."

        Design: Difficulty/cross_entity_state_dependency/freight_booking_requires_application_placed
        """
        bundle = setup_contracted_application(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
        )
        release_placement(bundle["placement"]["id"])
        conv_id = bundle["convention"]["id"]
        advance_phase(conv_id)
        slot = create_load_slot(conv_id, pallet_capacity=10)
        door = find_dock_door(conv_id, "D1")

        resp = api.create_freight_booking(
            {
                "application_id": bundle["application"]["id"],
                "load_slot_id": slot["id"],
                "dock_door_id": door["id"],
                "door_starts_at": "2026-10-14T08:00:00Z",
                "door_ends_at": "2026-10-14T09:00:00Z",
                "pallet_count": 2,
            },
            make_exhibitor_headers(bundle["exhibitor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_PLACED)
        bookings, meta = validate_paginated(
            api.list_freight_bookings(
                director_headers,
                params={"application_id": bundle["application"]["id"]},
            )
        )
        assert meta["total_count"] == 0
        assert get_load_slot(slot["id"])["reserved_pallets"] == 0

    def test_freight_inbound_wrong_phase_rejected(self, api):
        """PRD §3.8: "The phase gate follows: `INBOUND` slots accept bookings
        only during `LOGISTICS`, `OUTBOUND` slots only during `LOAD_OUT`
        (`ERR_FREIGHT_WRONG_PHASE`)."

        Design: Corner/validations/freight_inbound_wrong_phase_rejected
        """
        # PLACED application but convention still in PLACEMENT (not LOGISTICS).
        bundle = setup_placed_application(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[{"door_code": "D1"}],
        )
        conv_id = bundle["convention"]["id"]
        assert bundle["convention"]["phase"] == "PLACEMENT"
        slot = create_load_slot(conv_id, pallet_capacity=10)
        door = find_dock_door(conv_id, "D1")
        resp = api.create_freight_booking(
            {
                "application_id": bundle["application"]["id"],
                "load_slot_id": slot["id"],
                "dock_door_id": door["id"],
                "door_starts_at": "2026-10-14T08:00:00Z",
                "door_ends_at": "2026-10-14T09:00:00Z",
                "pallet_count": 2,
            },
            make_exhibitor_headers(bundle["exhibitor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FREIGHT_WRONG_PHASE)


class TestDockDoorBuffer:
    def test_dock_door_overlap_inside_buffer_rejected(self, api):
        """PRD §3.8: "A new window conflicts with an existing booking of the
        same door whenever the new `door_starts_at` falls before the existing
        window's end plus fifteen minutes and the existing window's start falls
        before the new `door_ends_at` plus fifteen minutes; a conflict is
        rejected with `ERR_DOOR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/dock_door_exclusive_buffer_overlap
        """
        bundle = setup_freight_ready()
        slot_id = bundle["load_slot"]["id"]
        door_id = bundle["doors"]["D1"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        app_id = bundle["application"]["id"]
        # Existing occupation: [08:00, 09:00) on D1.
        create_freight_booking(
            app_id,
            ex_id,
            slot_id,
            door_id,
            door_starts_at="2026-10-14T08:00:00Z",
            door_ends_at="2026-10-14T09:00:00Z",
            pallet_count=1,
        )
        # 09:14 < 09:00 + 15 minutes -> inside the buffer.
        resp = api.create_freight_booking(
            {
                "application_id": app_id,
                "load_slot_id": slot_id,
                "dock_door_id": door_id,
                "door_starts_at": "2026-10-14T09:14:00Z",
                "door_ends_at": "2026-10-14T10:00:00Z",
                "pallet_count": 1,
            },
            make_exhibitor_headers(ex_id),
        )
        validate_error(resp, ApiErrorId.ERR_DOOR_WINDOW_CONFLICT)

    def test_dock_door_window_at_exact_buffer_end_accepted(self, api):
        """PRD §3.8: "Because the inequality is strict, a new window beginning
        exactly at the existing window's end plus fifteen minutes is accepted."

        Design: Difficulty/resource_temporal_overlap/dock_door_exclusive_buffer_overlap
        """
        bundle = setup_freight_ready()
        slot_id = bundle["load_slot"]["id"]
        door_id = bundle["doors"]["D1"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        app_id = bundle["application"]["id"]
        create_freight_booking(
            app_id,
            ex_id,
            slot_id,
            door_id,
            door_starts_at="2026-10-14T08:00:00Z",
            door_ends_at="2026-10-14T09:00:00Z",
            pallet_count=1,
        )
        # 09:15 == 09:00 + 15 minutes -> accepted under strict inequality.
        booking = create_freight_booking(
            app_id,
            ex_id,
            slot_id,
            door_id,
            door_starts_at="2026-10-14T09:15:00Z",
            door_ends_at="2026-10-14T10:00:00Z",
            pallet_count=1,
        )
        assert booking["status"] == "REQUESTED"
        assert get_load_slot(slot_id)["reserved_pallets"] == 2


class TestSlotCapacitySharing:
    def test_overlapping_windows_share_slot_until_full(self, api):
        """PRD §3.8: "The `reserved_pallets` counter sums the `pallet_count` of
        the slot's bookings in `REQUESTED`, `CONFIRMED`, or `CHECKED_IN` status
        only. When a booking pushes the counter to exactly `pallet_capacity` the
        slot turns `FULL`; when a cancellation or completion later drops it
        below capacity the slot returns to `OPEN`"

        Design: Difficulty/resource_temporal_overlap/load_slot_aggregate_capacity_sharing
        """
        bundle = setup_freight_ready(slot_overrides={"pallet_capacity": 6})
        slot_id = bundle["load_slot"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        app_id = bundle["application"]["id"]
        door1 = bundle["doors"]["D1"]["id"]
        door2 = bundle["doors"]["D2"]["id"]
        # Three overlapping-but-legal bookings on alternating doors, 2 pallets
        # each: aggregate sharing applies, not mutual exclusion.
        create_freight_booking(
            app_id, ex_id, slot_id, door1,
            door_starts_at="2026-10-14T08:00:00Z",
            door_ends_at="2026-10-14T08:30:00Z", pallet_count=2,
        )
        create_freight_booking(
            app_id, ex_id, slot_id, door2,
            door_starts_at="2026-10-14T08:00:00Z",
            door_ends_at="2026-10-14T08:30:00Z", pallet_count=2,
        )
        create_freight_booking(
            app_id, ex_id, slot_id, door1,
            door_starts_at="2026-10-14T09:00:00Z",
            door_ends_at="2026-10-14T09:30:00Z", pallet_count=2,
        )
        slot = get_load_slot(slot_id)
        assert slot["reserved_pallets"] == 6
        assert slot["status"] == "FULL"  # equality means full, inclusive

    def test_pallet_over_capacity_rejected(self, api):
        """PRD §3.8: "Only then is capacity checked: the slot's
        `reserved_pallets` plus the new `pallet_count` may not exceed
        `pallet_capacity` (`ERR_SLOT_CAPACITY_EXCEEDED`)."

        Design: Difficulty/resource_temporal_overlap/load_slot_aggregate_capacity_sharing
        """
        # Capacity 7: after 2+2+2 the slot holds 6 and stays OPEN (6 < 7), so
        # the not-OPEN state gate does not fire; the 2-pallet booking that
        # would push the sum to 8 > 7 isolates the capacity gate.
        bundle = setup_freight_ready(slot_overrides={"pallet_capacity": 7})
        slot_id = bundle["load_slot"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        app_id = bundle["application"]["id"]
        door1 = bundle["doors"]["D1"]["id"]
        door2 = bundle["doors"]["D2"]["id"]
        create_freight_booking(
            app_id, ex_id, slot_id, door1,
            door_starts_at="2026-10-14T08:00:00Z",
            door_ends_at="2026-10-14T08:30:00Z", pallet_count=2,
        )
        create_freight_booking(
            app_id, ex_id, slot_id, door2,
            door_starts_at="2026-10-14T08:00:00Z",
            door_ends_at="2026-10-14T08:30:00Z", pallet_count=2,
        )
        create_freight_booking(
            app_id, ex_id, slot_id, door1,
            door_starts_at="2026-10-14T09:00:00Z",
            door_ends_at="2026-10-14T09:30:00Z", pallet_count=2,
        )
        assert get_load_slot(slot_id)["status"] == "OPEN"
        # reserved 6 + 2 = 8 > capacity 7: one pallet over the remaining room.
        resp = api.create_freight_booking(
            {
                "application_id": app_id,
                "load_slot_id": slot_id,
                "dock_door_id": door2,
                "door_starts_at": "2026-10-14T09:00:00Z",
                "door_ends_at": "2026-10-14T09:30:00Z",
                "pallet_count": 2,
            },
            make_exhibitor_headers(ex_id),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)
        assert get_load_slot(slot_id)["reserved_pallets"] == 6


class TestSlotFullOpenCycle:
    def test_slot_turns_full_at_exact_capacity(self, api):
        """PRD §3.8: "When a booking pushes the counter to exactly
        `pallet_capacity` the slot turns `FULL`; when a cancellation or
        completion later drops it below capacity the slot returns to `OPEN`"

        Design: Difficulty/non_linear_state_machine/load_slot_open_full_open_cycle
        """
        bundle = setup_freight_ready(slot_overrides={"pallet_capacity": 2})
        booking = create_freight_booking(
            bundle["application"]["id"],
            bundle["exhibitor"]["id"],
            bundle["load_slot"]["id"],
            bundle["doors"]["D1"]["id"],
            pallet_count=2,
        )
        assert booking["status"] == "REQUESTED"
        slot = get_load_slot(bundle["load_slot"]["id"])
        assert slot["reserved_pallets"] == 2
        assert slot["status"] == "FULL"  # automatic OPEN -> FULL at equality

    def test_slot_reopens_after_cancellation(self, api):
        """PRD §3.8: "The exhibitor, operations, or the director may cancel a
        booking still in `REQUESTED` or `CONFIRMED`; cancellation releases its
        pallets, dropping the slot's `reserved_pallets` by the booking's
        `pallet_count` and returning a `FULL` slot to `OPEN` when the count
        falls below capacity."

        Design: Difficulty/non_linear_state_machine/load_slot_open_full_open_cycle
        """
        bundle = setup_freight_ready(slot_overrides={"pallet_capacity": 2})
        ex_id = bundle["exhibitor"]["id"]
        booking = create_freight_booking(
            bundle["application"]["id"],
            ex_id,
            bundle["load_slot"]["id"],
            bundle["doors"]["D1"]["id"],
            pallet_count=2,
        )
        assert get_load_slot(bundle["load_slot"]["id"])["status"] == "FULL"

        cancelled = validate_success(
            api.cancel_freight_booking(booking["id"], make_exhibitor_headers(ex_id))
        )
        assert cancelled["status"] == "CANCELLED"
        slot = get_load_slot(bundle["load_slot"]["id"])
        assert slot["status"] == "OPEN"  # automatic FULL -> OPEN
        assert slot["reserved_pallets"] == 0


class TestPalletConservation:
    def test_pallet_reservation_tracks_active_bookings(self, api):
        """PRD §3.8: "The `reserved_pallets` counter sums the `pallet_count` of
        the slot's bookings in `REQUESTED`, `CONFIRMED`, or `CHECKED_IN` status
        only."

        Design: Difficulty/compensating_invariant/pallet_reservation_conservation_under_confirm_cancel
        """
        bundle = setup_freight_ready()
        slot_id = bundle["load_slot"]["id"]
        assert bundle["load_slot"]["reserved_pallets"] == 0
        create_freight_booking(
            bundle["application"]["id"],
            bundle["exhibitor"]["id"],
            slot_id,
            bundle["doors"]["D1"]["id"],
            pallet_count=3,
        )
        # REQUESTED already consumes capacity.
        assert get_load_slot(slot_id)["reserved_pallets"] == 3

    def test_cancel_returns_slot_to_prior_reservation(self, api):
        """PRD §3.8: "The exhibitor, operations, or the director may cancel a
        booking still in `REQUESTED` or `CONFIRMED`; cancellation releases its
        pallets, dropping the slot's `reserved_pallets` by the booking's
        `pallet_count` and returning a `FULL` slot to `OPEN` when the count
        falls below capacity."

        Design: Difficulty/compensating_invariant/pallet_reservation_conservation_under_confirm_cancel
        """
        bundle = setup_freight_ready()
        slot_id = bundle["load_slot"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        booking = create_freight_booking(
            bundle["application"]["id"],
            ex_id,
            slot_id,
            bundle["doors"]["D1"]["id"],
            pallet_count=3,
        )
        assert get_load_slot(slot_id)["reserved_pallets"] == 3
        cancelled = validate_success(
            api.cancel_freight_booking(booking["id"], make_exhibitor_headers(ex_id))
        )
        assert cancelled["status"] == "CANCELLED"
        slot = get_load_slot(slot_id)
        # Forward (book 3) + compensate (cancel) nets to exactly zero drift.
        assert slot["reserved_pallets"] == 0
        assert slot["status"] == "OPEN"


class TestDoorWindowContainment:
    def test_freight_door_window_outside_slot_rejected(self, api):
        """PRD §3.8: "The door window must lie inside the slot window —
        `door_starts_at` no earlier than the slot's `starts_at` and
        `door_ends_at` no later than the slot's `ends_at`
        (`ERR_DOOR_WINDOW_OUTSIDE_SLOT`) — and must not collide with another
        active booking of the same door under the buffer rule."

        Design: Corner/validations/freight_door_window_outside_slot_rejected
        """
        bundle = setup_freight_ready()
        resp = api.create_freight_booking(
            {
                "application_id": bundle["application"]["id"],
                "load_slot_id": bundle["load_slot"]["id"],
                "dock_door_id": bundle["doors"]["D1"]["id"],
                # [11:00, 13:00) exceeds the slot's 12:00 close.
                "door_starts_at": "2026-10-14T11:00:00Z",
                "door_ends_at": "2026-10-14T13:00:00Z",
                "pallet_count": 2,
            },
            make_exhibitor_headers(bundle["exhibitor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOOR_WINDOW_OUTSIDE_SLOT)
        assert get_load_slot(bundle["load_slot"]["id"])["reserved_pallets"] == 0


class TestCheckInAndSweeps:
    def test_freight_check_in_outside_slot_window_rejected(self, api, ops_headers):
        """PRD §3.8: "Check-in is the operations desk's alone and moves
        `CONFIRMED` → `CHECKED_IN` only while the clock is at or after the
        slot's `starts_at` and strictly before its `ends_at`
        (`ERR_INVALID_TIME_WINDOW`)."

        Design: Corner/validations/freight_check_in_outside_slot_window_rejected
        """
        bundle = setup_freight_ready()
        booking = create_freight_booking(
            bundle["application"]["id"],
            bundle["exhibitor"]["id"],
            bundle["load_slot"]["id"],
            bundle["doors"]["D1"]["id"],
            pallet_count=2,
        )
        confirm_freight_booking(booking["id"])
        set_clock("2026-10-14T07:00:00Z")  # one hour before the slot opens
        resp = api.check_in_freight_booking(booking["id"], ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)
        current = validate_success(
            api.get_freight_booking(booking["id"], TEST_USERS["director_headers"])
        )
        assert current["status"] == "CONFIRMED"

    def test_freight_no_show_and_slot_close_via_run_ops(self, api, director_headers):
        """PRD §3.8: "a `CONFIRMED` booking whose slot's `ends_at` has passed
        without check-in becomes `NO_SHOW` and releases nothing — the no-show
        held its capacity to the end — while a `CHECKED_IN` booking past its
        slot's end becomes `COMPLETED` and releases its pallets in the usual
        way."
        PRD §3.8: "the run-ops slot sweep moves any `OPEN` or `FULL` slot whose
        `ends_at` has passed to `CLOSED`, which is terminal."

        Design: Corner/state_machines/freight_no_show_and_slot_close_via_run_ops
        """
        bundle = setup_freight_ready()
        booking = create_freight_booking(
            bundle["application"]["id"],
            bundle["exhibitor"]["id"],
            bundle["load_slot"]["id"],
            bundle["doors"]["D1"]["id"],
            pallet_count=3,
        )
        confirm_freight_booking(booking["id"])
        set_clock("2026-10-15T00:00:00Z")  # slot ended 2026-10-14T12:00:00Z
        run_ops(bundle["convention"]["id"])

        current = validate_success(
            api.get_freight_booking(booking["id"], director_headers)
        )
        assert current["status"] == "NO_SHOW"
        slot = get_load_slot(bundle["load_slot"]["id"])
        assert slot["status"] == "CLOSED"
        assert slot["reserved_pallets"] == 3  # the no-show kept its capacity
