"""Half-open intervals competing for one berth or one tractor fleet, and the two
counters that must come back to where they started.
"""

from __future__ import annotations

from typing import Any, Dict, List

from test_helpers import (
    DAMAGE_ZONE_INTERIOR,
    ERR_BERTH_WINDOW_CONFLICT,
    ERR_CARRIER_WINDOW_CAPACITY,
    MANAGER,
    MODEL_LINE_LX500,
    MODEL_LINE_TX300,
    PLANNER,
    PROC_ALLOCATED,
    PROC_SHIPPING_READY,
    RO_ALLOCATED,
    RO_CANCELLED,
    RO_RELEASED,
    ROUTE_ZONE_B,
    VESSEL_DISCHARGING,
    VESSEL_SCHEDULED,
    WO_KITTED,
    WO_VOIDED,
    Vpc,
    assert_kit_ledger,
    assert_open_allocation_count,
    assert_slot_ledger,
    assert_subset,
    assert_vehicle_dimensions,
    factories as f,
    ok,
    open_port,
    validate_error,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 20, 0)

FIRST_WINDOW = {
    "pickup_window_start": "2026-08-05T08:00:00Z",
    "pickup_window_end": "2026-08-05T12:00:00Z",
}
ADJACENT_WINDOW = {
    "pickup_window_start": "2026-08-05T12:00:00Z",
    "pickup_window_end": "2026-08-05T16:00:00Z",
}
STRADDLING_WINDOW = {
    "pickup_window_start": "2026-08-05T11:00:00Z",
    "pickup_window_end": "2026-08-05T13:00:00Z",
}


def _ready_units(port: Vpc, serials: List[str], model_line: str) -> List[Dict[str, Any]]:
    """Walk several units off one voyage to ``SHIPPING_READY``."""
    units = [port.discharge(serial, model_line=model_line) for serial in serials]
    for unit in units:
        port.surveyed(unit["id"], [CLEAN_LINE])
    port.complete_voyage()
    ready = []
    for unit in units:
        port.pass_inspection(unit["id"])
        ready.append(port.prep_complete(unit["id"]))
    return ready


# ==========================================================================
# the berth turnaround buffer on both sides of a window
# ==========================================================================
def _berth_with_one_scheduled_voyage(flow: Vpc) -> Dict[str, Any]:
    """A two-hour-buffer berth holding a scheduled 06:00-18:00 voyage."""
    flow.set_clock("2026-08-01T00:00:00Z")
    center = flow.create_center()
    berth = flow.create_berth(center["id"], berth_code="B1", turnaround_buffer_minutes=120)
    neighbour = flow.create_vessel(
        center["id"],
        berth["id"],
        voyage_code="V001",
        berth_window_start="2026-08-01T06:00:00Z",
        berth_window_end="2026-08-01T18:00:00Z",
        declared_unit_count=10,
    )
    return {
        "flow": flow,
        "center_id": center["id"],
        "berth_id": berth["id"],
        "neighbour": neighbour,
    }


class TestBerthTurnaroundBuffer:
    def test_a_one_hour_gap_does_not_clear_a_two_hour_buffer(self, flow: Vpc):
        """A window an hour after its neighbour ends still conflicts.

        PRD: "Taking the berth's turnaround buffer as a duration, a conflict exists
        when the new window's start falls before the neighbour's end extended
        forward by that buffer, and at the same time the neighbour's start falls
        before the new window's end extended forward by that buffer."

        Design: Difficulty/resource_temporal_overlap/berth_window_requires_turnaround_buffer_clearance_on_both_sides
        """
        scenario = _berth_with_one_scheduled_voyage(flow)
        assert scenario["neighbour"]["discharge_status"] == VESSEL_SCHEDULED

        response = flow.api.create_vessel(
            f.vessel_payload(
                scenario["center_id"],
                scenario["berth_id"],
                voyage_code="V002",
                berth_window_start="2026-08-01T19:00:00Z",
                berth_window_end="2026-08-02T05:00:00Z",
                declared_unit_count=4,
            ),
            PLANNER,
        )
        validate_error(response, ERR_BERTH_WINDOW_CONFLICT, 409)

    def test_a_gap_of_exactly_the_full_buffer_is_accepted(self, flow: Vpc):
        """Clearing the neighbour by the full buffer on both sides is admitted.

        PRD: "In plain operational terms, a new window must clear its neighbour on
        either side by at least the full buffer; a window that begins at the exact
        instant a neighbour ends is a conflict, because zero gap is less than the
        buffer."

        Design: Difficulty/resource_temporal_overlap/berth_window_requires_turnaround_buffer_clearance_on_both_sides
        """
        scenario = _berth_with_one_scheduled_voyage(flow)
        flow.api.create_vessel(
            f.vessel_payload(
                scenario["center_id"],
                scenario["berth_id"],
                voyage_code="V002",
                berth_window_start="2026-08-01T19:00:00Z",
                berth_window_end="2026-08-02T05:00:00Z",
                declared_unit_count=4,
            ),
            PLANNER,
        )

        accepted = flow.create_vessel(
            scenario["center_id"],
            scenario["berth_id"],
            voyage_code="V003",
            berth_window_start="2026-08-01T20:00:00Z",
            berth_window_end="2026-08-02T06:00:00Z",
            declared_unit_count=4,
        )
        assert accepted["discharge_status"] == VESSEL_SCHEDULED

        voyages = ok(flow.api.list_vessels(PLANNER))
        live = [
            voyage
            for voyage in voyages
            if voyage["berth_id"] == scenario["berth_id"]
            and voyage["discharge_status"] in (VESSEL_SCHEDULED, VESSEL_DISCHARGING)
        ]
        assert len(live) == 2


# ==========================================================================
# carrier pickup-window concurrency
# ==========================================================================
def _three_allocations_on_one_carrier(flow: Vpc) -> Dict[str, Any]:
    """Three orders on a single-load carrier: two adjacent, one straddling both."""
    port = open_port(flow)
    units = _ready_units(port, ["000028", "000029", "000030"], MODEL_LINE_TX300)
    dealer = port.create_dealer(
        dealer_code="D-BIG",
        name="Bigtown Auto",
        route_zone=ROUTE_ZONE_B,
        distance_miles=285,
        allocation_quota=5,
    )
    carrier = port.create_carrier(
        carrier_code="TC-SOLO",
        name="Solo Load Transport",
        served_route_zones=["B"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=3,
        concurrent_load_capacity=1,
    )
    orders = [
        port.allocate(units[0]["id"], dealer["id"], units[0]["version"], **FIRST_WINDOW),
        port.allocate(units[1]["id"], dealer["id"], units[1]["version"], **ADJACENT_WINDOW),
        port.allocate(units[2]["id"], dealer["id"], units[2]["version"], **STRADDLING_WINDOW),
    ]
    return {"port": port, "carrier_id": carrier["id"], "orders": orders}


class TestCarrierPickupWindowConcurrency:
    def test_a_window_starting_when_another_ends_does_not_occupy_it(self, flow: Vpc):
        """Half-open windows make adjacency free of charge.

        PRD: "Pickup windows are half-open, and adjacency is explicitly allowed —
        a window that begins exactly when another ends does not overlap it."

        Design: Difficulty/resource_temporal_overlap/carrier_concurrent_pickup_windows_aggregate_with_adjacency_allowed
        """
        scenario = _three_allocations_on_one_carrier(flow)
        port = scenario["port"]

        first = port.dispatch(scenario["orders"][0]["id"])
        second = port.dispatch(scenario["orders"][1]["id"])

        assert first["status"] == RO_RELEASED
        assert second["status"] == RO_RELEASED

    def test_a_window_covering_both_peers_exceeds_the_concurrency_ceiling(self, flow: Vpc):
        """The straddling window is simultaneously occupied with a released peer.

        PRD: "The server evaluates, at every peer window boundary instant that
        lies inside the candidate window's own half-open span, how many windows
        would be simultaneously occupied — the candidate itself plus every peer
        covering that instant — and takes the largest such count."

        Design: Difficulty/resource_temporal_overlap/carrier_concurrent_pickup_windows_aggregate_with_adjacency_allowed
        """
        scenario = _three_allocations_on_one_carrier(flow)
        port = scenario["port"]
        port.dispatch(scenario["orders"][0]["id"])
        port.dispatch(scenario["orders"][1]["id"])

        response = port.api.dispatch(scenario["orders"][2]["id"], MANAGER)
        validate_error(response, ERR_CARRIER_WINDOW_CAPACITY, 409)

        assert port.get_release_order(scenario["orders"][2]["id"])["status"] == RO_ALLOCATED
        assert_slot_ledger(
            port.get_carrier(scenario["carrier_id"]), committed_slots=3, available_slots=0
        )


# ==========================================================================
# kit units conserved across install and void
# ==========================================================================
def _installed_four_of_ten(flow: Vpc) -> Dict[str, Any]:
    """Four of ten kit units installed on one unit, ready to be voided back."""
    port = open_port(flow)
    kit = port.create_kit(
        kit_code="KIT-ALLOY-19",
        program_code="PIO-ALLOY",
        received_qty_total=10,
        unit_cost_cents=12_340,
        install_minutes_per_unit=24,
    )
    unit = port.discharge("000031", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY")
    port.surveyed(unit["id"], [CLEAN_LINE])
    order = port.plan_work_order(unit["id"], kit["id"], 4)
    return {
        "port": port,
        "vehicle_id": unit["id"],
        "kit_id": kit["id"],
        "order_id": order["id"],
    }


class TestKitUnitConservation:
    def test_kitting_reserves_and_installing_consumes_without_changing_the_total(self, flow: Vpc):
        """On hand plus consumed equals received at every step.

        PRD: "For every accessory kit stock record, `on_hand_qty` plus
        `consumed_qty` always equals `received_qty_total`."

        Design: Difficulty/compensating_invariant/kit_units_conserved_across_install_and_void
        """
        scenario = _installed_four_of_ten(flow)
        port = scenario["port"]

        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=10,
            reserved_qty=0,
            available_qty=10,
            consumed_qty=0,
            received_qty_total=10,
        )

        kitted = port.kit_work_order(scenario["order_id"])
        assert kitted["status"] == WO_KITTED
        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=10,
            reserved_qty=4,
            available_qty=6,
            consumed_qty=0,
            received_qty_total=10,
        )

        installed = port.install_work_order(scenario["order_id"])
        assert installed["billed_cents"] == 69_932
        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=6,
            reserved_qty=0,
            available_qty=6,
            consumed_qty=4,
            received_qty_total=10,
        )

    def test_voiding_an_installed_order_restores_the_opening_ledger_exactly(self, flow: Vpc):
        """The void is the exact compensating half of the installation.

        PRD: "From `INSTALLED` voiding is the exact compensating half of
        installation: the kit's `on_hand_qty` is increased by the work order's
        `qty`, `consumed_qty`, `reserved_qty` and `available_qty` are recomputed,
        `billed_cents` is reset to 0, and the unit's `accessory_billed_cents` is
        recomputed — restoring the conservation invariant to the state it held
        before installation."

        Design: Difficulty/compensating_invariant/kit_units_conserved_across_install_and_void
        """
        scenario = _installed_four_of_ten(flow)
        port = scenario["port"]
        port.kit_work_order(scenario["order_id"])
        port.install_work_order(scenario["order_id"])

        voided = port.void_work_order(scenario["order_id"])

        assert_subset(voided, {"status": WO_VOIDED, "billed_cents": 0})
        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=10,
            reserved_qty=0,
            available_qty=10,
            consumed_qty=0,
            received_qty_total=10,
        )
        assert port.get_vehicle(scenario["vehicle_id"])["accessory_billed_cents"] == 0


# ==========================================================================
# tractor slots conserved across cancellation and supersession
# ==========================================================================
def _two_allocations_on_a_three_slot_carrier(flow: Vpc) -> Dict[str, Any]:
    """Two orders held against a three-slot carrier."""
    port = open_port(flow)
    first, second = _ready_units(port, ["000032", "000033"], MODEL_LINE_LX500)
    dealer = port.create_dealer(
        dealer_code="D-BIG",
        name="Bigtown Auto",
        route_zone=ROUTE_ZONE_B,
        distance_miles=285,
        allocation_quota=5,
    )
    carrier = port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["B"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=3,
        concurrent_load_capacity=2,
    )
    assert_slot_ledger(port.get_carrier(carrier["id"]), committed_slots=0, available_slots=3)

    order_a = port.allocate(first["id"], dealer["id"], first["version"], **FIRST_WINDOW)
    order_b = port.allocate(second["id"], dealer["id"], second["version"], **ADJACENT_WINDOW)
    return {
        "port": port,
        "dealer_id": dealer["id"],
        "carrier_id": carrier["id"],
        "vehicle_a": first["id"],
        "vehicle_b": second["id"],
        "order_a": order_a,
        "order_b": order_b,
    }


class TestTractorSlotConservation:
    def test_cancelling_an_allocation_returns_its_slot_to_the_pool(self, flow: Vpc):
        """Committed plus available equals capacity before and after the cancel.

        PRD: "For every inland carrier, `committed_slots` plus `available_slots`
        always equals `slot_capacity`."

        Design: Difficulty/compensating_invariant/carrier_slots_conserved_across_allocate_cancel_and_supersede
        """
        scenario = _two_allocations_on_a_three_slot_carrier(flow)
        port = scenario["port"]

        assert_slot_ledger(
            port.get_carrier(scenario["carrier_id"]), committed_slots=2, available_slots=1
        )

        cancelled = port.cancel(scenario["order_a"]["id"])

        assert cancelled["status"] == RO_CANCELLED
        assert_slot_ledger(
            port.get_carrier(scenario["carrier_id"]), committed_slots=1, available_slots=2
        )
        assert_vehicle_dimensions(
            port.get_vehicle(scenario["vehicle_a"]), processing_status=PROC_SHIPPING_READY
        )

    def test_superseding_an_allocation_moves_the_slot_without_double_counting(self, flow: Vpc):
        """A dealer swap cancels the prior order and holds the count steady.

        PRD: "On success the prior order moves to `CANCELLED` and the new order's
        `superseded_release_order_id` points at it; the prior order's carrier has
        its `committed_slots` recomputed and the prior dealer has its
        `open_allocation_count` recomputed; the unit's
        `storage_charge_provisional_cents` is recomputed against the new allocation
        instant; and the unit's `version` increments by one again."

        Design: Difficulty/compensating_invariant/carrier_slots_conserved_across_allocate_cancel_and_supersede
        """
        scenario = _two_allocations_on_a_three_slot_carrier(flow)
        port = scenario["port"]
        port.cancel(scenario["order_a"]["id"])

        current = port.get_vehicle(scenario["vehicle_b"])
        replacement = port.allocate(
            current["id"],
            scenario["dealer_id"],
            current["version"],
            pickup_window_start="2026-08-06T08:00:00Z",
            pickup_window_end="2026-08-06T12:00:00Z",
        )

        assert replacement["superseded_release_order_id"] == scenario["order_b"]["id"]
        assert port.get_release_order(scenario["order_b"]["id"])["status"] == RO_CANCELLED
        assert_slot_ledger(
            port.get_carrier(scenario["carrier_id"]), committed_slots=1, available_slots=2
        )
        assert_open_allocation_count(port.get_dealer(scenario["dealer_id"]), 1)
        assert_vehicle_dimensions(
            port.get_vehicle(scenario["vehicle_b"]), processing_status=PROC_ALLOCATED
        )
