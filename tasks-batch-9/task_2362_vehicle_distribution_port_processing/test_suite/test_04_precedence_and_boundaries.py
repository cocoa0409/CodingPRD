"""Which of two simultaneously true failures is reported, and what happens at
the exact value where a threshold flips.
"""

from __future__ import annotations

from typing import Any, Dict, List

from test_helpers import (
    CENTER_DAILY_STORAGE_RATE_CENTS,
    DAMAGE_REPAIR_AUTHORIZED,
    DAMAGE_SURVEY_DAMAGE_OPEN,
    DAMAGE_ZONE_BODY_PANEL,
    DAMAGE_ZONE_GLASS,
    DAMAGE_ZONE_INTERIOR,
    ERR_INVALID_STATE,
    ERR_NO_ELIGIBLE_CARRIER,
    ERR_VEHICLE_STOP_SHIP_BLOCKED,
    ERR_YARD_GRIDLOCK,
    HOLD_TYPE_STOP_SHIP,
    MANAGER,
    MODEL_LINE_EV900,
    MODEL_LINE_LX500,
    POSTURE_CONSTRAINED,
    POSTURE_GRIDLOCK,
    POSTURE_OPEN,
    PLANNER,
    PROC_SHIPPING_READY,
    REPAIR_AUTHORIZED_STATUS,
    REPAIR_ESCALATED_STATUS,
    RO_ALLOCATED,
    ROUTE_ZONE_B,
    TECHNICIAN,
    TIER_AUTO,
    TIER_ESCALATED,
    VESSEL_DISCHARGING,
    WO_VOIDED,
    Vpc,
    assert_kit_ledger,
    assert_open_allocation_count,
    assert_slot_ledger,
    assert_subset,
    assert_vehicle_dimensions,
    assert_yard_state,
    factories as f,
    open_port,
    validate_error,
    vin,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 20, 0)
MAJOR_LINES = [
    f.damage_line(DAMAGE_ZONE_BODY_PANEL, 40, 40_000),
    f.damage_line(DAMAGE_ZONE_GLASS, 30, 20_000),
]


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
# stop-ship outranks the dealer quota
# ==========================================================================
def _blocked_second_unit(flow: Vpc) -> Dict[str, Any]:
    """A dealer at its quota of one, whose next candidate unit is stop-shipped."""
    port = open_port(flow)
    first, second = _ready_units(port, ["000012", "000013"], MODEL_LINE_LX500)

    dealer = port.create_dealer(
        dealer_code="D-ONE",
        name="Single Slot Motors",
        route_zone=ROUTE_ZONE_B,
        distance_miles=285,
        allocation_quota=1,
    )
    port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["B"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=3,
        concurrent_load_capacity=2,
    )
    order = port.allocate(
        first["id"],
        dealer["id"],
        first["version"],
        pickup_window_start="2026-08-05T08:00:00Z",
        pickup_window_end="2026-08-05T12:00:00Z",
    )
    port.apply_single_vin_hold(
        second["id"], hold_type=HOLD_TYPE_STOP_SHIP, reference_code="SS-2026-77"
    )
    return {
        "port": port,
        "dealer_id": dealer["id"],
        "first_order": order,
        "blocked_vehicle": port.get_vehicle(second["id"]),
    }


class TestStopShipOutranksDealerQuota:
    def test_the_safety_block_is_reported_ahead_of_the_quota_ceiling(self, flow: Vpc):
        """Both failures are true; the lower-numbered band answers.

        PRD: "11. Recall and stop-ship blocking — `ERR_VEHICLE_STOP_SHIP_BLOCKED`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/stop_ship_safety_outranks_dealer_quota_fiscal_on_allocation
        """
        scenario = _blocked_second_unit(flow)
        port = scenario["port"]
        blocked = scenario["blocked_vehicle"]

        assert_open_allocation_count(port.get_dealer(scenario["dealer_id"]), 1)
        assert blocked["stop_ship_blocked"] is True

        response = port.api.allocate(
            blocked["id"],
            f.allocation_payload(
                scenario["dealer_id"],
                blocked["version"],
                pickup_window_start="2026-08-05T08:00:00Z",
                pickup_window_end="2026-08-05T12:00:00Z",
            ),
            MANAGER,
        )
        validate_error(response, ERR_VEHICLE_STOP_SHIP_BLOCKED, 409)

    def test_the_refused_allocation_leaves_no_order_and_no_counter_movement(self, flow: Vpc):
        """A rejected allocation creates nothing and consumes no quota.

        PRD: "the unit must not be covered by an open hold, or the allocation is
        refused with `ERR_VEHICLE_STOP_SHIP_BLOCKED`; the carrier candidate set
        must be non-empty, or the allocation is refused with
        `ERR_NO_ELIGIBLE_CARRIER`; and the consignee dealer's
        `open_allocation_count` must be strictly below its `allocation_quota`, or
        the allocation is refused with `ERR_DEALER_QUOTA_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/stop_ship_safety_outranks_dealer_quota_fiscal_on_allocation
        """
        scenario = _blocked_second_unit(flow)
        port = scenario["port"]
        blocked = scenario["blocked_vehicle"]

        port.api.allocate(
            blocked["id"],
            f.allocation_payload(
                scenario["dealer_id"],
                blocked["version"],
                pickup_window_start="2026-08-05T08:00:00Z",
                pickup_window_end="2026-08-05T12:00:00Z",
            ),
            MANAGER,
        )

        assert_vehicle_dimensions(
            port.get_vehicle(blocked["id"]), processing_status=PROC_SHIPPING_READY
        )
        assert_open_allocation_count(port.get_dealer(scenario["dealer_id"]), 1)
        assert port.list_release_orders({"vehicle_id": blocked["id"]}) == []
        assert port.get_release_order(scenario["first_order"]["id"])["status"] == RO_ALLOCATED


# ==========================================================================
# state legality outranks kit sufficiency
# ==========================================================================
def _voided_work_order_over_short_stock(flow: Vpc) -> Dict[str, Any]:
    """A voided work order for five units against two units of stock."""
    port = open_port(flow)
    kit = port.create_kit(
        kit_code="KIT-MAT-01",
        program_code="PIO-MAT",
        received_qty_total=2,
        unit_cost_cents=4_500,
        install_minutes_per_unit=6,
    )
    unit = port.discharge("000014", model_line=MODEL_LINE_LX500, pio_program_code="PIO-MAT")
    port.surveyed(unit["id"], [CLEAN_LINE])
    order = port.plan_work_order(unit["id"], kit["id"], 5)
    voided = port.void_work_order(order["id"])
    return {"port": port, "kit_id": kit["id"], "order_id": order["id"], "voided": voided}


class TestInvalidStateOutranksKitShortfall:
    def test_a_voided_order_is_refused_on_state_not_on_stock(self, flow: Vpc):
        """State legality is band eight; kit sufficiency is band twenty.

        PRD: "8. State legality: the requested transition must exist from the
        target's current state — `ERR_INVALID_STATE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_kit_insufficient_on_kitting
        """
        scenario = _voided_work_order_over_short_stock(flow)
        port = scenario["port"]

        assert scenario["voided"]["status"] == WO_VOIDED

        response = port.api.kit_work_order(scenario["order_id"], TECHNICIAN)
        validate_error(response, ERR_INVALID_STATE, 409)

    def test_the_refused_kitting_reserves_nothing(self, flow: Vpc):
        """A voided order is terminal and contributes to no kit quantity.

        PRD: "A voided work order is terminal and contributes to no kit quantity
        thereafter."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_kit_insufficient_on_kitting
        """
        scenario = _voided_work_order_over_short_stock(flow)
        port = scenario["port"]

        port.api.kit_work_order(scenario["order_id"], TECHNICIAN)

        assert port.get_work_order(scenario["order_id"])["status"] == WO_VOIDED
        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=2,
            reserved_qty=0,
            available_qty=2,
            consumed_qty=0,
            received_qty_total=2,
        )


# ==========================================================================
# the repair escalation threshold
# ==========================================================================
def _two_damaged_units(flow: Vpc) -> Dict[str, Any]:
    """Two units with submitted surveys and open damage."""
    port = open_port(flow)
    low = port.discharge("000015", model_line=MODEL_LINE_LX500)
    high = port.discharge("000016", model_line=MODEL_LINE_LX500)
    port.surveyed(low["id"], MAJOR_LINES)
    port.surveyed(high["id"], MAJOR_LINES)
    return {"port": port, "low_id": low["id"], "high_id": high["id"]}


class TestRepairEscalationThreshold:
    def test_one_cent_below_the_threshold_stays_automatic(self, flow: Vpc):
        """The band below 150,000 cents is the surveyor's own call.

        PRD: "an estimate of 150,000 cents or more — fifteen hundred dollars,
        inclusive at the boundary — is `ESCALATED`, and anything below it is
        `AUTO`."

        Design: Difficulty/boundary_precision_check/repair_estimate_exactly_at_escalation_threshold_escalates
        """
        scenario = _two_damaged_units(flow)
        port = scenario["port"]

        order = port.repair_order(scenario["low_id"], 149_999)

        assert_subset(
            order, {"authorization_tier": TIER_AUTO, "status": REPAIR_AUTHORIZED_STATUS}
        )
        assert order["authorized_by_user_id"] is not None
        assert_vehicle_dimensions(
            port.get_vehicle(scenario["low_id"]), damage_status=DAMAGE_REPAIR_AUTHORIZED
        )

    def test_exactly_at_the_threshold_escalates(self, flow: Vpc):
        """150,000 cents itself escalates and holds the damage dimension.

        PRD: "An `ESCALATED` estimate is created in `ESCALATED`,
        `authorized_by_user_id` stays null, and the unit's damage dimension is
        **not** advanced — it remains in `SURVEY_DAMAGE_OPEN`, and the unit stays
        damage-blocked until a manager acts."

        Design: Difficulty/boundary_precision_check/repair_estimate_exactly_at_escalation_threshold_escalates
        """
        scenario = _two_damaged_units(flow)
        port = scenario["port"]

        order = port.repair_order(scenario["high_id"], 150_000)

        assert_subset(
            order,
            {
                "authorization_tier": TIER_ESCALATED,
                "status": REPAIR_ESCALATED_STATUS,
                "authorized_by_user_id": None,
            },
        )
        assert_vehicle_dimensions(
            port.get_vehicle(scenario["high_id"]), damage_status=DAMAGE_SURVEY_DAMAGE_OPEN
        )


# ==========================================================================
# a carrier with no free slot leaves the candidate set empty
# ==========================================================================
def _single_slot_carrier(flow: Vpc) -> Dict[str, Any]:
    """Two ready units and a carrier holding exactly one tractor slot."""
    port = open_port(flow)
    first, second = _ready_units(port, ["000017", "000018"], MODEL_LINE_EV900)
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
        slot_capacity=1,
        concurrent_load_capacity=2,
    )
    return {
        "port": port,
        "dealer_id": dealer["id"],
        "carrier_id": carrier["id"],
        "first": first,
        "second": second,
    }


class TestEmptyCandidatePoolAtZeroFreeSlots:
    def test_the_last_free_slot_is_still_a_candidate(self, flow: Vpc):
        """A free slot count of one admits the allocation and consumes the slot.

        PRD: "The candidate set is every carrier whose `status` is `ACTIVE`, whose
        `served_route_zones` includes the route zone of this allocation (which is
        the dealer's `route_zone`), and whose `slot_capacity` less
        `committed_slots` is at least 1."

        Design: Difficulty/boundary_precision_check/carrier_free_slot_count_exactly_zero_empties_the_candidate_pool
        """
        scenario = _single_slot_carrier(flow)
        port = scenario["port"]

        order = port.allocate(
            scenario["first"]["id"],
            scenario["dealer_id"],
            scenario["first"]["version"],
            pickup_window_start="2026-08-05T08:00:00Z",
            pickup_window_end="2026-08-05T12:00:00Z",
        )

        assert order["truck_carrier_id"] == scenario["carrier_id"]
        assert_slot_ledger(
            port.get_carrier(scenario["carrier_id"]), committed_slots=1, available_slots=0
        )

    def test_zero_free_slots_rejects_rather_than_queues(self, flow: Vpc):
        """With the only carrier full the candidate set is empty.

        PRD: "If the candidate set is empty the allocation is rejected rather than
        queued."

        Design: Difficulty/boundary_precision_check/carrier_free_slot_count_exactly_zero_empties_the_candidate_pool
        """
        scenario = _single_slot_carrier(flow)
        port = scenario["port"]
        port.allocate(
            scenario["first"]["id"],
            scenario["dealer_id"],
            scenario["first"]["version"],
            pickup_window_start="2026-08-05T08:00:00Z",
            pickup_window_end="2026-08-05T12:00:00Z",
        )

        response = port.api.allocate(
            scenario["second"]["id"],
            f.allocation_payload(
                scenario["dealer_id"],
                scenario["second"]["version"],
                pickup_window_start="2026-08-06T08:00:00Z",
                pickup_window_end="2026-08-06T12:00:00Z",
            ),
            MANAGER,
        )
        validate_error(response, ERR_NO_ELIGIBLE_CARRIER, 409)

        assert_vehicle_dimensions(
            port.get_vehicle(scenario["second"]["id"]), processing_status=PROC_SHIPPING_READY
        )
        assert_open_allocation_count(port.get_dealer(scenario["dealer_id"]), 1)
        assert_slot_ledger(
            port.get_carrier(scenario["carrier_id"]), committed_slots=1, available_slots=0
        )


# ==========================================================================
# yard posture at the exact ratios
# ==========================================================================
def _tiny_yard(flow: Vpc) -> Vpc:
    """A five-slot yard, so each unit moves the ratio by exactly 0.2."""
    return open_port(
        flow,
        name="Tiny Yard VPC",
        port_code="USTNY",
        yard_capacity_slots=5,
        daily_storage_rate_cents=CENTER_DAILY_STORAGE_RATE_CENTS,
    )


class TestYardPostureBoundaries:
    def test_posture_steps_from_open_through_constrained_to_gridlock(self, flow: Vpc):
        """0.60 is open, 0.80 is constrained and 1.00 is gridlock.

        PRD: "When that ratio is at least 0.95, posture is `GRIDLOCK`; otherwise,
        when it is at least 0.80, posture is `CONSTRAINED`; otherwise it is
        `OPEN`."

        Design: Difficulty/boundary_precision_check/yard_occupancy_exactly_at_constrained_ratio_still_admits_a_unit
        """
        port = _tiny_yard(flow)
        for serial in ("000019", "000020", "000021"):
            port.discharge(serial, model_line=MODEL_LINE_LX500)
        assert_yard_state(port.get_center(), occupied_slots=3, free_slots=2, posture=POSTURE_OPEN)

        port.discharge("000022", model_line=MODEL_LINE_LX500)
        assert_yard_state(port.get_center(), occupied_slots=4, posture=POSTURE_CONSTRAINED)

        port.discharge("000023", model_line=MODEL_LINE_LX500)
        assert_yard_state(port.get_center(), occupied_slots=5, free_slots=0, posture=POSTURE_GRIDLOCK)

    def test_a_gridlocked_yard_refuses_the_next_unit(self, flow: Vpc):
        """The refusal is evaluated on the posture at request time.

        PRD: "and if the destination center's posture is already `GRIDLOCK` at the
        moment of the request, the discharge is refused outright with
        `ERR_YARD_GRIDLOCK`, because a full yard cannot absorb another unit."

        Design: Difficulty/boundary_precision_check/yard_occupancy_exactly_at_constrained_ratio_still_admits_a_unit
        """
        port = _tiny_yard(flow)
        for serial in ("000019", "000020", "000021", "000022", "000023"):
            port.discharge(serial, model_line=MODEL_LINE_LX500)

        response = port.api.discharge_vehicle(
            port.vessel["id"],
            f.vehicle_payload(vin("000024"), model_line=MODEL_LINE_LX500),
            PLANNER,
        )
        validate_error(response, ERR_YARD_GRIDLOCK, 409)

        vessel = port.get_vessel()
        assert_subset(
            vessel, {"discharged_unit_count": 5, "discharge_status": VESSEL_DISCHARGING}
        )
