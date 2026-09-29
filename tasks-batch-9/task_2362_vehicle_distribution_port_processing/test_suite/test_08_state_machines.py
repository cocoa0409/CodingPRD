"""Transitions: the ones that exist, the ones that do not, the states records are
born in, the side effects a transition carries and the doors that close for good.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    DAMAGE_NONE,
    DAMAGE_SURVEY_DAMAGE_OPEN,
    DAMAGE_ZONE_BODY_PANEL,
    DAMAGE_ZONE_INTERIOR,
    ERR_ACCESSORY_WORK_OPEN,
    ERR_INVALID_STATE,
    HOLD_LIFTED,
    HOLD_OPEN,
    HOLD_TYPE_RECALL,
    HOLD_TYPE_STOP_SHIP,
    INSPECTION_OPEN,
    INSPECTION_PASSED_STATUS,
    INSPECTOR,
    MANAGER,
    MANAGER_2,
    MODEL_LINE_LX500,
    MODEL_LINE_TX300,
    OUTCOME_PASS,
    PLANNER,
    PROC_ACCESSORY_IN_PROGRESS,
    PROC_DISCHARGED,
    PROC_GATED_OUT,
    PROC_INSPECTION_PASSED,
    PROC_SURVEYED,
    REFERENCE_WINDOW_END,
    REFERENCE_WINDOW_START,
    RO_DELIVERED,
    ROUTE_ZONE_A,
    SURVEYOR,
    SURVEY_DRAFT,
    SURVEY_SUBMITTED,
    TECHNICIAN,
    VESSEL_DISCHARGING,
    VESSEL_SCHEDULED,
    WO_KITTED,
    WO_PLANNED,
    YARD_DEPARTED,
    YARD_IN_YARD,
    Vpc,
    assert_pagination_meta,
    assert_stop_ship,
    assert_subset,
    assert_vehicle_dimensions,
    assert_yard_state,
    factories as f,
    open_port,
    validate_error,
    validate_paginated,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 10, 0)
BODY_PANEL_LINE = f.damage_line(DAMAGE_ZONE_BODY_PANEL, 25, 40_000)


class TestStartDischarge:
    def test_a_voyage_moves_to_discharging_and_admits_its_first_unit(self, flow: Vpc):
        """At exactly the reserved window start the voyage opens for units.

        PRD: "Starting discharge advances the voyage from `SCHEDULED` to
        `DISCHARGING`, and is admitted only once the logical clock has reached the
        reserved `berth_window_start` — at or after that instant is acceptable,
        before it is rejected with `ERR_BERTH_WINDOW_NOT_OPEN`."

        Design: Corner/state_machines/corner_start_discharge_moves_vessel_from_scheduled_to_discharging
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
        assert vessel["discharge_status"] == VESSEL_SCHEDULED

        flow.set_clock(REFERENCE_WINDOW_START)
        opened = flow.start_discharge(vessel["id"])
        assert opened["discharge_status"] == VESSEL_DISCHARGING

        unit = flow.discharge("000201", model_line=MODEL_LINE_LX500, vessel_id=vessel["id"])

        assert flow.get_vessel(vessel["id"])["discharged_unit_count"] == 1
        assert_vehicle_dimensions(
            unit, processing_status=PROC_DISCHARGED, yard_presence=YARD_IN_YARD
        )
        assert unit["yard_in_at"].startswith("2026-08-01T06:00:00")
        assert_yard_state(flow.get_center(center["id"]), occupied_slots=1, free_slots=49)


class TestInitialStates:
    def test_five_creation_calls_land_in_five_declared_initial_states(self, flow: Vpc):
        """None of the five creates advances its own record past its birth state.

        PRD: "Planning creates an `AccessoryWorkOrder` in `PLANNED` against a unit,
        naming the `accessory_kit_id` to be drawn from and a `qty` of at least 1.
        Planning moves no stock at all: the kit's quantities are untouched,
        `billed_cents` sits at 0, `installed_by_user_id` is null, and `reopen_count`
        is 0."

        PRD: "A `QualityInspector` opens an inspection against a unit; the request
        has no body, the inspection is created in `OPEN` with `inspector_user_id`
        recorded from the acting `X-User-ID`, and both `outcome` and `defect_count`
        stay unset while it remains open."

        PRD: "The hold is created in `OPEN` with `applied_by_user_id` recorded from
        the acting `X-User-ID`."

        Design: Corner/state_machines/corner_new_rows_start_in_their_declared_initial_states
        """
        port = open_port(flow)
        kit = port.create_kit(
            kit_code="K-ALLOY",
            program_code="PIO-ALLOY",
            received_qty_total=10,
            unit_cost_cents=24_000,
            install_minutes_per_unit=45,
        )

        unit = port.discharge(
            "000202", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY"
        )
        assert_vehicle_dimensions(
            unit, processing_status=PROC_DISCHARGED, damage_status=DAMAGE_NONE
        )

        survey = port.survey(unit["id"], [CLEAN_LINE])
        assert survey["status"] == SURVEY_DRAFT

        work_order = port.plan_work_order(unit["id"], kit["id"], 1)
        assert_subset(
            work_order,
            {
                "status": WO_PLANNED,
                "billed_cents": 0,
                "reopen_count": 0,
                "installed_by_user_id": None,
            },
        )

        inspection = port.open_inspection(unit["id"])
        assert_subset(inspection, {"status": INSPECTION_OPEN, "outcome": None})
        assert port.get_inspection(inspection["id"])["outcome"] is None

        hold = port.apply_model_line_hold(
            MODEL_LINE_TX300, hold_type=HOLD_TYPE_RECALL, reference_code="NHTSA-26V-777"
        )
        assert_subset(hold, {"status": HOLD_OPEN, "affected_vehicle_count": 0})
        assert_stop_ship(
            port.get_vehicle(unit["id"]), blocked=False, blocking_hold_order_id=None
        )


class TestInspectionPassPrecondition:
    def test_reserved_but_uninstalled_stock_blocks_the_pass_until_it_is_installed(
        self, flow: Vpc
    ):
        """The very same completion succeeds once the reservation is consumed.

        PRD: "One further precondition guards the pass: no accessory work order of
        that unit may still be sitting in `KITTED`, because reserved-but-uninstalled
        stock means the option work is not actually finished — such a pass is
        refused with `ERR_ACCESSORY_WORK_OPEN`."

        Design: Corner/state_machines/corner_inspection_pass_blocked_while_an_accessory_work_order_is_kitted
        """
        port = open_port(flow)
        kit = port.create_kit(
            kit_code="K-ALLOY",
            program_code="PIO-ALLOY",
            received_qty_total=10,
            unit_cost_cents=24_000,
            install_minutes_per_unit=45,
        )
        unit = port.discharge(
            "000203", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY"
        )
        port.surveyed(unit["id"], [CLEAN_LINE])
        work_order = port.plan_work_order(unit["id"], kit["id"], 1)
        kitted = port.kit_work_order(work_order["id"])
        assert kitted["status"] == WO_KITTED
        inspection = port.open_inspection(unit["id"])

        blocked = port.api.complete_inspection(
            inspection["id"], f.pass_payload(0), INSPECTOR
        )
        validate_error(blocked, ERR_ACCESSORY_WORK_OPEN, 409)

        assert port.get_inspection(inspection["id"])["status"] == INSPECTION_OPEN
        assert_vehicle_dimensions(
            port.get_vehicle(unit["id"]), processing_status=PROC_ACCESSORY_IN_PROGRESS
        )

        port.install_work_order(work_order["id"])
        passed = port.complete_inspection(inspection["id"], OUTCOME_PASS, 0)

        assert passed["status"] == INSPECTION_PASSED_STATUS
        assert_vehicle_dimensions(
            port.get_vehicle(unit["id"]), processing_status=PROC_INSPECTION_PASSED
        )


class TestSurveySubmissionSideEffects:
    def test_submission_scores_the_survey_and_writes_the_score_onto_the_unit(self, flow: Vpc):
        """One body-panel line of 25 points scores 30 and opens the damage dimension.

        PRD: "Submission then carries the score outward. The survey advances from
        `DRAFT` to `SUBMITTED`, its `claimed_amount_cents` is computed on the survey
        basis described in §3.3, and the unit's `processing_status` advances
        `DISCHARGED → SURVEYED`. The unit's own `severity_index` is set to the
        survey's, and `claim_mandatory` is set to true exactly when that index is 60
        or more. The damage dimension moves independently: when the index is 25 or
        more, `damage_status` advances `NONE → SURVEY_DAMAGE_OPEN` and
        `damage_opened_at` is stamped from the logical clock; when the index is below
        25, the damage is treated as cosmetic and `damage_status` stays `NONE` with
        `damage_opened_at` left null."

        PRD: "Sum those capped line figures: that total is `claimed_amount_cents`,
        and it is gross of the deductible."

        Design: Corner/state_machines/corner_survey_submit_writes_severity_and_damage_fields_onto_the_vehicle
        """
        port = open_port(flow)
        unit = port.discharge("000204", model_line=MODEL_LINE_TX300)
        survey = port.survey(unit["id"], [BODY_PANEL_LINE])

        submitted = port.submit_survey(survey["id"])

        assert_subset(
            submitted,
            {
                "status": SURVEY_SUBMITTED,
                "severity_index": 30,
                "claimed_amount_cents": 40_000,
            },
        )

        scored = port.get_vehicle(unit["id"])
        assert_vehicle_dimensions(
            scored,
            processing_status=PROC_SURVEYED,
            damage_status=DAMAGE_SURVEY_DAMAGE_OPEN,
        )
        assert_subset(
            scored,
            {"severity_index": 30, "claim_mandatory": False, "damage_cleared_at": None},
        )
        assert scored["damage_opened_at"].startswith("2026-08-02T00:00:00")
        assert scored["version"] > 1


class TestMissingTransitions:
    def test_three_absent_edges_each_answer_invalid_state(self, flow: Vpc):
        """A submitted survey, a planned work order and a discharged unit.

        PRD: "Submission is admitted only when the survey itself is still in `DRAFT`
        and the unit's `processing_status` is still `DISCHARGED`; anything else is
        `ERR_INVALID_STATE`."

        PRD: "8. State legality: the requested transition must exist from the
        target's current state — `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/corner_triggers_absent_from_the_transition_list_return_invalid_state
        """
        port = open_port(flow)
        kit = port.create_kit(
            kit_code="K-ALLOY",
            program_code="PIO-ALLOY",
            received_qty_total=10,
            unit_cost_cents=24_000,
            install_minutes_per_unit=45,
        )
        unit_a = port.discharge(
            "000205", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY"
        )
        unit_b = port.discharge("000206", model_line=MODEL_LINE_LX500)
        survey = port.survey(unit_a["id"], [CLEAN_LINE])
        port.submit_survey(survey["id"])
        work_order = port.plan_work_order(unit_a["id"], kit["id"], 1)

        resubmit = port.api.submit_survey(survey["id"], SURVEYOR)
        validate_error(resubmit, ERR_INVALID_STATE, 409)
        assert port.get_survey(survey["id"])["status"] == SURVEY_SUBMITTED

        install = port.api.install_work_order(work_order["id"], TECHNICIAN)
        validate_error(install, ERR_INVALID_STATE, 409)
        assert_subset(
            port.get_work_order(work_order["id"]),
            {"status": WO_PLANNED, "installed_by_user_id": None},
        )

        prep = port.api.prep_complete(unit_b["id"], INSPECTOR)
        validate_error(prep, ERR_INVALID_STATE, 409)
        assert_vehicle_dimensions(
            port.get_vehicle(unit_b["id"]), processing_status=PROC_DISCHARGED
        )

        assert_subset(
            port.get_vehicle(unit_a["id"]),
            {"severity_index": 10, "damage_status": DAMAGE_NONE},
        )


def _delivered_order(flow: Vpc) -> Dict[str, Any]:
    """One unit driven to ``GATED_OUT`` with its order confirmed ``DELIVERED``."""
    port = open_port(flow)
    dealer = port.create_dealer(
        dealer_code="D-ATL",
        name="Atlanta Motors",
        route_zone=ROUTE_ZONE_A,
        distance_miles=100,
        allocation_quota=2,
    )
    port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["A", "B", "C"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=4,
        concurrent_load_capacity=2,
    )
    ready = port.shipping_ready_unit("000207", line_items=[CLEAN_LINE])
    order = port.allocate(
        ready["id"],
        dealer["id"],
        ready["version"],
        pickup_window_start="2026-08-04T08:00:00Z",
        pickup_window_end="2026-08-04T12:00:00Z",
    )
    port.set_clock("2026-08-04T08:00:00Z")
    port.dispatch(order["id"])
    port.gate_out(order["id"])
    delivered = port.confirm_delivery(order["id"], dealer["id"])
    return {
        "port": port,
        "dealer_id": dealer["id"],
        "vehicle_id": ready["id"],
        "order_id": order["id"],
        "delivered": delivered,
    }


class TestTerminalLockdown:
    def test_a_delivered_order_and_a_gated_out_unit_admit_no_further_transition(
        self, flow: Vpc
    ):
        """Cancelling the order and re-allocating the unit are both dead ends.

        PRD: "A `Dealer` acknowledges receipt of a gated-out unit, moving the release
        order `GATED_OUT → DELIVERED`, which is terminal."

        PRD: "On success the unit's `yard_presence` becomes `DEPARTED`, its
        `gate_out_at` is stamped from the logical clock, and its processing dimension
        advances `RELEASED → GATED_OUT`, which is terminal for the processing
        dimension."

        Design: Corner/state_machines/corner_gated_out_vehicle_and_delivered_release_order_are_locked_down
        """
        scenario = _delivered_order(flow)
        port = scenario["port"]

        assert scenario["delivered"]["status"] == RO_DELIVERED
        gated = port.get_vehicle(scenario["vehicle_id"])
        assert_vehicle_dimensions(
            gated, processing_status=PROC_GATED_OUT, yard_presence=YARD_DEPARTED
        )
        assert gated["gate_out_at"].startswith("2026-08-04T08:00:00")

        cancel = port.api.cancel_release_order(scenario["order_id"], MANAGER)
        validate_error(cancel, ERR_INVALID_STATE, 409)
        assert port.get_release_order(scenario["order_id"])["status"] == RO_DELIVERED

        realloc = port.api.allocate(
            scenario["vehicle_id"],
            f.allocation_payload(
                scenario["dealer_id"],
                gated["version"],
                pickup_window_start="2026-08-05T08:00:00Z",
                pickup_window_end="2026-08-05T12:00:00Z",
            ),
            MANAGER,
        )
        validate_error(realloc, ERR_INVALID_STATE, 409)

        _, meta = validate_paginated(
            port.api.list_release_orders(
                MANAGER, params={"vehicle_id": scenario["vehicle_id"]}
            )
        )
        assert_pagination_meta(meta, total_count=1)
        still_gone = port.get_vehicle(scenario["vehicle_id"])
        assert_vehicle_dimensions(still_gone, yard_presence=YARD_DEPARTED)


class TestReplayedTransitions:
    def test_neither_replay_is_admitted_and_neither_re_runs_its_side_effects(self, flow: Vpc):
        """Start-discharge on a discharging voyage, lift on a lifted hold.

        PRD: "Lifting a hold moves it `OPEN → LIFTED` and records
        `lifted_by_user_id`. It is available only from `OPEN`, and the lifter must
        not be the applier per §2.11."

        PRD: "9. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Corner/state_machines/corner_replayed_start_discharge_and_replayed_lift_both_fail_on_second_attempt
        """
        port = open_port(flow)
        unit = port.discharge("000208", model_line=MODEL_LINE_LX500)
        hold = port.apply_model_line_hold(
            MODEL_LINE_LX500,
            hold_type=HOLD_TYPE_STOP_SHIP,
            reference_code="SS-2026-08",
            user=MANAGER,
        )
        assert hold["affected_vehicle_count"] == 1

        lifted = port.lift_hold(hold["id"], MANAGER_2)
        assert lifted["status"] == HOLD_LIFTED

        replay_discharge = port.api.start_discharge(port.vessel["id"], PLANNER)
        validate_error(replay_discharge, ERR_INVALID_STATE, 409)
        assert_subset(
            port.get_vessel(),
            {"discharge_status": VESSEL_DISCHARGING, "discharged_unit_count": 1},
        )

        replay_lift = port.api.lift_hold(hold["id"], MANAGER_2)
        validate_error(replay_lift, ERR_INVALID_STATE, 409)

        final = port.get_hold(hold["id"])
        assert_subset(final, {"status": HOLD_LIFTED, "lifted_by_user_id": MANAGER_2.user_id})
        assert_stop_ship(
            port.get_vehicle(unit["id"]), blocked=False, blocking_hold_order_id=None
        )
