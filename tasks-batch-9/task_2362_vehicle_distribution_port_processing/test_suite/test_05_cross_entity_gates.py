"""Transitions whose legality is decided by the state of a *different* record:
the voyage behind the unit, the hold covering it, and the claim behind its spend.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    CLAIM_FILED,
    DAMAGE_NONE,
    DAMAGE_REPAIR_AUTHORIZED,
    DAMAGE_SURVEY_DAMAGE_OPEN,
    DAMAGE_ZONE_GLASS,
    DAMAGE_ZONE_INTERIOR,
    DAMAGE_ZONE_UNDERBODY,
    ERR_CLAIM_REQUIRED,
    ERR_VEHICLE_STOP_SHIP_BLOCKED,
    ERR_VESSEL_DISCHARGE_INCOMPLETE,
    HOLD_LIFTED,
    HOLD_TYPE_STOP_SHIP,
    INSPECTOR,
    MANAGER_2,
    MODEL_LINE_EV900,
    MODEL_LINE_LX500,
    MODEL_LINE_TX300,
    PROC_GATED_OUT,
    PROC_INSPECTION_PASSED,
    PROC_SHIPPING_READY,
    REPAIR_AUTHORIZED_STATUS,
    REPAIR_ESCALATED_STATUS,
    RO_GATED_OUT,
    RO_RELEASED,
    ROUTE_ZONE_B,
    SURVEY_CLAIMED,
    VESSEL_DISCHARGE_COMPLETE,
    VESSEL_DISCHARGING,
    YARD_DEPARTED,
    Vpc,
    assert_iso_instant,
    assert_stop_ship,
    assert_subset,
    assert_vehicle_dimensions,
    factories as f,
    open_port,
    validate_error,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 20, 0)
CLAIMABLE_LINES = [
    f.damage_line(DAMAGE_ZONE_UNDERBODY, 34, 95_000),
    f.damage_line(DAMAGE_ZONE_GLASS, 30, 32_000),
]


# ==========================================================================
# preparation depends on the voyage, not on the unit alone
# ==========================================================================
def _passed_unit_on_an_open_voyage(flow: Vpc) -> Dict[str, Any]:
    """An inspection-passed unit whose voyage is still discharging."""
    port = open_port(flow)
    unit = port.discharge("000025", model_line=MODEL_LINE_TX300)
    port.surveyed(unit["id"], [CLEAN_LINE])
    port.pass_inspection(unit["id"])
    return {"port": port, "vehicle_id": unit["id"]}


class TestPreparationRequiresAClosedVoyage:
    def test_an_open_voyage_refuses_preparation_and_leaves_the_unit_where_it_was(self, flow: Vpc):
        """The unit itself is ready; its voyage is not.

        PRD: "The unit's discharging voyage must have reached
        `DISCHARGE_COMPLETE`; a unit off a voyage still `SCHEDULED` or
        `DISCHARGING` is refused with `ERR_VESSEL_DISCHARGE_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/prep_to_shipping_condition_requires_vessel_discharge_complete
        """
        scenario = _passed_unit_on_an_open_voyage(flow)
        port = scenario["port"]

        assert port.get_vessel()["discharge_status"] == VESSEL_DISCHARGING

        response = port.api.prep_complete(scenario["vehicle_id"], INSPECTOR)
        validate_error(response, ERR_VESSEL_DISCHARGE_INCOMPLETE, 409)

        assert_vehicle_dimensions(
            port.get_vehicle(scenario["vehicle_id"]),
            processing_status=PROC_INSPECTION_PASSED,
            damage_status=DAMAGE_NONE,
        )

    def test_closing_the_voyage_makes_the_same_request_succeed(self, flow: Vpc):
        """Closing the voyage is what makes its units eligible for preparation.

        PRD: "Closing has two forward consequences: the berth window stops
        participating in the conflict comparison above, freeing the berth for the
        next voyage; and every unit off that voyage becomes eligible for
        preparation to shipping condition, which §3.6 revisits."

        Design: Difficulty/cross_entity_state_dependency/prep_to_shipping_condition_requires_vessel_discharge_complete
        """
        scenario = _passed_unit_on_an_open_voyage(flow)
        port = scenario["port"]
        port.api.prep_complete(scenario["vehicle_id"], INSPECTOR)

        vessel = port.complete_voyage()
        assert vessel["discharge_status"] == VESSEL_DISCHARGE_COMPLETE

        prepared = port.prep_complete(scenario["vehicle_id"])
        assert_vehicle_dimensions(prepared, processing_status=PROC_SHIPPING_READY)


# ==========================================================================
# gate-out depends on the hold covering the unit
# ==========================================================================
def _released_unit_under_a_hold(flow: Vpc) -> Dict[str, Any]:
    """A dispatched unit frozen in place by a later model-line stop-ship."""
    port = open_port(flow)
    unit = port.discharge("000026", model_line=MODEL_LINE_LX500)
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
    port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["B"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=3,
        concurrent_load_capacity=2,
    )
    order = port.allocate(
        ready["id"],
        dealer["id"],
        ready["version"],
        pickup_window_start="2026-08-05T08:00:00Z",
        pickup_window_end="2026-08-05T12:00:00Z",
    )
    released = port.dispatch(order["id"])
    hold = port.apply_model_line_hold(
        MODEL_LINE_LX500, hold_type=HOLD_TYPE_STOP_SHIP, reference_code="SS-2026-91"
    )
    return {
        "port": port,
        "vehicle_id": unit["id"],
        "order_id": order["id"],
        "released": released,
        "hold_id": hold["id"],
    }


class TestGateOutUnderAHold:
    def test_a_released_order_is_frozen_rather_than_cancelled_and_cannot_gate_out(self, flow: Vpc):
        """The hold cascade leaves a released order alone but bars the gate.

        PRD: "An order that has already reached `RELEASED` is emphatically **not**
        cancelled — the unit is frozen in place instead, and its gate-out is
        refused with `ERR_VEHICLE_STOP_SHIP_BLOCKED` for as long as the hold
        stands."

        Design: Difficulty/cross_entity_state_dependency/gate_out_blocked_by_open_hold_and_permitted_after_lift
        """
        scenario = _released_unit_under_a_hold(flow)
        port = scenario["port"]

        assert port.get_release_order(scenario["order_id"])["status"] == RO_RELEASED
        assert_stop_ship(
            port.get_vehicle(scenario["vehicle_id"]),
            blocked=True,
            blocking_hold_order_id=scenario["hold_id"],
        )

        response = port.api.gate_out(scenario["order_id"], MANAGER_2)
        validate_error(response, ERR_VEHICLE_STOP_SHIP_BLOCKED, 409)

        assert port.get_release_order(scenario["order_id"])["status"] == RO_RELEASED

    def test_lifting_the_hold_readmits_the_gate_out_on_the_same_order(self, flow: Vpc):
        """A frozen order needs no re-allocation once the campaign closes.

        PRD: "Orders that were merely frozen in `RELEASED` need no re-allocation:
        once the hold is lifted, their gate-out is admitted again."

        Design: Difficulty/cross_entity_state_dependency/gate_out_blocked_by_open_hold_and_permitted_after_lift
        """
        scenario = _released_unit_under_a_hold(flow)
        port = scenario["port"]
        settled_freight = scenario["released"]["freight_total_cents"]
        port.api.gate_out(scenario["order_id"], MANAGER_2)

        lifted = port.lift_hold(scenario["hold_id"], MANAGER_2)
        assert lifted["status"] == HOLD_LIFTED
        assert_stop_ship(
            port.get_vehicle(scenario["vehicle_id"]), blocked=False, blocking_hold_order_id=None
        )

        gated = port.gate_out(scenario["order_id"], MANAGER_2)
        assert_subset(
            gated, {"status": RO_GATED_OUT, "freight_total_cents": settled_freight}
        )
        unit = port.get_vehicle(scenario["vehicle_id"])
        assert_vehicle_dimensions(
            unit, processing_status=PROC_GATED_OUT, yard_presence=YARD_DEPARTED
        )
        assert_iso_instant(unit["gate_out_at"])


# ==========================================================================
# escalated authorization depends on the claim behind the spend
# ==========================================================================
def _escalated_repair_without_a_claim(flow: Vpc) -> Dict[str, Any]:
    """A 220,000-cent escalated estimate on a unit whose claim is not yet filed."""
    port = open_port(flow)
    unit = port.discharge("000027", model_line=MODEL_LINE_EV900)
    survey = port.surveyed(unit["id"], CLAIMABLE_LINES)
    order = port.repair_order(unit["id"], 220_000)
    return {
        "port": port,
        "vehicle_id": unit["id"],
        "survey": survey,
        "order_id": order["id"],
    }


class TestEscalatedAuthorizationRequiresAClaim:
    def test_authorization_without_a_live_claim_is_refused(self, flow: Vpc):
        """The escalated tier carries a precondition the automatic tier does not.

        PRD: "`AUTHORIZE` carries one additional precondition that the automatic
        tier does not: there must be a live carrier claim behind the spend,
        meaning a claim on this unit's survey whose status is `FILED`,
        `ACCEPTED_PENDING_SETTLEMENT` or `DISPUTED`."

        Design: Difficulty/cross_entity_state_dependency/escalated_repair_authorization_requires_a_live_carrier_claim
        """
        scenario = _escalated_repair_without_a_claim(flow)
        port = scenario["port"]

        assert port.get_vehicle(scenario["vehicle_id"])["claim_mandatory"] is True

        response = port.api.authorize_repair(
            scenario["order_id"], f.authorize_payload(), MANAGER_2
        )
        validate_error(response, ERR_CLAIM_REQUIRED, 409)

        assert port.get_repair_order(scenario["order_id"])["status"] == REPAIR_ESCALATED_STATUS
        assert_vehicle_dimensions(
            port.get_vehicle(scenario["vehicle_id"]), damage_status=DAMAGE_SURVEY_DAMAGE_OPEN
        )

    def test_filing_the_claim_opens_the_authorization_and_advances_the_damage(self, flow: Vpc):
        """With a recovery path on record the escalated order rejoins the
        automatic path.

        PRD: "On `AUTHORIZE` the order moves `ESCALATED → AUTHORIZED`,
        `authorized_by_user_id` is written with the manager's `X-User-ID`, and the
        unit's damage dimension advances `SURVEY_DAMAGE_OPEN →
        REPAIR_AUTHORIZED`; the two escalated-to-authorized paths therefore rejoin
        the automatic path at the same place."

        Design: Difficulty/cross_entity_state_dependency/escalated_repair_authorization_requires_a_live_carrier_claim
        """
        scenario = _escalated_repair_without_a_claim(flow)
        port = scenario["port"]
        port.api.authorize_repair(scenario["order_id"], f.authorize_payload(), MANAGER_2)

        claim = port.file_claim(scenario["survey"]["id"], scenario["survey"]["version"])
        assert claim["status"] == CLAIM_FILED
        assert port.get_survey(scenario["survey"]["id"])["status"] == SURVEY_CLAIMED

        authorized = port.authorize_repair(scenario["order_id"], MANAGER_2)
        assert_subset(authorized, {"status": REPAIR_AUTHORIZED_STATUS})
        assert authorized["authorized_by_user_id"] == MANAGER_2.user_id
        assert_vehicle_dimensions(
            port.get_vehicle(scenario["vehicle_id"]), damage_status=DAMAGE_REPAIR_AUTHORIZED
        )
