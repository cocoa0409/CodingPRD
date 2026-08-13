"""Shore-side operations: berth turnaround-buffer intervals and the aggregate
parking pool (PRD §3.2, §3.7)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_booking,
    create_customer,
    create_dock,
    create_dock_slot,
    create_paid_booking,
    create_parking_pass,
    setup_inventory,
    validate_error,
    validate_success,
)

OM = TEST_USERS["ops_manager_headers"]
ATTENDANT = TEST_USERS["dock_attendant_headers"]


class TestDockSlotTurnaroundBuffer:
    def test_buffer_adjacency_boundary(self, api):
        """PRD §3.2: "Two slots naming the same vessel — regardless of which
        docks they sit at — conflict whenever the first slot's start falls before
        the second slot's end plus a forty-five-minute turnaround buffer, and the
        second slot's start falls before the first slot's end plus the same
        buffer."
        PRD §3.2: "Adjacency exactly at the earlier slot's end plus forty-five
        minutes is permitted: the buffer is a gap requirement, not an occupancy
        extension. A creation that would violate this rule is rejected with
        `ERR_DOCK_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/dock_slot_turnaround_buffer_adjacency
        """
        inv = setup_inventory()
        dock_id = inv["dock"]["id"]
        vessel_id = inv["vessel"]["id"]
        create_dock_slot(dock_id, vessel_id, "2026-08-10T14:00:00Z",
                         "2026-08-10T16:00:00Z")

        # 16:44 is one minute inside the buffer (16:00 + 45min = 16:45).
        resp = api.create_dock_slot(
            dock_id,
            {"vessel_id": vessel_id, "slot_start": "2026-08-10T16:44:00Z",
             "slot_end": "2026-08-10T18:00:00Z"},
            OM)
        validate_error(resp, ApiErrorId.ERR_DOCK_SLOT_CONFLICT)

        # Exactly at the buffer boundary: permitted.
        ok = validate_success(api.create_dock_slot(
            dock_id,
            {"vessel_id": vessel_id, "slot_start": "2026-08-10T16:45:00Z",
             "slot_end": "2026-08-10T18:00:00Z"},
            OM), expected_status=201)
        # The stored start instant is the requested one (PRD pins the instant,
        # not the string rendering).
        start = datetime.fromisoformat(ok["slot_start"].replace("Z", "+00:00"))
        assert start == datetime(2026, 8, 10, 16, 45, tzinfo=timezone.utc)

    def test_temporal_conflict_fires_on_slot_creation(self, api):
        """PRD §3.2: "Two slots naming the same vessel — regardless of which
        docks they sit at — conflict whenever the first slot's start falls before
        the second slot's end plus a forty-five-minute turnaround buffer, and the
        second slot's start falls before the first slot's end plus the same
        buffer."
        PRD §3.2: "A creation that would violate this rule is rejected with
        `ERR_DOCK_SLOT_CONFLICT`."
        PRD §2.8: "8. Berth turnaround-buffer overlap for the same vessel —
        `ERR_DOCK_SLOT_CONFLICT` (409)."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_conflict
        """
        # A 16:30 start falls inside the 16:00+45min buffer: the temporal rule
        # fires on the creation itself.
        inv = setup_inventory()
        dock_id = inv["dock"]["id"]
        vessel_id = inv["vessel"]["id"]
        create_dock_slot(dock_id, vessel_id, "2026-08-10T14:00:00Z",
                         "2026-08-10T16:00:00Z")
        resp = api.create_dock_slot(
            dock_id,
            {"vessel_id": vessel_id, "slot_start": "2026-08-10T16:30:00Z",
             "slot_end": "2026-08-10T18:00:00Z"},
            OM)
        validate_error(resp, ApiErrorId.ERR_DOCK_SLOT_CONFLICT)

    def test_temporal_conflict_independent_of_parking_pool_state(self, api):
        """PRD §2.8: "8. Berth turnaround-buffer overlap for the same vessel —
        `ERR_DOCK_SLOT_CONFLICT` (409)."
        PRD §3.2: "A creation that would violate this rule is rejected with
        `ERR_DOCK_SLOT_CONFLICT`."
        PRD §3.7: "Each dock's parking is a single shared pool."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_conflict
        """
        # The temporal check is about berth windows, not the parking pool: a
        # conflicting slot on a dock with zero parking stalls still fails with
        # the temporal error (the parking rule never applies to slot creation).
        inv = setup_inventory(parking_capacity=0)
        dock_id = inv["dock"]["id"]
        vessel_id = inv["vessel"]["id"]
        create_dock_slot(dock_id, vessel_id, "2026-08-10T14:00:00Z",
                         "2026-08-10T16:00:00Z")
        resp = api.create_dock_slot(
            dock_id,
            {"vessel_id": vessel_id, "slot_start": "2026-08-10T16:30:00Z",
             "slot_end": "2026-08-10T18:00:00Z"},
            OM)
        validate_error(resp, ApiErrorId.ERR_DOCK_SLOT_CONFLICT)

    def test_conflict_applies_across_docks_for_same_vessel(self, api):
        """PRD §3.2: "Two slots naming the same vessel — regardless of which
        docks they sit at — conflict whenever the first slot's start falls before
        the second slot's end plus a forty-five-minute turnaround buffer, and the
        second slot's start falls before the first slot's end plus the same
        buffer."

        Design: Difficulty/resource_temporal_overlap/dock_slot_turnaround_buffer_adjacency
        """
        inv = setup_inventory()
        vessel_id = inv["vessel"]["id"]
        dock_b = create_dock(parking_capacity=10, name="Pier 10")
        create_dock_slot(inv["dock"]["id"], vessel_id, "2026-08-10T14:00:00Z",
                         "2026-08-10T16:00:00Z")
        # Same vessel, different dock, overlapping within the buffer.
        resp = api.create_dock_slot(
            dock_b["id"],
            {"vessel_id": vessel_id, "slot_start": "2026-08-10T16:30:00Z",
             "slot_end": "2026-08-10T18:00:00Z"},
            OM)
        validate_error(resp, ApiErrorId.ERR_DOCK_SLOT_CONFLICT)


class TestParkingPoolBoundaries:
    def test_zero_capacity_empty_pool_and_unit_capacity(self, api):
        """PRD §3.7: "`parking_in_use` counts the dock's passes standing at
        `RESERVED` or `REDEEMED`, and a new pass is allowed only while that count
        is strictly below the dock's `parking_capacity` — the final stall is
        usable, so a count exactly one short of capacity admits the pass, while
        a count equal to capacity rejects it with `ERR_PARKING_FULL`."

        Design: Difficulty/boundary_precision_check/parking_pool_zero_capacity_empty_set_edge
        """
        dock_z = create_dock(parking_capacity=0, name="Pier Z")
        dock_o = create_dock(parking_capacity=1, name="Pier O")
        inv = setup_inventory()  # cruise on its own dock
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        bk_a = create_paid_booking(cruise["id"], customer["id"], 1,
                                   cruise["version"])
        version2 = get_cruise_version(api, cruise["id"])
        bk_b = create_booking(cruise["id"], customer["id"], 1, version2)
        assert bk_b["booking_status"] == "RESERVED"

        # Empty-pool edge: 0 < 0 is false, the very first pass is rejected.
        resp = api.create_parking_pass(
            dock_z["id"], {"booking_id": bk_a["id"], "cruise_id": cruise["id"]},
            ATTENDANT)
        validate_error(resp, ApiErrorId.ERR_PARKING_FULL)

        # Capacity 1: the single stall is usable.
        pass_o = create_parking_pass(dock_o["id"], bk_a["id"], cruise["id"])
        assert pass_o["status"] == "RESERVED"
        dock_o_after = validate_success(api.get_dock(dock_o["id"], OM))
        assert dock_o_after["parking_in_use"] == 1

        # Full pool: 1 < 1 is false.
        resp2 = api.create_parking_pass(
            dock_o["id"], {"booking_id": bk_b["id"], "cruise_id": cruise["id"]},
            ATTENDANT)
        validate_error(resp2, ApiErrorId.ERR_PARKING_FULL)

    def test_unit_capacity_boundary_admits_last_stall_then_rejects(self, api):
        """PRD §3.7: "The capacity check is aggregate-count semantics over the
        pool: `parking_in_use` counts the dock's passes standing at `RESERVED` or
        `REDEEMED`, and a new pass is allowed only while that count is strictly
        below the dock's `parking_capacity` — the final stall is usable, so a
        count exactly one short of capacity admits the pass, while a count equal
        to capacity rejects it with `ERR_PARKING_FULL`."

        Design: Difficulty/boundary_precision_check/parking_pool_zero_capacity_empty_set_edge
        """
        # Second scenario at the unit-capacity boundary: one stall admits exactly
        # one pass, and the pool-full rejection does not disturb the count.
        dock = create_dock(parking_capacity=1, name="Pier U")
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("u@example.com", "U")
        bk_a = create_paid_booking(cruise["id"], customer["id"], 1,
                                   cruise["version"])
        version2 = get_cruise_version(api, cruise["id"])
        bk_b = create_paid_booking(cruise["id"], customer["id"], 1, version2)

        first = create_parking_pass(dock["id"], bk_a["id"], cruise["id"])
        assert first["status"] == "RESERVED"
        resp = api.create_parking_pass(
            dock["id"], {"booking_id": bk_b["id"], "cruise_id": cruise["id"]},
            ATTENDANT)
        validate_error(resp, ApiErrorId.ERR_PARKING_FULL)
        assert validate_success(api.get_dock(dock["id"], OM))[
            "parking_in_use"] == 1, (
            "A rejected creation must not change parking_in_use"
        )

    def test_aggregate_pool_release_reopens_exactly_one_stall(self, api):
        """PRD §3.7: "Passes for the same cruise date draw on the same pool
        regardless of arrival hour; there is no time-slicing."
        PRD §3.7: "Releasing a pass — by a `DockAttendant`'s explicit release, or
        automatically when the cruise is weather-cancelled — moves a `RESERVED`
        pass to `RELEASED` and decrements `parking_in_use`."

        Design: Difficulty/resource_temporal_overlap/parking_pool_aggregate_non_interval_sharing
        """
        inv = setup_inventory(parking_capacity=1)
        dock = inv["dock"]
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        bk_a = create_paid_booking(cruise["id"], customer["id"], 1,
                                   cruise["version"])
        version2 = get_cruise_version(api, cruise["id"])
        bk_b = create_paid_booking(cruise["id"], customer["id"], 1, version2)

        pass_a = create_parking_pass(dock["id"], bk_a["id"], cruise["id"])
        # Pool is now full: the second pass is rejected on aggregate count.
        resp = api.create_parking_pass(
            dock["id"], {"booking_id": bk_b["id"], "cruise_id": cruise["id"]},
            ATTENDANT)
        validate_error(resp, ApiErrorId.ERR_PARKING_FULL)

        released = validate_success(api.release_parking_pass(pass_a["id"],
                                                             ATTENDANT))
        assert released["status"] == "RELEASED"
        dock_after = validate_success(api.get_dock(dock["id"], OM))
        assert dock_after["parking_in_use"] == 0

        # The released stall is available again — pool semantics, no intervals.
        pass_b = create_parking_pass(dock["id"], bk_b["id"], cruise["id"])
        assert pass_b["status"] == "RESERVED"

    def test_two_passes_same_cruise_share_pool_without_time_slicing(self, api):
        """PRD §3.7: "Passes for the same cruise date draw on the same pool
        regardless of arrival hour; there is no time-slicing."
        PRD §3.7: "the pass begins in `RESERVED` status and the dock's
        `parking_in_use` is incremented."

        Design: Difficulty/resource_temporal_overlap/parking_pool_aggregate_non_interval_sharing
        """
        inv = setup_inventory(parking_capacity=5)
        dock = inv["dock"]
        cruise = inv["cruise"]
        customer = create_customer("p@example.com", "P")
        bk_a = create_paid_booking(cruise["id"], customer["id"], 1,
                                   cruise["version"])
        version2 = get_cruise_version(api, cruise["id"])
        bk_b = create_paid_booking(cruise["id"], customer["id"], 1, version2)

        # Two passes for the same cruise consume two stalls — pure count, no
        # interval arithmetic.
        create_parking_pass(dock["id"], bk_a["id"], cruise["id"])
        create_parking_pass(dock["id"], bk_b["id"], cruise["id"])
        assert validate_success(api.get_dock(dock["id"], OM))[
            "parking_in_use"] == 2


class TestParkingInUseConservation:
    def test_create_release_round_trip_restores_parking_in_use(self, api):
        """PRD §3.7: "the pass begins in `RESERVED` status and the dock's
        `parking_in_use` is incremented."
        PRD §3.7: "Releasing a pass — by a `DockAttendant`'s explicit release, or
        automatically when the cruise is weather-cancelled — moves a `RESERVED`
        pass to `RELEASED` and decrements `parking_in_use`."

        Design: Difficulty/compensating_invariant/parking_in_use_conserved_under_pass_release
        """
        inv = setup_inventory(parking_capacity=5)
        dock = inv["dock"]
        cruise = inv["cruise"]
        assert dock["parking_in_use"] == 0
        customer = create_customer("a@example.com", "A")
        booking = create_paid_booking(cruise["id"], customer["id"], 1,
                                      cruise["version"])

        parking_pass = create_parking_pass(dock["id"], booking["id"],
                                           cruise["id"])
        assert validate_success(api.get_dock(dock["id"], OM))[
            "parking_in_use"] == 1
        released = validate_success(api.release_parking_pass(parking_pass["id"],
                                                             ATTENDANT))
        assert released["status"] == "RELEASED"
        assert validate_success(api.get_dock(dock["id"], OM))[
            "parking_in_use"] == 0, (
            "parking_in_use must return to its pre-action value after the "
            "compensating release"
        )

    def test_redeemed_pass_still_counts_toward_pool(self, api):
        """PRD §3.7: "A redeemed pass keeps its stall: `REDEEMED` still counts
        toward `parking_in_use`."
        PRD §3.7: "`parking_in_use` counts the dock's passes standing at
        `RESERVED` or `REDEEMED`, and a new pass is allowed only while that count
        is strictly below the dock's `parking_capacity`"

        Design: Difficulty/compensating_invariant/parking_in_use_conserved_under_pass_release
        """
        inv = setup_inventory(parking_capacity=5)
        dock = inv["dock"]
        cruise = inv["cruise"]
        customer = create_customer("b@example.com", "B")
        booking = create_paid_booking(cruise["id"], customer["id"], 1,
                                      cruise["version"])
        parking_pass = create_parking_pass(dock["id"], booking["id"],
                                           cruise["id"])
        redeemed = validate_success(api.redeem_parking_pass(parking_pass["id"],
                                                            ATTENDANT))
        assert redeemed["status"] == "REDEEMED"
        assert validate_success(api.get_dock(dock["id"], OM))[
            "parking_in_use"] == 1, (
            "A REDEEMED pass must keep counting toward parking_in_use"
        )


def get_cruise_version(api, cruise_id):
    return validate_success(api.get_cruise(cruise_id, OM))["version"]
