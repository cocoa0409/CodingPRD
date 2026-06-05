"""OEE effectiveness and work-order cost calculations.

Difficulty queue (depth): dual-variant calculations, the three-factor OEE
product, BOM standard-cost rounding, and the quality-floor boundary.
"""
import pytest

from test_helpers import (
    api_client as _ac,
    get_success_data, validate_success,
    TEST_USERS,
    setup_machine_with_run_logs,
    setup_material_variance_scenario,
    setup_bom_standard_cost_scenario,
)

ENG = TEST_USERS["manufacturing_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]


# Two run logs: run 12000s each (sum 24000), totals 100+100=200, good 95+90=185.
TWO_LOGS = [
    {"window_start": "2026-06-01T00:00:00.000Z", "window_end": "2026-06-01T04:00:00.000Z",
     "run_time_secs": 12000, "total_units": 100, "good_units": 95},
    {"window_start": "2026-06-01T04:00:00.000Z", "window_end": "2026-06-01T08:00:00.000Z",
     "run_time_secs": 12000, "total_units": 100, "good_units": 90},
]


class TestOeeRecompute:
    def test_oee_performance_ideal_basis_on_machine(self, api):
        """PRD §3.3: "Performance is the product of the primary operation's
        ideal_cycle_time_secs and the summed total units, divided by the total run
        time, again clamped to 0 through 1".
        PRD §3.3: "availability is that total run time divided by the machine's
        planned_production_secs, clamped to lie within 0 through 1."

        Design: Difficulty/dual_variant_calc/oee_performance_two_bases_diverge_on_machine
        """
        ctx = setup_machine_with_run_logs(
            planned_production_secs=28800, run_logs=TWO_LOGS,
            primary_ideal_cycle_time_secs=100)
        m = validate_success(api.recompute_oee(ctx["machine"]["id"], INSPECTOR))
        # A = 24000/28800 = 0.8333 ; P = 100*200/24000 = 0.8333
        assert m["oee_availability"] == 0.8333, m["oee_availability"]
        assert m["oee_performance"] == 0.8333, m["oee_performance"]
        assert m["oee_quality"] == 0.9250, m["oee_quality"]

    def test_oee_overall_single_round_from_full_precision_ratios(self, api):
        """PRD §3.3: "The overall figure oee_overall is computed by multiplying the
        three full-precision clamped ratios — availability, performance, and quality,
        not their already-rounded forms — together and rounding that single product
        to 4 decimal places".

        Design: Difficulty/combinatorial_formula/oee_three_factor_nonlinear_product
        """
        ctx = setup_machine_with_run_logs(
            planned_production_secs=28800, run_logs=TWO_LOGS,
            primary_ideal_cycle_time_secs=100)
        m = validate_success(api.recompute_oee(ctx["machine"]["id"], ENG))
        # 0.833333.. * 0.833333.. * 0.925 rounded once = 0.6424 (not pre-rounded 0.6423)
        assert m["oee_overall"] == 0.6424, m["oee_overall"]

    def test_oee_overall_full_three_factor_product(self, api):
        """PRD §3.3: "The overall figure oee_overall is computed by multiplying the
        three full-precision clamped ratios — availability, performance, and quality,
        not their already-rounded forms — together and rounding that single product
        to 4 decimal places".

        Design: Difficulty/combinatorial_formula/oee_three_factor_nonlinear_product
        """
        ctx = setup_machine_with_run_logs(
            planned_production_secs=28800, run_logs=TWO_LOGS,
            primary_ideal_cycle_time_secs=100)
        m = validate_success(api.recompute_oee(ctx["machine"]["id"], INSPECTOR))
        assert m["oee_availability"] == 0.8333
        assert m["oee_performance"] == 0.8333
        assert m["oee_quality"] == 0.9250
        assert m["oee_overall"] == 0.6424

    def test_oee_performance_basis_diverges_from_quality_metric(self, api):
        """PRD §3.3: "Performance is the product of the primary operation's
        ideal_cycle_time_secs and the summed total units, divided by the total run
        time, again clamped to 0 through 1".
        PRD §3.3: "Quality is the summed good units divided by the summed total
        units, clamped to 0 through 1".

        Design: Difficulty/dual_variant_calc/oee_performance_two_bases_diverge_on_machine
        """
        ctx = setup_machine_with_run_logs(
            planned_production_secs=28800, run_logs=TWO_LOGS,
            primary_ideal_cycle_time_secs=100)
        m = validate_success(api.recompute_oee(ctx["machine"]["id"], ENG))
        # performance (ideal-basis) and quality are independently derived metrics.
        assert m["oee_performance"] == 0.8333
        assert m["oee_quality"] == 0.9250


class TestQualityFloorBoundary:
    def test_quality_exactly_at_floor_flags(self, api):
        """PRD §3.3: "the machine's quality_flagged is set to true when the
        just-computed oee_quality is at or below the quality floor of 0.95, and
        false otherwise; the boundary value of exactly 0.95 does flag."

        Design: Difficulty/boundary_precision_check/quality_flag_exact_floor_inclusive
        """
        # one log: total 200, good 190 -> Q = 0.9500 exactly
        ctx = setup_machine_with_run_logs(
            planned_production_secs=28800,
            run_logs=[{"window_start": "2026-06-01T00:00:00.000Z",
                       "window_end": "2026-06-01T04:00:00.000Z",
                       "run_time_secs": 10000, "total_units": 200, "good_units": 190}])
        m = validate_success(api.recompute_oee(ctx["machine"]["id"], INSPECTOR))
        assert m["oee_quality"] == 0.9500, m["oee_quality"]
        assert m["quality_flagged"] is True

    def test_quality_floor_value_is_exactly_point_nine_five(self, api):
        """PRD §3.3: "the machine's quality_flagged is set to true when the
        just-computed oee_quality is at or below the quality floor of 0.95, and
        false otherwise; the boundary value of exactly 0.95 does flag."

        Design: Difficulty/boundary_precision_check/quality_flag_exact_floor_inclusive
        """
        ctx = setup_machine_with_run_logs(
            planned_production_secs=28800,
            run_logs=[{"window_start": "2026-06-01T00:00:00.000Z",
                       "window_end": "2026-06-01T04:00:00.000Z",
                       "run_time_secs": 10000, "total_units": 200, "good_units": 190}])
        m = validate_success(api.recompute_oee(ctx["machine"]["id"], ENG))
        # Q = 190/200 = 0.95 exactly; inclusive boundary flags.
        assert m["oee_quality"] == 0.9500
        assert m["quality_flagged"] is True


class TestBomStandardCost:
    def test_bom_standard_total_round_per_component_then_sum(self, api):
        """PRD §2.7: "Every per-item cost component is rounded to whole cents using
        the round-half-up method before it is summed into a total. This pinned
        "round each, then sum" order applies to BOM standard cost, actual material
        cost, and labor cost".

        Design: Difficulty/combinatorial_formula/bom_standard_round_per_component_then_sum
        """
        ctx = setup_bom_standard_cost_scenario()
        wo = ctx["work_order"]
        get_success_data(api.release_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER))
        cost = validate_success(api.get_cost_summary(wo["id"], PLANNER))
        # R1: 1/0.8 * 1/0.8 ... actually R1 path FG->R1 s20: eff 1/0.8=1.25 ->
        # required 1.25, cost 1.25*82=102.5 -> 103. R2 path FG->SA->R2 each s20:
        # 1.25*1.25=1.5625 required, cost 1.5625*88=137.5 -> 138. Total 103+138=241.
        assert cost["bom_standard_total_cents"] == 241, cost["bom_standard_total_cents"]

    def test_bom_standard_total_differs_from_sum_then_round(self, api):
        """PRD §2.7: "rounding the sum instead of the parts would yield a different
        cent total and is incorrect."

        Design: Difficulty/combinatorial_formula/bom_standard_round_per_component_then_sum
        """
        ctx = setup_bom_standard_cost_scenario()
        wo = ctx["work_order"]
        get_success_data(api.release_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER))
        cost = validate_success(api.get_cost_summary(wo["id"], PLANNER))
        # round-per-component = 241; sum-then-round would be 240.
        assert cost["bom_standard_total_cents"] == 241
        assert cost["bom_standard_total_cents"] != 240


class TestMaterialVariance:
    def test_material_variance_actual_minus_standard(self, api):
        """PRD §3.9: "Material variance is the actual material cost minus the
        standard material cost: the actual cost is the sum, over every non-reversed
        lot issue for this order, of that issue's issued_qty multiplied by its
        source lot's product unit_cost_cents, each per-issue product rounded to
        whole cents before being summed; the standard cost is the sum of
        standard_cost_cents across the order's component demands."

        Design: Difficulty/dual_variant_calc/workorder_material_variance_actual_vs_standard
        """
        ctx = setup_material_variance_scenario()
        wo = ctx["work_order"]
        completed = validate_success(api.complete_work_order(wo["id"], PLANNER))
        # actual = 2*82 + 2*88 = 164 + 176 = 340 ; standard = 103 + 138 = 241 -> var 99
        assert completed["material_variance_cents"] == 99, completed["material_variance_cents"]
        assert completed["status"] == "COMPLETED"

    def test_material_variance_set_on_completion(self, api):
        """PRD §3.9: "On success it finalizes the consumed lots' issued_qty and
        seals the genealogy links for the order, computes the work order's
        material_variance_cents, sets the status to COMPLETED, and increments the
        order's version."

        Design: Difficulty/dual_variant_calc/workorder_material_variance_actual_vs_standard
        """
        ctx = setup_material_variance_scenario()
        wo = ctx["work_order"]
        completed = validate_success(api.complete_work_order(wo["id"], PLANNER))
        assert completed["status"] == "COMPLETED"
        assert completed["material_variance_cents"] == 99
