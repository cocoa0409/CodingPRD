"""Who may act: the reads everybody shares, the writes reserved to one role, the
consignee's own order, and the three places where two people are required.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    CLAIM_ACCEPTED_PENDING_SETTLEMENT,
    CLAIM_SETTLED,
    DAMAGE_ZONE_BODY_PANEL,
    DAMAGE_ZONE_INTERIOR,
    DUAL_INSPECTOR,
    DUAL_MANAGER,
    DUAL_SURVEYOR,
    DUAL_TECH,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    HOLD_LIFTED,
    HOLD_OPEN,
    HOLD_TYPE_STOP_SHIP,
    INSPECTION_OPEN,
    INSPECTOR,
    MANAGER,
    MANAGER_2,
    MODEL_LINE_EV900,
    MODEL_LINE_LX500,
    MODEL_LINE_TX300,
    PLANNER,
    RO_DELIVERED,
    RO_GATED_OUT,
    ROUTE_ZONE_A,
    SURVEYOR,
    SURVEY_SUBMITTED,
    TECHNICIAN,
    WO_INSTALLED,
    Vpc,
    assert_open_allocation_count,
    assert_pagination_meta,
    assert_stop_ship,
    assert_subset,
    dealer_user,
    factories as f,
    ids_of,
    ok,
    open_port,
    validate_error,
    validate_paginated,
    vin,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 10, 0)
CLAIMABLE_LINE = f.damage_line(DAMAGE_ZONE_BODY_PANEL, 25, 60_000)

PICKUP_WINDOW = {
    "pickup_window_start": "2026-08-04T08:00:00Z",
    "pickup_window_end": "2026-08-04T12:00:00Z",
}


class TestSharedReads:
    def test_all_six_roles_read_the_same_unit_and_see_the_same_vin(self, flow: Vpc):
        """Including the dealer, whose scoping bites only on delivery confirmation.

        PRD: "| GET | `/vpc/vehicles/{vehicleId}` | Read one unit with both state
        dimensions, dwell and charge fields. | `PortOperationsPlanner`,
        `DamageSurveyor`, `AccessoryTechnician`, `QualityInspector`,
        `DistributionManager`, `Dealer` |"

        PRD: "Note that this ownership comparison is scoped to delivery confirmation
        alone: a `Dealer` reading the unit collection or the release-order collection
        is not filtered to its own consignments and is not rejected for reading
        another dealer's order."

        Design: Corner/rbac/corner_shared_reads_are_open_to_every_declared_role
        """
        port = open_port(flow)
        dealer = port.create_dealer(
            dealer_code="D-ATL",
            name="Atlanta Motors",
            route_zone=ROUTE_ZONE_A,
            distance_miles=100,
            allocation_quota=2,
        )
        unit = port.discharge("000601", model_line=MODEL_LINE_EV900)

        readers = [
            PLANNER,
            SURVEYOR,
            TECHNICIAN,
            INSPECTOR,
            MANAGER,
            dealer_user(dealer["id"]),
        ]
        seen = [ok(port.api.get_vehicle(unit["id"], reader)) for reader in readers]

        assert len(seen) == 6
        for record in seen:
            assert record["id"] == unit["id"]
            assert record["vin"] == vin("000601")


class TestRoleExclusiveWrites:
    def test_a_dealer_cannot_hold_and_an_inspector_cannot_claim(self, flow: Vpc):
        """Both refusals land before any business condition is consulted.

        PRD: "| POST | `/vpc/processing-centers/{centerId}/hold-orders` | Apply a
        recall or stop-ship hold to units in the yard before release, by model line
        or by single VIN. | `DistributionManager` |"

        PRD: "| POST | `/vpc/damage-surveys/{surveyId}/claims` | File a
        transportation damage claim from a submitted survey. Guarded by the survey
        version expectation. | `DamageSurveyor` |"

        Design: Corner/rbac/corner_roles_are_refused_operations_exclusive_to_other_roles
        """
        port = open_port(flow)
        dealer = port.create_dealer(
            dealer_code="D-ATL",
            name="Atlanta Motors",
            route_zone=ROUTE_ZONE_A,
            distance_miles=100,
            allocation_quota=2,
        )
        unit = port.discharge("000602", model_line=MODEL_LINE_TX300)
        survey = port.surveyed(unit["id"], [CLAIMABLE_LINE])
        assert survey["severity_index"] == 30

        dealer_hold = port.api.apply_hold(
            port.center["id"],
            f.model_line_hold_payload(
                MODEL_LINE_TX300,
                hold_type=HOLD_TYPE_STOP_SHIP,
                reference_code="SS-2026-9",
            ),
            dealer_user(dealer["id"]),
        )
        validate_error(dealer_hold, ERR_FORBIDDEN_ROLE, 403)

        inspector_claim = port.api.file_claim(
            survey["id"], f.claim_payload(survey["version"]), INSPECTOR
        )
        validate_error(inspector_claim, ERR_FORBIDDEN_ROLE, 403)

        _, hold_meta = validate_paginated(
            port.api.list_holds(MANAGER, params={"processing_center_id": port.center["id"]})
        )
        assert_pagination_meta(hold_meta, total_count=0)
        _, claim_meta = validate_paginated(
            port.api.list_claims(MANAGER, params={"damage_survey_id": survey["id"]})
        )
        assert_pagination_meta(claim_meta, total_count=0)

        assert port.get_survey(survey["id"])["status"] == SURVEY_SUBMITTED
        assert_stop_ship(
            port.get_vehicle(unit["id"]), blocked=False, blocking_hold_order_id=None
        )


def _gated_out_order_for_one_of_two_dealers(flow: Vpc) -> Dict[str, Any]:
    """One order sitting in ``GATED_OUT``, owned by D-OWN, with D-OTHER standing by."""
    port = open_port(flow)
    owner = port.create_dealer(
        dealer_code="D-OWN",
        name="Owner Motors",
        route_zone=ROUTE_ZONE_A,
        distance_miles=100,
        allocation_quota=5,
    )
    other = port.create_dealer(
        dealer_code="D-OTHER",
        name="Other Motors",
        route_zone=ROUTE_ZONE_A,
        distance_miles=120,
        allocation_quota=5,
    )
    port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["A"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=4,
        concurrent_load_capacity=2,
    )
    ready = port.shipping_ready_unit(
        "000603", model_line=MODEL_LINE_EV900, line_items=[CLEAN_LINE]
    )
    order = port.allocate(ready["id"], owner["id"], ready["version"], **PICKUP_WINDOW)
    port.set_clock("2026-08-04T08:00:00Z")
    port.dispatch(order["id"])
    gated = port.gate_out(order["id"])
    return {
        "port": port,
        "owner_id": owner["id"],
        "other_id": other["id"],
        "order_id": order["id"],
        "gated": gated,
    }


class TestConsigneeOwnership:
    def test_only_the_owning_dealer_may_acknowledge_the_delivery(self, flow: Vpc):
        """The stranger's role is allowed; the stranger's identity is not.

        PRD: "Only the consignee may do it: the acting `X-User-ID` must equal the
        order's `dealer_id`, and any other dealer is refused with
        `ERR_NOT_RESOURCE_OWNER`."

        PRD: "10. Resource ownership for a `Dealer` — `ERR_NOT_RESOURCE_OWNER`
        (403)."

        Design: Corner/rbac/corner_dealer_cannot_confirm_another_dealers_release_order
        """
        scenario = _gated_out_order_for_one_of_two_dealers(flow)
        port = scenario["port"]

        assert scenario["gated"]["status"] == RO_GATED_OUT

        stranger = port.api.confirm_delivery(
            scenario["order_id"], dealer_user(scenario["other_id"])
        )
        validate_error(stranger, ERR_NOT_RESOURCE_OWNER, 403)
        assert port.get_release_order(scenario["order_id"])["status"] == RO_GATED_OUT
        assert_open_allocation_count(port.get_dealer(scenario["other_id"]), 0)

        delivered = port.confirm_delivery(scenario["order_id"], scenario["owner_id"])

        assert delivered["status"] == RO_DELIVERED
        assert delivered["dealer_id"] == scenario["owner_id"]


class TestInspectionIndependence:
    def test_the_installer_cannot_open_the_inspection_on_their_own_unit(self, flow: Vpc):
        """A second inspector opens it on the very next call.

        PRD: "The first protects inspection independence: the `QualityInspector`
        opening an inspection on a unit must not be the operator recorded as
        `installed_by_user_id` on any accessory work order of that unit whose status
        is `INSTALLED`, nor on any work order that is back in `KITTED` after a
        reopen."

        PRD: "The only gate on opening is the independence rule of §2.11: an
        inspector who is on record as having installed accessories on this unit is
        turned away with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/corner_inspector_who_installed_the_accessory_cannot_open_the_inspection
        """
        port = open_port(flow)
        unit = port.discharge(
            "000604", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY"
        )
        port.surveyed(unit["id"], [CLEAN_LINE])
        kit = port.create_kit(
            kit_code="K-ALLOY",
            program_code="PIO-ALLOY",
            received_qty_total=4,
            unit_cost_cents=24_000,
            install_minutes_per_unit=45,
        )
        work_order = port.plan_work_order(unit["id"], kit["id"], 1, DUAL_TECH)
        port.kit_work_order(work_order["id"], DUAL_TECH)
        installed = port.install_work_order(work_order["id"], DUAL_TECH)
        assert_subset(
            installed,
            {"status": WO_INSTALLED, "installed_by_user_id": DUAL_TECH.user_id},
        )

        refused = port.api.open_inspection(unit["id"], DUAL_INSPECTOR)
        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)

        accepted = port.open_inspection(unit["id"], INSPECTOR)

        assert_subset(
            accepted, {"status": INSPECTION_OPEN, "inspector_user_id": INSPECTOR.user_id}
        )
        rows, meta = validate_paginated(
            port.api.list_inspections(INSPECTOR, params={"vehicle_id": unit["id"]})
        )
        assert_pagination_meta(meta, total_count=1)
        assert ids_of(rows) == [accepted["id"]]


class TestHoldGovernance:
    def test_the_applier_cannot_lift_and_the_cascade_waits_for_the_second_manager(
        self, flow: Vpc
    ):
        """The refused lift leaves both the hold and the block exactly as they were.

        PRD: "The second protects hold governance: the `DistributionManager` lifting
        a hold order must not be the one recorded as its `applied_by_user_id`."

        PRD: "Unblocking is careful about overlapping campaigns: for every unit whose
        `blocking_hold_order_id` points at the hold being lifted, if no other open
        hold still covers that unit then `stop_ship_blocked` returns to false and
        `blocking_hold_order_id` returns to null; but if another open hold does still
        cover it, the unit stays blocked and `blocking_hold_order_id` is repointed to
        the remaining open hold with the earliest `created_at`."

        Design: Corner/rbac/corner_manager_who_applied_the_hold_cannot_lift_it
        """
        port = open_port(flow)
        unit = port.discharge("000605", model_line=MODEL_LINE_TX300)
        hold = port.apply_model_line_hold(
            MODEL_LINE_TX300,
            hold_type=HOLD_TYPE_STOP_SHIP,
            reference_code="SS-2026-9",
            user=MANAGER,
        )
        assert_subset(
            hold,
            {
                "status": HOLD_OPEN,
                "applied_by_user_id": MANAGER.user_id,
                "affected_vehicle_count": 1,
            },
        )

        refused = port.api.lift_hold(hold["id"], MANAGER)
        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)
        assert_subset(
            port.get_hold(hold["id"]), {"status": HOLD_OPEN, "lifted_by_user_id": None}
        )
        assert_stop_ship(
            port.get_vehicle(unit["id"]), blocked=True, blocking_hold_order_id=hold["id"]
        )

        lifted = port.lift_hold(hold["id"], MANAGER_2)

        assert_subset(
            lifted, {"status": HOLD_LIFTED, "lifted_by_user_id": MANAGER_2.user_id}
        )
        assert_stop_ship(
            port.get_vehicle(unit["id"]), blocked=False, blocking_hold_order_id=None
        )


class TestClaimRecovery:
    def test_the_filer_cannot_settle_the_claim_they_raised(self, flow: Vpc):
        """Same operator identifier, different role, still refused.

        PRD: "The third protects claim recovery: the `DistributionManager` settling a
        carrier claim must not be the one recorded as its `filed_by_user_id`."

        PRD: "Two guards apply beyond the state check: the settler must not be the
        claim's filer, per §2.11, and the settled amount must not exceed the claim's
        `recoverable_amount_cents` under its currently active basis — an overpayment
        attempt is rejected with `ERR_SETTLEMENT_EXCEEDS_RECOVERABLE`, which is the
        one HTTP 422 in this API."

        Design: Corner/rbac/corner_manager_who_filed_the_claim_cannot_settle_it
        """
        port = open_port(flow)
        unit = port.discharge("000606", model_line=MODEL_LINE_TX300)
        survey = port.surveyed(unit["id"], [CLAIMABLE_LINE], DUAL_SURVEYOR)
        claim = port.file_claim(survey["id"], survey["version"], DUAL_SURVEYOR)
        assert_subset(
            claim,
            {
                "filed_by_user_id": DUAL_SURVEYOR.user_id,
                "recoverable_amount_cents": 35_000,
            },
        )
        pending = port.accept_claim(claim["id"], MANAGER)
        assert pending["status"] == CLAIM_ACCEPTED_PENDING_SETTLEMENT

        refused = port.api.settle_claim(
            claim["id"], f.settle_payload(35_000), DUAL_MANAGER
        )
        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)
        assert_subset(
            port.get_claim(claim["id"]),
            {
                "status": CLAIM_ACCEPTED_PENDING_SETTLEMENT,
                "settled_amount_cents": None,
                "settled_by_user_id": None,
            },
        )

        settled = port.settle_claim(claim["id"], 35_000, MANAGER_2)

        assert_subset(
            settled,
            {
                "status": CLAIM_SETTLED,
                "settled_amount_cents": 35_000,
                "settled_by_user_id": MANAGER_2.user_id,
            },
        )
