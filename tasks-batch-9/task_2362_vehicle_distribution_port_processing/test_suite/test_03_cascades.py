"""The two depth-four cascades: a hold reaching an already-allocated unit, and
an inspection failure reaching back into kit stock.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    DAMAGE_ZONE_INTERIOR,
    HOLD_OPEN,
    HOLD_TYPE_RECALL,
    INSPECTION_FAILED_STATUS,
    MODEL_LINE_LX500,
    OUTCOME_FAIL,
    PROC_ACCESSORY_IN_PROGRESS,
    PROC_SHIPPING_READY,
    RO_CANCELLED_BY_HOLD,
    ROUTE_ZONE_B,
    TECHNICIAN,
    WO_KITTED,
    Vpc,
    assert_center_ledgers,
    assert_freight_unsettled,
    assert_kit_ledger,
    assert_open_allocation_count,
    assert_slot_ledger,
    assert_storage_charges,
    assert_stop_ship,
    assert_subset,
    assert_vehicle_dimensions,
    factories as f,
    open_port,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 20, 0)


# ==========================================================================
# hold application
# ==========================================================================
def _allocated_unit(flow: Vpc) -> Dict[str, Any]:
    """One LX500 allocated to a zone-B dealer on a three-slot carrier."""
    port = open_port(flow)
    unit = port.discharge("000010", model_line=MODEL_LINE_LX500)
    port.complete_voyage()
    port.surveyed(unit["id"], [CLEAN_LINE])
    port.pass_inspection(unit["id"])
    ready = port.prep_complete(unit["id"])

    dealer = port.create_dealer(
        dealer_code="D-ATL",
        name="Atlanta Import Motors",
        route_zone=ROUTE_ZONE_B,
        distance_miles=285,
        allocation_quota=2,
    )
    carrier = port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["B"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=3,
        concurrent_load_capacity=2,
    )

    port.set_clock("2026-08-14T00:00:00Z")
    order = port.allocate(
        ready["id"],
        dealer["id"],
        ready["version"],
        pickup_window_start="2026-08-16T08:00:00Z",
        pickup_window_end="2026-08-16T12:00:00Z",
    )
    return {
        "port": port,
        "vehicle_id": unit["id"],
        "dealer_id": dealer["id"],
        "carrier_id": carrier["id"],
        "order": order,
    }


class TestHoldApplicationCascade:
    def test_hold_blocks_the_in_yard_unit_and_cancels_its_allocated_order(self, flow: Vpc):
        """Links one to three: the hold opens, stamps its reach, and cancels the
        allocated release order with its lineage recorded.

        PRD: "Link three, caused by link two, reaches the release orders of those
        units: any order sitting in `ALLOCATED` is moved to `CANCELLED_BY_HOLD`
        with its `cancelled_by_hold_order_id` set to this hold, processed in
        ascending `created_at` order."

        Design: Difficulty/transitive_cascade/hold_application_cascade_depth_four_cancels_allocation_and_reverses_accruals
        """
        scenario = _allocated_unit(flow)
        port = scenario["port"]

        hold = port.apply_model_line_hold(
            MODEL_LINE_LX500,
            hold_type=HOLD_TYPE_RECALL,
            reference_code="NHTSA-26V-0142",
        )

        assert_subset(hold, {"status": HOLD_OPEN, "affected_vehicle_count": 1})
        assert_stop_ship(
            port.get_vehicle(scenario["vehicle_id"]),
            blocked=True,
            blocking_hold_order_id=hold["id"],
        )
        order = port.get_release_order(scenario["order"]["id"])
        assert_subset(
            order,
            {"status": RO_CANCELLED_BY_HOLD, "cancelled_by_hold_order_id": hold["id"]},
        )
        assert_freight_unsettled(order)

    def test_hold_cascade_unwinds_slots_quota_usage_and_the_provisional_accrual(self, flow: Vpc):
        """Link four: the commercial commitments of the cancelled order are undone.

        PRD: "Link four, caused by link three, unwinds the commercial commitments
        of every order the cascade cancelled: the assigned carrier's
        `committed_slots` and `available_slots` are recomputed and the consignee
        dealer's `open_allocation_count` is recomputed, both preserving the slot
        conservation invariant; each affected unit's processing dimension reverts
        to `SHIPPING_READY`; and each unit's `storage_charge_provisional_cents` is
        reset to 0 with the center's `provisional_storage_accrued_cents`
        recomputed accordingly."

        Design: Difficulty/transitive_cascade/hold_application_cascade_depth_four_cancels_allocation_and_reverses_accruals
        """
        scenario = _allocated_unit(flow)
        port = scenario["port"]

        assert_slot_ledger(
            port.get_carrier(scenario["carrier_id"]), committed_slots=1, available_slots=2
        )
        assert_open_allocation_count(port.get_dealer(scenario["dealer_id"]), 1)
        assert_storage_charges(
            port.get_vehicle(scenario["vehicle_id"]), provisional_cents=13_050
        )

        port.apply_model_line_hold(
            MODEL_LINE_LX500,
            hold_type=HOLD_TYPE_RECALL,
            reference_code="NHTSA-26V-0142",
        )

        assert_slot_ledger(
            port.get_carrier(scenario["carrier_id"]), committed_slots=0, available_slots=3
        )
        assert_open_allocation_count(port.get_dealer(scenario["dealer_id"]), 0)
        unit = port.get_vehicle(scenario["vehicle_id"])
        assert_vehicle_dimensions(unit, processing_status=PROC_SHIPPING_READY)
        assert_storage_charges(unit, provisional_cents=0)
        assert_center_ledgers(port.get_center(), provisional_storage_accrued_cents=0)


# ==========================================================================
# inspection failure
# ==========================================================================
def _inspected_unit_with_installed_options(flow: Vpc) -> Dict[str, Any]:
    """A passed unit carrying a four-unit installed accessory work order."""
    port = open_port(flow)
    kit = port.create_kit(
        kit_code="KIT-ALLOY-19",
        program_code="PIO-ALLOY",
        received_qty_total=10,
        unit_cost_cents=12_340,
        install_minutes_per_unit=24,
    )
    unit = port.discharge("000011", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY")
    port.surveyed(unit["id"], [CLEAN_LINE])
    order = port.installed_work_order(unit["id"], kit["id"], 4, TECHNICIAN)
    port.pass_inspection(unit["id"])
    return {
        "port": port,
        "vehicle_id": unit["id"],
        "kit_id": kit["id"],
        "order": order,
    }


class TestInspectionFailureCascade:
    def test_failure_reopens_the_installed_order_and_clears_its_billing(self, flow: Vpc):
        """Links one to three: the order returns to kitted, counts a reopen, loses
        its billing and keeps the installer on record.

        PRD: "Link three, caused by link two, walks every accessory work order of
        that unit currently in `INSTALLED`, in ascending `created_at` order, and
        returns each one from `INSTALLED` to `KITTED`, increasing its
        `reopen_count` by one and resetting its `billed_cents` to 0;
        `installed_by_user_id` is deliberately retained."

        Design: Difficulty/transitive_cascade/inspection_failure_cascade_depth_four_reopens_work_orders_and_restores_kit
        """
        scenario = _inspected_unit_with_installed_options(flow)
        port = scenario["port"]
        installer = scenario["order"]["installed_by_user_id"]

        assert scenario["order"]["billed_cents"] == 69_932

        reinspection = port.open_inspection(scenario["vehicle_id"])
        failed = port.complete_inspection(reinspection["id"], OUTCOME_FAIL, 3)

        assert failed["status"] == INSPECTION_FAILED_STATUS
        unit = port.get_vehicle(scenario["vehicle_id"])
        assert_vehicle_dimensions(unit, processing_status=PROC_ACCESSORY_IN_PROGRESS)
        assert unit["rework_cycle_count"] == 1
        assert_subset(
            port.get_work_order(scenario["order"]["id"]),
            {
                "status": WO_KITTED,
                "reopen_count": 1,
                "billed_cents": 0,
                "installed_by_user_id": installer,
            },
        )

    def test_failure_returns_the_consumed_units_to_stock_as_a_reservation(self, flow: Vpc):
        """Link four: on-hand stock is restored while the reopened order still
        holds its reservation, and the unit's accessory billing is recomputed.

        PRD: "Link four, caused by link three, restores stock for each reopened
        order — the kit's `on_hand_qty` is increased by that order's `qty`, and
        `consumed_qty`, `reserved_qty` and `available_qty` are recomputed, along
        with the unit's `accessory_billed_cents`."

        Design: Difficulty/transitive_cascade/inspection_failure_cascade_depth_four_reopens_work_orders_and_restores_kit
        """
        scenario = _inspected_unit_with_installed_options(flow)
        port = scenario["port"]

        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=6,
            reserved_qty=0,
            available_qty=6,
            consumed_qty=4,
            received_qty_total=10,
        )

        reinspection = port.open_inspection(scenario["vehicle_id"])
        port.complete_inspection(reinspection["id"], OUTCOME_FAIL, 3)

        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=10,
            reserved_qty=4,
            available_qty=6,
            consumed_qty=0,
            received_qty_total=10,
        )
        assert port.get_vehicle(scenario["vehicle_id"])["accessory_billed_cents"] == 0
