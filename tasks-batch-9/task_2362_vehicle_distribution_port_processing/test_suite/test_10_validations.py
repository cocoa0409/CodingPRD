"""Admission rules: the boundary instant, the empty voyage, the reused key, the
claim gates, the stock shortfall, the damage gate and the order the bands run in.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    BASIS_SURVEY_BASED,
    CLAIM_ACCEPTED_PENDING_SETTLEMENT,
    CLAIM_FILED,
    CLAIM_SETTLED,
    DAMAGE_NONE,
    DAMAGE_REPAIR_AUTHORIZED,
    DAMAGE_REPAIRED,
    DAMAGE_SURVEY_DAMAGE_OPEN,
    DAMAGE_ZONE_BODY_PANEL,
    DAMAGE_ZONE_INTERIOR,
    DAMAGE_ZONE_UNDERBODY,
    ERR_BERTH_WINDOW_NOT_OPEN,
    ERR_CLAIM_ALREADY_OPEN,
    ERR_CLAIM_NOT_WARRANTED,
    ERR_CLAIM_REQUIRED,
    ERR_DUPLICATE_KEY,
    ERR_KIT_INSUFFICIENT,
    ERR_NO_UNITS_DISCHARGED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SETTLEMENT_EXCEEDS_RECOVERABLE,
    ERR_VEHICLE_DAMAGE_BLOCKED,
    ERR_VEHICLE_NOT_FOUND,
    INSPECTION_PASSED_STATUS,
    INSPECTOR,
    MANAGER,
    MISSING_DEALER_UUID,
    MISSING_VEHICLE_UUID,
    MODEL_LINE_LX500,
    MODEL_LINE_TX300,
    PLANNER,
    PROC_DISCHARGED,
    PROC_INSPECTION_PASSED,
    PROC_SHIPPING_READY,
    PROC_SURVEYED,
    REFERENCE_WINDOW_END,
    REFERENCE_WINDOW_START,
    REPAIR_AUTHORIZED_STATUS,
    REPAIR_COMPLETED_STATUS,
    SURVEYOR,
    SURVEY_CLAIMED,
    SURVEY_SUBMITTED,
    TECHNICIAN,
    TIER_AUTO,
    VESSEL_DISCHARGE_COMPLETE,
    VESSEL_DISCHARGING,
    VESSEL_SCHEDULED,
    WO_PLANNED,
    Vpc,
    assert_center_ledgers,
    assert_kit_ledger,
    assert_pagination_meta,
    assert_subset,
    assert_vehicle_dimensions,
    factories as f,
    open_port,
    validate_error,
    validate_paginated,
    vin,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 10, 0)
BODY_PANEL_LINE = f.damage_line(DAMAGE_ZONE_BODY_PANEL, 25, 40_000)


class TestBerthWindowOpeningTime:
    def test_one_minute_early_is_refused_and_the_exact_instant_is_admitted(self, flow: Vpc):
        """The gate is inclusive at the reserved start and closed a minute before.

        PRD: "Starting discharge advances the voyage from `SCHEDULED` to
        `DISCHARGING`, and is admitted only once the logical clock has reached the
        reserved `berth_window_start` — at or after that instant is acceptable,
        before it is rejected with `ERR_BERTH_WINDOW_NOT_OPEN`."

        Design: Corner/validations/corner_start_discharge_before_the_berth_window_opens_is_rejected
        """
        flow.set_clock("2026-08-01T00:00:00Z")
        center = flow.create_center()
        berth = flow.create_berth(center["id"])
        vessel = flow.create_vessel(
            center["id"],
            berth["id"],
            berth_window_start=REFERENCE_WINDOW_START,
            berth_window_end=REFERENCE_WINDOW_END,
            declared_unit_count=4,
        )

        flow.set_clock("2026-08-01T05:59:00Z")
        early = flow.api.start_discharge(vessel["id"], PLANNER)
        validate_error(early, ERR_BERTH_WINDOW_NOT_OPEN, 409)
        assert flow.get_vessel(vessel["id"])["discharge_status"] == VESSEL_SCHEDULED

        flow.set_clock(REFERENCE_WINDOW_START)
        on_time = flow.start_discharge(vessel["id"])

        assert on_time["discharge_status"] == VESSEL_DISCHARGING


class TestVoyageClosureNeedsAUnit:
    def test_an_empty_voyage_cannot_be_closed_but_one_unit_is_enough(self, flow: Vpc):
        """The same closing call flips from refusal to success on the first unit.

        PRD: "Closing the voyage advances `DISCHARGING` to `DISCHARGE_COMPLETE` and
        requires that `discharged_unit_count` be at least 1 — a voyage that
        discharged nothing cannot be closed, and the attempt yields
        `ERR_NO_UNITS_DISCHARGED`."

        Design: Corner/validations/corner_complete_discharge_with_zero_units_is_rejected
        """
        port = open_port(flow)
        assert port.get_vessel()["discharged_unit_count"] == 0

        empty = port.api.complete_discharge(port.vessel["id"], PLANNER)
        validate_error(empty, ERR_NO_UNITS_DISCHARGED, 409)
        assert port.get_vessel()["discharge_status"] == VESSEL_DISCHARGING

        unit = port.discharge("000401", model_line=MODEL_LINE_LX500)
        closed = port.complete_voyage()

        assert_subset(
            closed,
            {"discharge_status": VESSEL_DISCHARGE_COMPLETE, "discharged_unit_count": 1},
        )
        assert_vehicle_dimensions(
            port.get_vehicle(unit["id"]), processing_status=PROC_DISCHARGED
        )


class TestUniquenessOnCreate:
    def test_a_reused_vin_and_a_reused_port_code_share_one_code(self, flow: Vpc):
        """Neither duplicate attempt leaves a second row behind.

        PRD: "Uniqueness is enforced on creation and reported as `ERR_DUPLICATE_KEY`
        (HTTP 409)."

        PRD: "A center's `port_code` is unique system-wide, as are a dealer's
        `dealer_code` and a carrier's `carrier_code` and a unit's `vin`."

        Design: Corner/validations/corner_duplicate_vin_and_duplicate_port_code_return_duplicate_key
        """
        port = open_port(flow)
        first = port.discharge("000402", model_line=MODEL_LINE_LX500)

        same_vin = port.api.discharge_vehicle(
            port.vessel["id"],
            f.vehicle_payload(vin("000402"), model_line=MODEL_LINE_TX300),
            PLANNER,
        )
        validate_error(same_vin, ERR_DUPLICATE_KEY, 409)

        same_port_code = port.api.create_center(
            f.center_payload(
                name="Newport VPC Annex",
                yard_capacity_slots=10,
                daily_storage_rate_cents=1_200,
                labor_rate_cents_per_hour=8_000,
                fuel_surcharge_pct=0.05,
            ),
            PLANNER,
        )
        validate_error(same_port_code, ERR_DUPLICATE_KEY, 409)

        units, unit_meta = validate_paginated(port.api.list_vehicles(PLANNER))
        assert_pagination_meta(unit_meta, total_count=1)
        assert units[0]["id"] == first["id"]

        _, center_meta = validate_paginated(port.api.list_centers(PLANNER))
        assert_pagination_meta(center_meta, total_count=1)
        assert port.get_vessel()["discharged_unit_count"] == 1


class TestClaimSeverityThreshold:
    def test_a_cosmetic_survey_one_point_short_cannot_be_claimed(self, flow: Vpc):
        """24 points of interior damage is cosmetic, and cosmetic is not recoverable.

        PRD: "Filing is refused when the survey's `severity_index` is below 25, with
        `ERR_CLAIM_NOT_WARRANTED` — cosmetic damage is not recoverable."

        PRD: "The damage dimension moves independently: when the index is 25 or
        more, `damage_status` advances `NONE → SURVEY_DAMAGE_OPEN` and
        `damage_opened_at` is stamped from the logical clock; when the index is below
        25, the damage is treated as cosmetic and `damage_status` stays `NONE` with
        `damage_opened_at` left null."

        Design: Corner/validations/corner_claim_filing_below_the_damage_threshold_is_not_warranted
        """
        port = open_port(flow)
        unit = port.discharge("000403", model_line=MODEL_LINE_LX500)
        survey = port.surveyed(
            unit["id"], [f.damage_line(DAMAGE_ZONE_INTERIOR, 24, 30_000)]
        )

        assert survey["severity_index"] == 24
        assert_vehicle_dimensions(
            port.get_vehicle(unit["id"]), damage_status=DAMAGE_NONE
        )

        refused = port.api.file_claim(
            survey["id"], f.claim_payload(survey["version"]), SURVEYOR
        )
        validate_error(refused, ERR_CLAIM_NOT_WARRANTED, 409)

        assert port.get_survey(survey["id"])["status"] == SURVEY_SUBMITTED
        _, claim_meta = validate_paginated(
            port.api.list_claims(MANAGER, params={"damage_survey_id": survey["id"]})
        )
        assert_pagination_meta(claim_meta, total_count=0)


class TestOneLiveClaimPerSurvey:
    def test_a_second_filing_over_a_live_claim_is_refused(self, flow: Vpc):
        """The self-transition exists for denied predecessors, not for live ones.

        PRD: "It is also refused with `ERR_CLAIM_ALREADY_OPEN` when any claim
        already exists for that survey in `FILED`, `ACCEPTED_PENDING_SETTLEMENT`,
        `DISPUTED` or `SETTLED`."

        PRD: "A survey in `CLAIMED` can be filed against a second time, but only in
        one circumstance: every claim already attached to it must be in `DENIED`."

        Design: Corner/validations/corner_second_live_claim_on_the_same_survey_is_rejected
        """
        port = open_port(flow)
        unit = port.discharge("000404", model_line=MODEL_LINE_TX300)
        survey = port.surveyed(unit["id"], [BODY_PANEL_LINE])
        claim = port.file_claim(survey["id"], survey["version"])

        assert_subset(
            claim,
            {
                "status": CLAIM_FILED,
                "recoverable_basis": BASIS_SURVEY_BASED,
                "recoverable_amount_cents": 15_000,
            },
        )
        current = port.get_survey(survey["id"])
        assert current["status"] == SURVEY_CLAIMED

        second = port.api.file_claim(
            survey["id"], f.claim_payload(current["version"]), SURVEYOR
        )
        validate_error(second, ERR_CLAIM_ALREADY_OPEN, 409)

        claims, claim_meta = validate_paginated(
            port.api.list_claims(MANAGER, params={"damage_survey_id": survey["id"]})
        )
        assert_pagination_meta(claim_meta, total_count=1)
        assert claims[0]["id"] == claim["id"]


def _accepted_claim_of_eighty_thousand(flow: Vpc) -> Dict[str, Any]:
    """A claim capped to 80,000 cents, accepted and awaiting settlement."""
    port = open_port(flow)
    unit = port.discharge("000405", model_line=MODEL_LINE_LX500)
    survey = port.surveyed(
        unit["id"], [f.damage_line(DAMAGE_ZONE_BODY_PANEL, 25, 100_000)]
    )
    claim = port.file_claim(survey["id"], survey["version"])
    accepted = port.accept_claim(claim["id"])
    return {"port": port, "survey": survey, "claim": claim, "accepted": accepted}


class TestSettlementCeiling:
    def test_one_cent_over_the_recoverable_figure_is_the_single_unprocessable_entity(
        self, flow: Vpc
    ):
        """55,001 is refused, 55,000 settles — the ceiling is inclusive.

        PRD: "For each line of the originating survey, take its
        `repair_estimate_cents` but never more than 80,000 cents from any single
        line — an individual damage line cannot claim more than eight hundred
        dollars regardless of what the estimate says."

        PRD: "Two guards apply beyond the state check: the settler must not be the
        claim's filer, per §2.11, and the settled amount must not exceed the claim's
        `recoverable_amount_cents` under its currently active basis — an overpayment
        attempt is rejected with `ERR_SETTLEMENT_EXCEEDS_RECOVERABLE`, which is the
        one HTTP 422 in this API."

        PRD: "`settled_amount_cents` is null until settlement occurs."

        Design: Corner/validations/corner_settlement_above_the_recoverable_ceiling_is_rejected
        """
        scenario = _accepted_claim_of_eighty_thousand(flow)
        port = scenario["port"]
        claim_id = scenario["claim"]["id"]

        assert scenario["survey"]["claimed_amount_cents"] == 80_000
        assert_subset(
            scenario["accepted"],
            {
                "status": CLAIM_ACCEPTED_PENDING_SETTLEMENT,
                "recoverable_basis": BASIS_SURVEY_BASED,
                "recoverable_amount_cents": 55_000,
                "settled_amount_cents": None,
            },
        )

        over = port.api.settle_claim(claim_id, f.settle_payload(55_001), MANAGER)
        validate_error(over, ERR_SETTLEMENT_EXCEEDS_RECOVERABLE, 422)
        assert_subset(
            port.get_claim(claim_id),
            {
                "status": CLAIM_ACCEPTED_PENDING_SETTLEMENT,
                "settled_amount_cents": None,
            },
        )

        settled = port.settle_claim(claim_id, 55_000)

        assert_subset(
            settled, {"status": CLAIM_SETTLED, "settled_amount_cents": 55_000}
        )
        assert settled["settled_by_user_id"] == MANAGER.user_id


class TestKitStockSufficiency:
    def test_a_single_unit_kit_cannot_serve_a_two_unit_work_order(self, flow: Vpc):
        """The shortfall reserves nothing and moves nothing.

        PRD: "A work order in `PLANNED` advances to `KITTED` provided the kit's
        `available_qty` is greater than or equal to the work order's `qty` —
        equality is sufficient, and a shortfall is refused with
        `ERR_KIT_INSUFFICIENT`."

        Design: Corner/validations/corner_kitting_beyond_available_kit_quantity_is_rejected
        """
        port = open_port(flow)
        unit = port.discharge(
            "000406", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY"
        )
        port.surveyed(unit["id"], [CLEAN_LINE])
        kit = port.create_kit(
            kit_code="K-SCARCE",
            program_code="PIO-ALLOY",
            received_qty_total=1,
            unit_cost_cents=24_000,
            install_minutes_per_unit=45,
        )
        assert_kit_ledger(
            kit,
            on_hand_qty=1,
            reserved_qty=0,
            available_qty=1,
            consumed_qty=0,
            received_qty_total=1,
        )

        work_order = port.plan_work_order(unit["id"], kit["id"], 2)
        shortfall = port.api.kit_work_order(work_order["id"], TECHNICIAN)
        validate_error(shortfall, ERR_KIT_INSUFFICIENT, 409)

        assert_subset(
            port.get_work_order(work_order["id"]),
            {"status": WO_PLANNED, "billed_cents": 0},
        )
        assert_kit_ledger(
            port.get_kit(kit["id"]),
            on_hand_qty=1,
            reserved_qty=0,
            available_qty=1,
            consumed_qty=0,
            received_qty_total=1,
        )
        assert_vehicle_dimensions(
            port.get_vehicle(unit["id"]), processing_status=PROC_SURVEYED
        )


def _passed_unit_with_open_damage(flow: Vpc) -> Dict[str, Any]:
    """An inspection-passed unit off a closed voyage whose damage is still open."""
    port = open_port(flow)
    unit = port.discharge("000407", model_line=MODEL_LINE_LX500)
    port.complete_voyage()
    port.surveyed(unit["id"], [BODY_PANEL_LINE])
    inspection = port.pass_inspection(unit["id"])
    return {"port": port, "vehicle_id": unit["id"], "inspection": inspection}


class TestDamageGateOnPreparation:
    def test_open_damage_blocks_preparation_even_with_no_claim_obligation(self, flow: Vpc):
        """Severity 30 opens the damage dimension without making a claim mandatory.

        PRD: "The unit's damage dimension must be `NONE` or `REPAIRED`; a unit
        sitting in `SURVEY_DAMAGE_OPEN` or `REPAIR_AUTHORIZED` is refused with
        `ERR_VEHICLE_DAMAGE_BLOCKED`."

        Design: Corner/validations/corner_prep_complete_blocked_while_damage_is_open
        """
        scenario = _passed_unit_with_open_damage(flow)
        port = scenario["port"]

        assert scenario["inspection"]["status"] == INSPECTION_PASSED_STATUS
        blocked_unit = port.get_vehicle(scenario["vehicle_id"])
        assert_vehicle_dimensions(
            blocked_unit,
            processing_status=PROC_INSPECTION_PASSED,
            damage_status=DAMAGE_SURVEY_DAMAGE_OPEN,
        )
        assert blocked_unit["claim_mandatory"] is False

        refused = port.api.prep_complete(scenario["vehicle_id"], INSPECTOR)
        validate_error(refused, ERR_VEHICLE_DAMAGE_BLOCKED, 409)

        assert_vehicle_dimensions(
            port.get_vehicle(scenario["vehicle_id"]),
            processing_status=PROC_INSPECTION_PASSED,
        )

    def test_repairing_the_damage_clears_the_gate_and_books_the_spend(self, flow: Vpc):
        """A 40,000-cent order authorizes itself and closes the damage dimension.

        PRD: "An `AUTO` estimate is born already approved: the order is created in
        `AUTHORIZED`, `authorized_by_user_id` is written with the same operator who
        supplied the estimate, and the unit's damage dimension advances
        `SURVEY_DAMAGE_OPEN → REPAIR_AUTHORIZED`."

        PRD: "The unit's damage dimension advances `REPAIR_AUTHORIZED → REPAIRED`
        and `damage_cleared_at` is stamped from the logical clock."

        PRD: "The owning center's `repair_spend_cents` is recomputed as the sum of
        `actual_cost_cents` over all completed repair orders on that center's units."

        Design: Corner/validations/corner_prep_complete_succeeds_once_the_damage_is_repaired
        """
        scenario = _passed_unit_with_open_damage(flow)
        port = scenario["port"]
        vehicle_id = scenario["vehicle_id"]

        order = port.repair_order(vehicle_id, 40_000)
        assert_subset(
            order,
            {"authorization_tier": TIER_AUTO, "status": REPAIR_AUTHORIZED_STATUS},
        )
        assert_vehicle_dimensions(
            port.get_vehicle(vehicle_id), damage_status=DAMAGE_REPAIR_AUTHORIZED
        )

        completed = port.complete_repair(order["id"], 40_000)
        assert completed["status"] == REPAIR_COMPLETED_STATUS

        repaired = port.get_vehicle(vehicle_id)
        assert_vehicle_dimensions(repaired, damage_status=DAMAGE_REPAIRED)
        assert repaired["damage_cleared_at"].startswith("2026-08-02T00:00:00")

        prepared = port.prep_complete(vehicle_id)
        assert_vehicle_dimensions(prepared, processing_status=PROC_SHIPPING_READY)
        assert_center_ledgers(port.get_center(), repair_spend_cents=40_000)


def _two_repaired_units_of_different_severity(flow: Vpc) -> Dict[str, Any]:
    """One unit at severity 63 and one at 30, both repaired and inspection-passed."""
    port = open_port(flow)
    unit_a = port.discharge("000409", model_line=MODEL_LINE_LX500)
    unit_b = port.discharge("000410", model_line=MODEL_LINE_LX500)
    port.complete_voyage()

    survey_a = port.surveyed(
        unit_a["id"], [f.damage_line(DAMAGE_ZONE_UNDERBODY, 35, 40_000)]
    )
    order_a = port.repair_order(unit_a["id"], 40_000)
    port.complete_repair(order_a["id"], 40_000)
    port.pass_inspection(unit_a["id"])

    survey_b = port.surveyed(
        unit_b["id"], [f.damage_line(DAMAGE_ZONE_BODY_PANEL, 25, 30_000)]
    )
    order_b = port.repair_order(unit_b["id"], 30_000)
    port.complete_repair(order_b["id"], 30_000)
    port.pass_inspection(unit_b["id"])

    return {
        "port": port,
        "vehicle_a": unit_a["id"],
        "vehicle_b": unit_b["id"],
        "survey_a": survey_a,
        "survey_b": survey_b,
    }


class TestMandatoryClaimGate:
    def test_only_the_severity_sixty_unit_needs_a_claim_before_it_ships(self, flow: Vpc):
        """One underbody line of 35 points obliges a claim; a body panel of 25 does not.

        PRD: "Each line is weighted by its zone: an underbody line carries a weight
        of 1.8, a glass line 1.5, a body-panel line 1.2, and an interior line 1.0."

        PRD: "The unit's own `severity_index` is set to the survey's, and
        `claim_mandatory` is set to true exactly when that index is 60 or more."

        PRD: "And if the unit's `claim_mandatory` flag is true, a carrier claim must
        exist against that unit's survey; without one the request is refused with
        `ERR_CLAIM_REQUIRED`."

        PRD: "Units whose `claim_mandatory` is false clear this last gate
        unconditionally."

        Design: Corner/validations/corner_mandatory_claim_gate_applies_only_above_severity_sixty
        """
        scenario = _two_repaired_units_of_different_severity(flow)
        port = scenario["port"]

        assert scenario["survey_a"]["severity_index"] == 63
        assert scenario["survey_b"]["severity_index"] == 30
        assert port.get_vehicle(scenario["vehicle_a"])["claim_mandatory"] is True
        assert port.get_vehicle(scenario["vehicle_b"])["claim_mandatory"] is False

        refused = port.api.prep_complete(scenario["vehicle_a"], INSPECTOR)
        validate_error(refused, ERR_CLAIM_REQUIRED, 409)

        prepared_b = port.prep_complete(scenario["vehicle_b"])
        assert_vehicle_dimensions(prepared_b, processing_status=PROC_SHIPPING_READY)
        _, b_claims = validate_paginated(
            port.api.list_claims(
                MANAGER, params={"damage_survey_id": scenario["survey_b"]["id"]}
            )
        )
        assert_pagination_meta(b_claims, total_count=0)

        survey_a = port.get_survey(scenario["survey_a"]["id"])
        claim = port.file_claim(survey_a["id"], survey_a["version"])
        assert claim["recoverable_amount_cents"] == 15_000

        prepared_a = port.prep_complete(scenario["vehicle_a"])
        assert_vehicle_dimensions(prepared_a, processing_status=PROC_SHIPPING_READY)


class TestBandOrderOfIdentifierResolution:
    def test_the_path_identifier_is_reported_before_the_body_reference(self, flow: Vpc):
        """Two unknown ids in one request; the path one answers first.

        PRD: "3. Path identifier resolution, left to right — the fourteen 404 codes
        named in §2.5."

        PRD: "4. Body foreign-key resolution — `ERR_REFERENCE_NOT_FOUND` (404)."

        Design: Corner/validations/corner_path_existence_is_checked_before_body_foreign_keys
        """
        port = open_port(flow)
        port.create_carrier(
            carrier_code="TC-ROAD",
            name="Roadway Auto Transport",
            served_route_zones=["A"],
            linehaul_rate_cents_per_mile=412,
            slot_capacity=2,
            concurrent_load_capacity=1,
        )
        ready = port.shipping_ready_unit("000411", line_items=[CLEAN_LINE])
        payload = f.allocation_payload(
            MISSING_DEALER_UUID,
            ready["version"],
            pickup_window_start="2026-08-04T08:00:00Z",
            pickup_window_end="2026-08-04T12:00:00Z",
        )

        unknown_path = port.api.allocate(MISSING_VEHICLE_UUID, payload, MANAGER)
        validate_error(unknown_path, ERR_VEHICLE_NOT_FOUND, 404)

        unknown_body = port.api.allocate(ready["id"], payload, MANAGER)
        validate_error(unknown_body, ERR_REFERENCE_NOT_FOUND, 404)

        _, order_meta = validate_paginated(
            port.api.list_release_orders(MANAGER, params={"vehicle_id": ready["id"]})
        )
        assert_pagination_meta(order_meta, total_count=0)
        untouched = port.get_vehicle(ready["id"])
        assert_vehicle_dimensions(untouched, processing_status=PROC_SHIPPING_READY)
        assert untouched["version"] == ready["version"]
