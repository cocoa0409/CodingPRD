"""Run floor lifecycle: invalid transitions, the hold/resume loop, the
process-deviation cascade, and the rework yield variants with their unit
conservation invariant."""
import pytest

from test_helpers import (
    OPERATOR,
    PLANNER,
    ApiErrorId,
    assert_lot,
    cancel_run,
    complete_run,
    complete_run_payload,
    create_run,
    get_component,
    get_lot,
    get_run,
    get_window,
    hold_run,
    list_holds_for_lot,
    resume_run,
    setup_active_lot,
    setup_runnable_plant,
    start_run,
    validate_error,
)


class TestInvalidTransitions:
    def test_complete_from_planned_rejected(self, api):
        """PRD §3.6: "The `LineOperator` completes an `IN_PROGRESS` run — again,
        any other state is `ERR_INVALID_STATE`"

        Design: Corner/state_machines/run_complete_from_planned_rejected
        """
        plant = setup_runnable_plant()
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=500)
        payload = complete_run_payload(500)
        validate_error(api.complete_run(run["id"], payload, OPERATOR),
                       ApiErrorId.ERR_INVALID_STATE)
        run = get_run(run["id"])
        assert run["status"] == "PLANNED"
        assert run["created_lot_id"] is None, "no lot is created by a rejected complete"

    def test_cancel_from_completed_rejected(self, api):
        """PRD §3.6: "The `ProductionPlanner` may cancel a run from `PLANNED` or
        `ON_HOLD` — from any other state, `ERR_INVALID_STATE` — landing it in the
        terminal `CANCELLED`."
        PRD §3.6: "First, packaging is consumed: the component's `qty_reserved`
        decreases by the run's `packaging_reserved_qty` and its `qty_on_hand`
        decreases by the same amount, with `qty_available` recomputed — the
        reservation becomes physical consumption."

        Design: Corner/state_machines/run_cancel_from_completed_rejected
        """
        plant = setup_active_lot(output_units=500)
        resp = api.cancel_run(plant["run"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_run(plant["run"]["id"])["status"] == "COMPLETED"

        component = get_component(plant["component"]["id"])
        assert component["qty_on_hand"] == 99950, "consumption is not reversed"
        assert component["qty_reserved"] == 0


class TestHoldResumeCycle:
    def test_hold_and_resume_return_to_in_progress(self, api):
        """PRD §3.6: "Production is interruptible: an `IN_PROGRESS` run can be
        paused to `ON_HOLD` (a process upset, a depositing delay) and an `ON_HOLD`
        run resumed back to `IN_PROGRESS`, each transition requiring the named
        from-state (otherwise `ERR_INVALID_STATE`) and each incrementing the run's
        `version`."

        Design: Difficulty/non_linear_state_machine/run_hold_resume_cycle
        """
        plant = setup_runnable_plant()
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=1000)
        start_run(run["id"])

        held = hold_run(run["id"])
        assert held["status"] == "ON_HOLD"
        resumed = resume_run(run["id"])
        assert resumed["status"] == "IN_PROGRESS", "the cycle returns to a prior state"
        assert resumed["version"] > run["version"]

    def test_run_completes_after_hold_resume_cycle(self, api):
        """PRD §3.6: "The hold loop can repeat as often as the floor demands."
        PRD §3.6: "On success the run lands in `COMPLETED` with `output_units`
        recorded and `version` incremented"

        Design: Difficulty/non_linear_state_machine/run_hold_resume_cycle
        """
        plant = setup_runnable_plant()
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=1000)
        start_run(run["id"])
        hold_run(run["id"])
        resume_run(run["id"])

        done = complete_run(run["id"], output_units=1000)
        assert done["status"] == "COMPLETED"
        assert done["output_units"] == 1000
        lot = get_lot(done["created_lot_id"])
        assert_lot(lot)
        assert lot["qty_on_hand"] == 1000
        assert lot["status"] == "ACTIVE"
        assert lot["quality_status"] == "OK"


class TestDeviationCascade:
    def _complete_with_deviation(self, api):
        """Run planned 500 completed with cook 99, outside the [80, 90] band."""
        plant = setup_runnable_plant(product_type="SEASONAL", sku_code="TRUFFLE-24",
                                     base_price_cents=1000, shelf_life_days=180,
                                     season_code="HOLIDAY", target_units=10000)
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=500)
        start_run(run["id"])
        done = complete_run(run["id"], output_units=500, actual_cook_temp_c=99)
        return plant, done

    def test_out_of_band_completion_suspects_and_blocks_lot(self, api):
        """PRD §3.6: "Hop one: if `actual_cook_temp_c` fell outside the recipe's
        cooking band — below `cook_temp_min_c` or above `cook_temp_max_c` — or
        `actual_temper_exit_c` fell outside the tempering band — below
        `temper_exit_min_c` or above `temper_exit_max_c` — the lot's
        `quality_status` becomes `SUSPECT`."
        PRD §3.6: "Hop two: a `SUSPECT` lot causes the system, unprompted, to open
        a QualityHold on it with `defect_type` `TEMPER_DEVIATION`,
        `affected_units` equal to the run's full `output_units`, `opened_by`
        recorded as 'system', and `status` `OPEN`."
        PRD §3.6: "Hop three: that hold's creation sets the lot's `status` to
        `BLOCKED`."

        Design: Difficulty/transitive_cascade/run_deviation_cascades_to_lot_hold_and_window
        """
        _plant, done = self._complete_with_deviation(api)
        assert done["status"] == "COMPLETED"

        lot = get_lot(done["created_lot_id"])
        assert lot["quality_status"] == "SUSPECT"
        assert lot["status"] == "BLOCKED"
        assert lot["qty_on_hand"] == 500

        holds = list_holds_for_lot(lot["id"])
        assert len(holds) == 1
        hold = holds[0]
        assert hold["defect_type"] == "TEMPER_DEVIATION"
        assert hold["affected_units"] == 500
        assert hold["opened_by"] == "system"
        assert hold["status"] == "OPEN"
        assert hold["lot_qty_at_open"] == 500
        assert hold["defect_rate_pct"] == pytest.approx(100.0)

    def test_blocked_lot_drops_out_of_confirmed_build(self, api):
        """PRD §3.6: "Hop four: the lot's blocking re-triggers the window's build
        projection — the confirmed term now excludes this lot — and bumps the
        window's `version`, per §3.4."
        PRD §3.4: "`shortfall` is true exactly when `confirmed_build_units` is
        less than `target_units`."

        Design: Difficulty/transitive_cascade/run_deviation_cascades_to_lot_hold_and_window
        """
        plant, _done = self._complete_with_deviation(api)
        window = get_window(plant["window"]["id"])
        assert window["confirmed_build_units"] == 0, "blocked lots contribute nothing"
        assert window["shortfall"] is True


class TestReworkYieldVariants:
    def _setup_rework_run(self, api):
        """Source lot of 1000; REWORK run planned 900 drawing all 1000 units."""
        plant = setup_active_lot(output_units=1000, product_type="SEASONAL",
                                 sku_code="CANDY-CANE", base_price_cents=500,
                                 shelf_life_days=120, standard_yield_pct=0.90,
                                 season_code="HOLIDAY", target_units=10000)
        rework = create_run(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], run_type="REWORK", planned_units=900,
            scheduled_start="2026-09-07T08:00:00Z",
            scheduled_end="2026-09-07T16:00:00Z",
            source_lot_id=plant["lot"]["id"], rework_qty=1000)
        return plant, rework

    def test_standard_projection_fixed_at_creation(self, api):
        """PRD §3.5: "The run's `expected_output_units` is then computed by the
        standard yield variant — `rework_qty` multiplied by the recipe's
        `standard_yield_pct`, rounded down to a whole unit — while for non-rework
        runs `expected_output_units` stays null."
        PRD §3.5: "An accepted rework create moves the earmarked units out of free
        stock: the source lot's `qty_on_hand` decreases by `rework_qty`, its
        `qty_reserved_rework` increases by the same amount, and the lot's
        `version` increments."

        Design: Difficulty/dual_variant_calc/rework_standard_vs_actual_yield
        """
        plant, rework = self._setup_rework_run(api)
        assert rework["expected_output_units"] == 900, "floor(1000 * 0.90)"
        assert rework["output_units"] is None
        source = get_lot(plant["lot"]["id"])
        assert source["qty_on_hand"] == 0
        assert source["qty_reserved_rework"] == 1000

    def test_actual_yield_wins_at_completion(self, api):
        """PRD §3.6: "the standard variant computed `expected_output_units` at
        creation, but the actual variant — the operator's counted `output_units` —
        is what lands in the new lot's `qty_on_hand` and feeds the window's
        confirmed build; the two diverge whenever actual yield differs from the
        recipe standard, and the actual figure always wins."
        PRD §3.6: "if the source lot's `qty_on_hand` is zero and its
        `qty_reserved_rework` is zero after that release, the source lot
        transitions to `DEPLETED`"

        Design: Difficulty/dual_variant_calc/rework_standard_vs_actual_yield
        """
        plant, rework = self._setup_rework_run(api)
        start_run(rework["id"])
        done = complete_run(rework["id"], output_units=850)
        assert done["output_units"] == 850

        run = get_run(rework["id"])
        assert run["expected_output_units"] == 900, "standard variant unchanged"
        assert run["output_units"] == 850, "actual variant recorded"
        assert run["expected_output_units"] != run["output_units"]

        new_lot = get_lot(done["created_lot_id"])
        assert new_lot["qty_on_hand"] == 850, "actual yield lands in the lot"
        source = get_lot(plant["lot"]["id"])
        assert source["qty_reserved_rework"] == 0
        assert source["qty_on_hand"] == 0
        assert source["status"] == "DEPLETED"

        window = get_window(plant["window"]["id"])
        assert window["confirmed_build_units"] == 850, (
            "confirmed build follows the actual variant, not the standard 900")


class TestReworkReserveCancelConservation:
    def _setup_rework_run(self, api, rework_qty=400):
        plant = setup_active_lot(output_units=1000, standard_yield_pct=0.90)
        rework = create_run(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], run_type="REWORK", planned_units=360,
            scheduled_start="2026-09-07T08:00:00Z",
            scheduled_end="2026-09-07T16:00:00Z",
            source_lot_id=plant["lot"]["id"], rework_qty=rework_qty)
        return plant, rework

    def test_cancel_from_planned_restores_source_units(self, api):
        """PRD §3.5: "An accepted rework create moves the earmarked units out of
        free stock: the source lot's `qty_on_hand` decreases by `rework_qty`, its
        `qty_reserved_rework` increases by the same amount, and the lot's
        `version` increments."
        PRD §3.6: "For a rework run, unit conservation is restored at the source:
        the source lot's `qty_reserved_rework` decreases by `rework_qty` and its
        `qty_on_hand` increases by the same amount."

        Design: Difficulty/compensating_invariant/rework_reserve_cancel_unit_conservation
        """
        plant, rework = self._setup_rework_run(api)
        source = get_lot(plant["lot"]["id"])
        assert source["qty_on_hand"] == 600
        assert source["qty_reserved_rework"] == 400
        assert source["qty_on_hand"] + source["qty_reserved_rework"] == 1000
        assert source["status"] == "ACTIVE"

        cancel_run(rework["id"])
        source = get_lot(plant["lot"]["id"])
        assert source["qty_on_hand"] == 1000
        assert source["qty_reserved_rework"] == 0
        assert source["status"] == "ACTIVE"

    def test_cancel_from_on_hold_restores_source_units(self, api):
        """PRD §3.6: "The `ProductionPlanner` may cancel a run from `PLANNED` or
        `ON_HOLD` — from any other state, `ERR_INVALID_STATE`"
        PRD §3.6: "For a rework run, unit conservation is restored at the source:
        the source lot's `qty_reserved_rework` decreases by `rework_qty` and its
        `qty_on_hand` increases by the same amount."

        Design: Difficulty/compensating_invariant/rework_reserve_cancel_unit_conservation
        """
        plant, rework = self._setup_rework_run(api)
        start_run(rework["id"])
        hold_run(rework["id"])
        cancel_run(rework["id"])

        assert get_run(rework["id"])["status"] == "CANCELLED"
        source = get_lot(plant["lot"]["id"])
        assert source["qty_on_hand"] == 1000
        assert source["qty_reserved_rework"] == 0
        assert source["status"] == "ACTIVE"
