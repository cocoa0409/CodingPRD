"""QA verdicts, brix correction branches, reblend limit, and mass balance."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, create_tank, plan_batch, blend_and_record,
    qa_verdict, process_batch_validated, remeasure_blend,
)

# Module-level alias of the session-scoped `api` fixture (conftest returns
# the same object) so module/class helpers can call the client without
# declaring the fixture parameter.
api = api_client


PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["blend_operator_headers"]
QA = TEST_USERS["qa_inspector_headers"]


def _qa_failed_batch(measured_brix, capacity_liters=5000, quantity_liters=2000):
    """Customer + DRAFT formula (target 12.0, tol 0.3, conc 65.0) + tank + batch
    driven to QA_FAILED with the given out-of-tolerance measurement."""
    customer = create_customer()
    formula = create_formula(customer["id"], approve=False)
    tank = create_tank(capacity_liters=capacity_liters)
    batch = plan_batch(formula["id"], tank["id"], quantity_liters=quantity_liters)
    blend_and_record(batch["id"], measured_brix)
    failed = qa_verdict(batch["id"], "FAIL")
    return formula, tank, failed


class TestBrixDilutionBranch:
    def test_dilution_adds_water_to_target(self, api):
        """PRD §3.4: "When the blend is too sweet — measured above target by more
        than the tolerance — the system dilutes with water all the way to target,
        not merely to the band's edge: the addition equals the current
        `quantity_liters` multiplied by the excess of `measured_brix` over
        `target_brix`, divided by `target_brix`."

        Design: Difficulty/combinatorial_formula/brix_dilution_branch_with_capacity_gate
        """
        formula, tank, batch = _qa_failed_batch(12.8)
        adjusted = get_success_data(api.apply_adjustment(batch["id"], OP))
        assert adjusted["status"] == "BLENDING"
        fresh = get_success_data(api.get_batch(batch["id"], PM))
        # round_half_up(2000 * 0.8 / 12.0, 1) == 133.3
        assert fresh["added_water_liters"] == pytest.approx(133.3, abs=0.01)
        assert fresh["added_concentrate_liters"] == 0
        assert fresh["quantity_liters"] == pytest.approx(2133.3, abs=0.01)
        assert fresh["adjustment_count"] == 1

    def test_capacity_gate_rejects_overflow_atomically(self, api):
        """PRD §3.4: "one whose rounded addition would push the batch past the
        tank's `capacity_liters` is refused with
        `ERR_ADJUSTMENT_EXCEEDS_TANK_CAPACITY` — no partial addition is ever
        applied."

        Design: Difficulty/combinatorial_formula/brix_dilution_branch_with_capacity_gate
        """
        formula, tank, batch = _qa_failed_batch(12.8, capacity_liters=2100)
        resp = api.apply_adjustment(batch["id"], OP)
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_TANK_CAPACITY)
        assert resp.status_code == 422
        fresh = get_success_data(api.get_batch(batch["id"], PM))
        assert fresh["quantity_liters"] == 2000
        assert fresh["added_water_liters"] == 0
        assert fresh["adjustment_count"] == 0
        assert fresh["status"] == "QA_FAILED"


class TestBrixConcentrationBranch:
    def test_concentration_adds_concentrate_to_target(self, api):
        """PRD §3.4: "When the blend is too thin — measured below target by more
        than the tolerance — the system fortifies with concentrate, again to
        target: the addition equals `quantity_liters` multiplied by the shortfall
        of `measured_brix` below `target_brix`, divided by the difference between
        the formula's `concentrate_brix` and its `target_brix`."

        Design: Corner/calculations/brix_concentration_branch_standalone
        """
        formula, tank, batch = _qa_failed_batch(11.5)
        adjusted = get_success_data(api.apply_adjustment(batch["id"], OP))
        assert adjusted["status"] == "BLENDING"
        fresh = get_success_data(api.get_batch(batch["id"], PM))
        # round_half_up(2000 * 0.5 / (65.0 - 12.0), 1) == 18.9
        assert fresh["added_concentrate_liters"] == pytest.approx(18.9, abs=0.01)
        assert fresh["added_water_liters"] == 0
        assert fresh["quantity_liters"] == pytest.approx(2018.9, abs=0.01)
        assert fresh["adjustment_count"] == 1


class TestAdjustmentGates:
    def test_adjustment_with_in_band_reading_rejected(self, api):
        """PRD §3.4: "A correction requested while the measurement still sits
        inside the tolerance band is refused with `ERR_NOTHING_TO_ADJUST`"

        Design: Corner/calculations/apply_adjustment_rejected_when_brix_in_band
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=2000)
        blend_and_record(batch["id"], 12.2)  # |12.2 - 12.0| == 0.2 <= 0.3
        qa_verdict(batch["id"], "FAIL")  # FAIL carries no brix precondition
        resp = api.apply_adjustment(batch["id"], OP)
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_ADJUST)
        fresh = get_success_data(api.get_batch(batch["id"], PM))
        assert fresh["adjustment_count"] == 0
        assert fresh["status"] == "QA_FAILED"

    def test_capacity_gate_fires_before_applying(self, api):
        """PRD §3.4: "The computed addition is rounded to the nearest tenth of a
        liter, half up, before the capacity check is applied. ... and one whose
        rounded addition would push the batch past the tank's `capacity_liters` is
        refused with `ERR_ADJUSTMENT_EXCEEDS_TANK_CAPACITY` — no partial addition
        is ever applied."

        Design: Corner/calculations/adjustment_rejected_when_tank_would_overflow
        """
        formula, tank, batch = _qa_failed_batch(12.8, capacity_liters=2100)
        resp = api.apply_adjustment(batch["id"], OP)
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_TANK_CAPACITY)
        fresh = get_success_data(api.get_batch(batch["id"], PM))
        assert fresh["quantity_liters"] == 2000
        assert fresh["added_water_liters"] == 0
        assert fresh["adjustment_count"] == 0
        assert fresh["status"] == "QA_FAILED"


class TestQaPassBrixBand:
    def test_pass_at_exactly_band_edge(self, api):
        """PRD §3.4: "the absolute gap between `measured_brix` and the formula's
        `target_brix` must not exceed the formula's `brix_tolerance`, with the
        boundary inclusive"

        Design: Corner/calculations/qa_pass_brix_band_inclusive_edges
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1000)
        blend_and_record(batch["id"], 12.3)  # exactly target + tolerance
        passed = qa_verdict(batch["id"], "PASS")
        assert passed["status"] == "QA_PASSED"

    def test_pass_outside_band_rejected_then_fail_allowed(self, api):
        """PRD §3.4: "a `PASS` attempted outside the band is rejected with
        `ERR_BRIX_OUT_OF_TOLERANCE`."

        Design: Corner/calculations/qa_pass_brix_band_inclusive_edges
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1000)
        blend_and_record(batch["id"], 12.31)  # 0.31 over target, outside the band
        resp = api.qa_verdict(batch["id"], {"verdict": "PASS"}, QA)
        validate_error(resp, ApiErrorId.ERR_BRIX_OUT_OF_TOLERANCE)
        assert get_success_data(api.get_batch(batch["id"], PM))["status"] == "AWAITING_QA"
        failed = qa_verdict(batch["id"], "FAIL")
        assert failed["status"] == "QA_FAILED"


class TestReblendCycle:
    def _run_two_adjustment_loop(self):
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=2000)
        # loop 1: too sweet -> dilute
        blend_and_record(batch["id"], 12.8)
        qa_verdict(batch["id"], "FAIL")
        get_success_data(api.apply_adjustment(batch["id"], OP))
        # loop 2: too thin -> fortify (batch returned to BLENDING: re-measure only)
        remeasure_blend(batch["id"], 11.5)
        qa_verdict(batch["id"], "FAIL")
        get_success_data(api.apply_adjustment(batch["id"], OP))
        # loop exit: inside the band
        remeasure_blend(batch["id"], 12.2)
        passed = qa_verdict(batch["id"], "PASS")
        return formula, tank, batch["id"], passed

    def test_two_loops_exit_via_pass_with_count_two(self, api):
        """PRD §3.4: "A successful correction accumulates into
        `added_water_liters` or `added_concentrate_liters` as appropriate, grows
        `quantity_liters` by the same addition, increments `adjustment_count` by
        one, and returns the batch to `BLENDING` for re-measurement"

        Design: Difficulty/non_linear_state_machine/batch_qa_reblend_cycle_twice
        """
        _, _, batch_id, passed = self._run_two_adjustment_loop()
        assert passed["status"] == "QA_PASSED"
        fresh = get_success_data(api.get_batch(batch_id, PM))
        assert fresh["adjustment_count"] == 2

    def test_two_loops_accumulate_both_branches(self, api):
        """PRD §3.4: "the addition equals the current `quantity_liters` multiplied
        by the excess of `measured_brix` over `target_brix`, divided by
        `target_brix`." and "the addition equals `quantity_liters` multiplied by
        the shortfall of `measured_brix` below `target_brix`, divided by the
        difference between the formula's `concentrate_brix` and its
        `target_brix`."

        Design: Difficulty/non_linear_state_machine/batch_qa_reblend_cycle_twice
        """
        _, _, batch_id, _ = self._run_two_adjustment_loop()
        fresh = get_success_data(api.get_batch(batch_id, PM))
        # water: round_half_up(2000 * 0.8 / 12.0, 1) == 133.3
        # concentrate: round_half_up(2133.3 * 0.5 / (65.0 - 12.0), 1) == 20.1
        assert fresh["added_water_liters"] == pytest.approx(133.3, abs=0.01)
        assert fresh["added_concentrate_liters"] == pytest.approx(20.1, abs=0.01)
        assert fresh["quantity_liters"] == pytest.approx(2153.4, abs=0.01)


class TestReblendLimit:
    def _batch_at_adjustment_limit(self):
        formula, tank, batch = _qa_failed_batch(12.8)
        get_success_data(api.apply_adjustment(batch["id"], OP))  # count -> 1
        remeasure_blend(batch["id"], 11.5)
        qa_verdict(batch["id"], "FAIL")
        get_success_data(api.apply_adjustment(batch["id"], OP))  # count -> 2
        remeasure_blend(batch["id"], 12.9)
        qa_verdict(batch["id"], "FAIL")
        return batch["id"]

    def test_third_adjustment_rejected(self, api):
        """PRD §3.4: "A failed batch may be corrected at most twice: once
        `adjustment_count` has reached two, a further correction attempt is
        refused with `ERR_REBLEND_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/reblend_limit_at_exactly_two
        """
        batch_id = self._batch_at_adjustment_limit()
        resp = api.apply_adjustment(batch_id, OP)
        validate_error(resp, ApiErrorId.ERR_REBLEND_LIMIT_EXCEEDED)

    def test_rejected_third_adjustment_changes_nothing(self, api):
        """PRD §3.4: "A failed batch may be corrected at most twice: once
        `adjustment_count` has reached two, a further correction attempt is
        refused with `ERR_REBLEND_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/reblend_limit_at_exactly_two
        """
        batch_id = self._batch_at_adjustment_limit()
        validate_error(api.apply_adjustment(batch_id, OP),
                       ApiErrorId.ERR_REBLEND_LIMIT_EXCEEDED)
        fresh = get_success_data(api.get_batch(batch_id, PM))
        assert fresh["adjustment_count"] == 2
        assert fresh["status"] == "QA_FAILED"
        assert fresh["quantity_liters"] == pytest.approx(2153.4, abs=0.01)


class TestMassBalance:
    def _processed_batch_after_two_adjustments(self):
        formula, tank, batch = _qa_failed_batch(12.8)
        get_success_data(api.apply_adjustment(batch["id"], OP))
        remeasure_blend(batch["id"], 11.5)
        qa_verdict(batch["id"], "FAIL")
        get_success_data(api.apply_adjustment(batch["id"], OP))
        remeasure_blend(batch["id"], 12.2)
        qa_verdict(batch["id"], "PASS")
        process_batch_validated(batch["id"], formula["process_type"])
        return get_success_data(api.get_batch(batch["id"], PM))

    def test_quantity_equals_initial_plus_additions(self, api):
        """PRD §2.9: "On a batch, `quantity_liters` always equals
        `initial_quantity_liters` plus `added_water_liters` plus
        `added_concentrate_liters`."

        Design: Difficulty/compensating_invariant/batch_mass_balance_invariant
        """
        batch = self._processed_batch_after_two_adjustments()
        assert batch["initial_quantity_liters"] == 2000
        assert batch["added_water_liters"] == pytest.approx(133.3, abs=0.01)
        assert batch["added_concentrate_liters"] == pytest.approx(20.1, abs=0.01)
        assert batch["quantity_liters"] == pytest.approx(2153.4, abs=0.01)
        total = round(batch["initial_quantity_liters"] + batch["added_water_liters"]
                      + batch["added_concentrate_liters"], 1)
        assert round(batch["quantity_liters"], 1) == total

    def test_loss_and_processed_sum_back_to_quantity(self, api):
        """PRD §3.5: "`loss_liters` is two percent of the batch's current
        `quantity_liters`, rounded to the nearest tenth of a liter half up, and
        `processed_liters` is what remains of `quantity_liters` after that loss."

        Design: Difficulty/compensating_invariant/batch_mass_balance_invariant
        """
        batch = self._processed_batch_after_two_adjustments()
        assert batch["status"] == "PROCESSED"
        # round_half_up(2153.4 * 0.02, 1) == 43.1
        assert batch["loss_liters"] == pytest.approx(43.1, abs=0.01)
        assert batch["processed_liters"] == pytest.approx(2110.3, abs=0.01)
        assert round(batch["processed_liters"] + batch["loss_liters"], 1) == pytest.approx(2153.4, abs=0.01)
