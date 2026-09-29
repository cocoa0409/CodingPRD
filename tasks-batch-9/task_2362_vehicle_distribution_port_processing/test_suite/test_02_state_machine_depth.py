"""The non-linear edges: parallel unit dimensions, the claim dispute cycle and
the fork between an automatic and an escalated repair authorization.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    CLAIM_DISPUTED,
    CLAIM_FILED,
    DAMAGE_REPAIR_AUTHORIZED,
    DAMAGE_REPAIRED,
    DAMAGE_SURVEY_DAMAGE_OPEN,
    DAMAGE_ZONE_BODY_PANEL,
    DAMAGE_ZONE_GLASS,
    DAMAGE_ZONE_UNDERBODY,
    ERR_CLAIM_REVISION_LIMIT,
    INSPECTION_FAILED_STATUS,
    INSPECTION_PASSED_STATUS,
    MODEL_LINE_LX500,
    MODEL_LINE_TX300,
    OUTCOME_FAIL,
    PROC_ACCESSORY_IN_PROGRESS,
    REPAIR_AUTHORIZED_STATUS,
    REPAIR_ESCALATED_STATUS,
    SURVEYOR,
    TECHNICIAN,
    TIER_AUTO,
    TIER_ESCALATED,
    Vpc,
    assert_subset,
    assert_vehicle_dimensions,
    factories as f,
    open_port,
    validate_error,
)

MAJOR_LINES = [
    f.damage_line(DAMAGE_ZONE_BODY_PANEL, 40, 40_000),
    f.damage_line(DAMAGE_ZONE_GLASS, 30, 20_000),
]
CLAIMABLE_LINES = [
    f.damage_line(DAMAGE_ZONE_UNDERBODY, 34, 95_000),
    f.damage_line(DAMAGE_ZONE_GLASS, 30, 32_000),
]


# ==========================================================================
# the two unit dimensions and the rework cycle
# ==========================================================================
def _accessorized_unit_with_open_damage(flow: Vpc) -> Dict[str, Any]:
    """A unit carrying installed accessories while its damage is still open."""
    port = open_port(flow)
    unit = port.discharge("000006", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY")
    port.complete_voyage()
    kit = port.create_kit(
        kit_code="KIT-ALLOY-19",
        program_code="PIO-ALLOY",
        received_qty_total=10,
        unit_cost_cents=12_340,
        install_minutes_per_unit=24,
    )
    port.surveyed(unit["id"], MAJOR_LINES)
    order = port.installed_work_order(unit["id"], kit["id"], 2, TECHNICIAN)
    return {"port": port, "vehicle_id": unit["id"], "order": order}


class TestParallelDimensionsAndRework:
    def test_accessory_progress_and_damage_progress_advance_independently(self, flow: Vpc):
        """Installed accessories do not move the damage dimension, and repair
        completion does not move the processing dimension.

        PRD: "Because `damage_status` and `processing_status` are independent
        dimensions, a unit with open damage continues through accessory work and
        inspection normally."

        Design: Difficulty/non_linear_state_machine/vehicle_parallel_dimensions_and_inspection_rework_cycle
        """
        scenario = _accessorized_unit_with_open_damage(flow)
        port = scenario["port"]

        assert_vehicle_dimensions(
            port.get_vehicle(scenario["vehicle_id"]),
            processing_status=PROC_ACCESSORY_IN_PROGRESS,
            damage_status=DAMAGE_SURVEY_DAMAGE_OPEN,
        )

        repair = port.repair_order(scenario["vehicle_id"], 60_000)
        port.complete_repair(repair["id"], 58_000)

        assert_vehicle_dimensions(
            port.get_vehicle(scenario["vehicle_id"]),
            processing_status=PROC_ACCESSORY_IN_PROGRESS,
            damage_status=DAMAGE_REPAIRED,
        )

    def test_failed_reinspection_walks_the_processing_dimension_backwards_only(self, flow: Vpc):
        """The cyclic edge returns the unit to accessory work and counts a cycle.

        PRD: "Link two, caused by link one, returns the unit's processing
        dimension to `ACCESSORY_IN_PROGRESS` from `INSPECTION_PASSED` and
        increases the unit's `rework_cycle_count` by one — this is the cyclic
        edge of the processing dimension."

        Design: Difficulty/non_linear_state_machine/vehicle_parallel_dimensions_and_inspection_rework_cycle
        """
        scenario = _accessorized_unit_with_open_damage(flow)
        port = scenario["port"]
        repair = port.repair_order(scenario["vehicle_id"], 60_000)
        port.complete_repair(repair["id"], 58_000)

        first = port.pass_inspection(scenario["vehicle_id"])
        second = port.open_inspection(scenario["vehicle_id"])
        failed = port.complete_inspection(second["id"], OUTCOME_FAIL, 2)

        unit = port.get_vehicle(scenario["vehicle_id"])
        assert_vehicle_dimensions(
            unit,
            processing_status=PROC_ACCESSORY_IN_PROGRESS,
            damage_status=DAMAGE_REPAIRED,
        )
        assert unit["rework_cycle_count"] == 1
        assert port.get_inspection(first["id"])["status"] == INSPECTION_PASSED_STATUS
        assert failed["status"] == INSPECTION_FAILED_STATUS


# ==========================================================================
# the claim dispute and resubmission cycle
# ==========================================================================
def _disputed_claim(flow: Vpc) -> Dict[str, Any]:
    """A 112,000-cent claim the carrier has disputed at 100,000 cents."""
    port = open_port(flow)
    unit = port.discharge("000007", model_line=MODEL_LINE_TX300)
    survey = port.surveyed(unit["id"], CLAIMABLE_LINES)
    claim = port.file_claim(survey["id"], survey["version"])
    port.dispute_claim(claim["id"], 100_000)
    return {"port": port, "claim_id": claim["id"]}


class TestClaimRevisionCycle:
    def test_each_resubmission_returns_the_claim_to_filed_at_the_revised_amount(self, flow: Vpc):
        """Every revision advances the round, resets the claimed amount and
        clears the conceded amount.

        PRD: "On success `revision_round` increases by one,
        `claimed_amount_cents` becomes the revised amount,
        `disputed_amount_cents` is cleared back to null, and
        `recoverable_amount_cents` is recomputed under whichever basis the claim
        currently carries — a claim already latched to `REPAIR_ACTUAL` stays on
        actual cost through the revision."

        Design: Difficulty/non_linear_state_machine/carrier_claim_dispute_resubmit_cycle_returns_to_filed_until_ceiling
        """
        scenario = _disputed_claim(flow)
        port = scenario["port"]
        claim_id = scenario["claim_id"]

        first = port.resubmit_claim(claim_id, 100_000)
        assert_subset(
            first,
            {
                "status": CLAIM_FILED,
                "revision_round": 1,
                "claimed_amount_cents": 100_000,
                "recoverable_amount_cents": 75_000,
                "disputed_amount_cents": None,
            },
        )

        port.dispute_claim(claim_id, 90_000)
        second = port.resubmit_claim(claim_id, 90_000)
        assert_subset(second, {"revision_round": 2, "recoverable_amount_cents": 65_000})

        port.dispute_claim(claim_id, 80_000)
        third = port.resubmit_claim(claim_id, 80_000)
        assert_subset(third, {"revision_round": 3, "recoverable_amount_cents": 55_000})

    def test_a_fourth_revision_is_refused_and_leaves_the_claim_disputed(self, flow: Vpc):
        """Three completed revisions exhaust the ceiling.

        PRD: "And `revision_round`, which counts completed resubmissions and
        starts at 0, must still be below the ceiling of three revisions; a claim
        that has already used all three is refused with
        `ERR_CLAIM_REVISION_LIMIT`."

        Design: Difficulty/non_linear_state_machine/carrier_claim_dispute_resubmit_cycle_returns_to_filed_until_ceiling
        """
        scenario = _disputed_claim(flow)
        port = scenario["port"]
        claim_id = scenario["claim_id"]

        port.resubmit_claim(claim_id, 100_000)
        port.dispute_claim(claim_id, 90_000)
        port.resubmit_claim(claim_id, 90_000)
        port.dispute_claim(claim_id, 80_000)
        port.resubmit_claim(claim_id, 80_000)
        port.dispute_claim(claim_id, 70_000)

        response = port.api.resubmit_claim(claim_id, f.resubmit_payload(70_000), SURVEYOR)
        validate_error(response, ERR_CLAIM_REVISION_LIMIT, 409)

        assert_subset(
            port.get_claim(claim_id),
            {"status": CLAIM_DISPUTED, "revision_round": 3},
        )


# ==========================================================================
# the repair authorization fork
# ==========================================================================
def _claimed_unit(port: Vpc, serial: str) -> Dict[str, Any]:
    """A unit with a submitted claimable survey and a live carrier claim."""
    unit = port.discharge(serial, model_line=MODEL_LINE_LX500)
    survey = port.surveyed(unit["id"], CLAIMABLE_LINES)
    claim = port.file_claim(survey["id"], survey["version"])
    return {"vehicle_id": unit["id"], "claim_id": claim["id"]}


class TestRepairAuthorizationFork:
    def test_an_automatic_estimate_is_born_authorized_and_advances_the_damage(self, flow: Vpc):
        """Below the escalation threshold the estimator is also the authorizer.

        PRD: "An `AUTO` estimate is born already approved: the order is created
        in `AUTHORIZED`, `authorized_by_user_id` is written with the same
        operator who supplied the estimate, and the unit's damage dimension
        advances `SURVEY_DAMAGE_OPEN → REPAIR_AUTHORIZED`."

        Design: Difficulty/non_linear_state_machine/repair_order_fork_to_escalated_has_divergent_side_effect_set
        """
        port = open_port(flow)
        unit = _claimed_unit(port, "000008")

        order = port.repair_order(unit["vehicle_id"], 149_999, carrier_claim_id=unit["claim_id"])

        assert_subset(
            order,
            {"authorization_tier": TIER_AUTO, "status": REPAIR_AUTHORIZED_STATUS},
        )
        assert order["authorized_by_user_id"] == order["estimated_by_user_id"]
        assert_vehicle_dimensions(
            port.get_vehicle(unit["vehicle_id"]), damage_status=DAMAGE_REPAIR_AUTHORIZED
        )

    def test_an_escalated_estimate_holds_the_damage_dimension_until_a_manager_acts(self, flow: Vpc):
        """Escalation leaves the authorizer unset and the unit damage-blocked
        until adjudication rejoins the automatic path.

        PRD: "An `ESCALATED` estimate is created in `ESCALATED`,
        `authorized_by_user_id` stays null, and the unit's damage dimension is
        **not** advanced — it remains in `SURVEY_DAMAGE_OPEN`, and the unit stays
        damage-blocked until a manager acts."

        Design: Difficulty/non_linear_state_machine/repair_order_fork_to_escalated_has_divergent_side_effect_set
        """
        port = open_port(flow)
        unit = _claimed_unit(port, "000009")

        order = port.repair_order(unit["vehicle_id"], 220_000, carrier_claim_id=unit["claim_id"])

        assert_subset(
            order,
            {
                "authorization_tier": TIER_ESCALATED,
                "status": REPAIR_ESCALATED_STATUS,
                "authorized_by_user_id": None,
            },
        )
        assert_vehicle_dimensions(
            port.get_vehicle(unit["vehicle_id"]), damage_status=DAMAGE_SURVEY_DAMAGE_OPEN
        )

        adjudicated = port.authorize_repair(order["id"])
        assert adjudicated["status"] == REPAIR_AUTHORIZED_STATUS
        assert_vehicle_dimensions(
            port.get_vehicle(unit["vehicle_id"]), damage_status=DAMAGE_REPAIR_AUTHORIZED
        )
