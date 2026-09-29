"""Multi-term formulas whose pinned evaluation order decides the published figure."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ApiErrorId as E
from test_helpers import LOAD_CONTROLLER, api_client
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    """The subset of the canonical layout a test actually needs."""
    return [_SPECS[code] for code in codes]


def _revise(flight_id: str, **conditions) -> dict:
    return get_success_data(
        api_client.patch_flight_conditions(flight_id, dict(conditions), LOAD_CONTROLLER)
    )


# ---------------------------------------------------------------------------
# Performance-limited takeoff weight
# ---------------------------------------------------------------------------


class TestPerformanceLimitedWeightPenaltyStack:
    def test_each_revised_condition_reprices_the_performance_limit(self):
        """Temperature, wind and surface each move the performance limit in turn.

        PRD: "The three rounded adjustments are combined with the band's
        `base_limit_weight_kg`: subtract the altitude penalty, subtract the
        temperature penalty, add the wind credit."

        Design: Difficulty/combinatorial_formula/performance_limited_weight_nonlinear_penalty_stack
        """
        world = fx.flight_world(fx.reference_world(compartment_specs=[]), flight_number="LX1610")

        A.assert_flight_capacity(
            world.flight,
            dry_operating_weight_kg=42550.00,
            dry_operating_index=62.53,
            performance_limited_takeoff_weight_kg=73810.00,
            allowed_payload_kg=20180.00,
            limiting_factor="MZFW",
        )

        cool = _revise(world.flight_id, outside_air_temp_c=15)
        A.assert_flight_capacity(
            cool,
            performance_limited_takeoff_weight_kg=74720.00,
            allowed_payload_kg=20180.00,
            limiting_factor="MZFW",
        )

        hot = _revise(world.flight_id, outside_air_temp_c=30)
        A.assert_flight_capacity(
            hot,
            performance_limited_takeoff_weight_kg=70020.00,
            allowed_payload_kg=17920.00,
            limiting_factor="PERFORMANCE",
        )

        windy = _revise(world.flight_id, headwind_component_kt=12)
        A.assert_flight_capacity(
            windy,
            performance_limited_takeoff_weight_kg=70380.00,
            allowed_payload_kg=18280.00,
        )

        wet = _revise(world.flight_id, runway_condition="WET")
        A.assert_flight_capacity(
            wet,
            performance_limited_takeoff_weight_kg=65460.00,
            allowed_payload_kg=13360.00,
            limiting_factor="PERFORMANCE",
        )

    def test_the_contamination_factor_multiplies_the_bracket_before_the_floor(self):
        """The wet factor scales the whole bracketed figure, then the floor applies.

        PRD: "The evaluation order is pinned and must not be rearranged:
        adjustments and their rounding first, then the bracket, then the
        multiplicative factor, then the floor."

        Design: Difficulty/combinatorial_formula/performance_limited_weight_nonlinear_penalty_stack
        """
        world = fx.flight_world(fx.reference_world(compartment_specs=[]), flight_number="LX1610")
        _revise(world.flight_id, outside_air_temp_c=30)
        dry = _revise(world.flight_id, headwind_component_kt=12)
        A.assert_kg(
            dry["performance_limited_takeoff_weight_kg"], 70380.00, "the dry performance limit"
        )

        wet = _revise(world.flight_id, runway_condition="WET")

        A.assert_kg(
            wet["performance_limited_takeoff_weight_kg"], 65460.00, "the wet performance limit"
        )
        A.assert_multiple_of_ten(
            wet["performance_limited_takeoff_weight_kg"], "performance_limited_takeoff_weight_kg"
        )
        assert float(wet["performance_limited_takeoff_weight_kg"]) != pytest.approx(
            round(float(dry["performance_limited_takeoff_weight_kg"]) * 0.93, 2), abs=0.01
        ), "the wet factor should apply to the bracket, not to the already-floored dry figure"

    def test_every_revision_advances_the_flight_version_by_one(self):
        """Four revisions on a flight created at version 1 leave it at version 5.

        PRD: "The revision re-runs band selection, so a temperature moved outside
        every published band fails with `ERR_NO_PERFORMANCE_BAND` and nothing is
        written; it re-checks fuel coherence, failing with
        `ERR_FUEL_FIGURES_INCONSISTENT`; and on success it re-derives the dry
        operating figures, `performance_limited_takeoff_weight_kg`,
        `allowed_payload_kg` and `limiting_factor`, and increments the flight's
        `version` by 1."

        Design: Difficulty/combinatorial_formula/performance_limited_weight_nonlinear_penalty_stack
        """
        world = fx.flight_world(fx.reference_world(compartment_specs=[]), flight_number="LX1610")
        A.assert_version_is(world.flight, 1, "a freshly opened flight")

        _revise(world.flight_id, outside_air_temp_c=15)
        _revise(world.flight_id, outside_air_temp_c=30)
        _revise(world.flight_id, headwind_component_kt=12)
        final = _revise(world.flight_id, runway_condition="WET")

        A.assert_version_is(final, 5, "a flight revised four times")


# ---------------------------------------------------------------------------
# Index rounding mode
# ---------------------------------------------------------------------------


def _rounding_pair():
    """The same distribution computed under both index rounding modes."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H5"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    per_line = fx.flight_world(world, flight_number="LX1612")
    plan_a = fx.open_plan(per_line.flight_id)
    flight_b = fx.create_flight(
        world.aircraft_id,
        world.runway_id,
        world.program_id,
        flight_number="LX1614",
        scheduled_off_block_utc="2026-08-15T14:00:00Z",
        scheduled_on_block_utc="2026-08-15T16:30:00Z",
    )
    plan_b = fx.open_plan(str(flight_b["id"]), rounding_mode="SUM_THEN_ROUND")

    for plan_id in (str(plan_a["id"]), str(plan_b["id"])):
        fx.add_pax_line(
            plan_id,
            world.compartment_id("OC"),
            male_count=50,
            child_count=6,
            infant_count=4,
        )
        fx.add_bag_allocation(plan_id, world.compartment_id("H5"), 48, 625)

    computed_a = get_success_data(
        api_client.compute_load_plan(str(plan_a["id"]), LOAD_CONTROLLER)
    )
    computed_b = get_success_data(
        api_client.compute_load_plan(str(plan_b["id"]), LOAD_CONTROLLER)
    )
    return computed_a, computed_b


class TestIndexRoundingOrder:
    def test_per_line_then_sum_retains_the_per_row_rounding(self):
        """The contract default rounds each row's contribution before summing.

        PRD: "Under `PER_LINE_THEN_SUM` — the contract default — `index_zfw` is
        the flight's `dry_operating_index` plus the sum, over every passenger
        line, of that line's raw contribution rounded half-up to 2 decimals, plus
        the same per-row-rounded sum over every bag allocation, plus the same
        per-row-rounded sum over every counted consignment at its assigned hold's
        `arm_m`."

        Design: Difficulty/combinatorial_formula/index_rounding_order_per_line_vs_sum
        """
        per_line, _ = _rounding_pair()

        A.assert_plan_figures(
            per_line,
            rounding_mode="PER_LINE_THEN_SUM",
            base_payload_kg=5275.00,
            zero_fuel_weight_kg=47825.00,
            index_zfw=97.10,
            mac_zfw_pct=23.45,
            index_tow=105.70,
            mac_tow_pct=23.11,
        )

    def test_sum_then_round_rounds_the_accumulated_total_exactly_once(self):
        """The alternative mode accumulates at full precision and rounds once.

        PRD: "Under `SUM_THEN_ROUND`, all of those raw contributions are instead
        summed at full precision together with `dry_operating_index` and the
        total is rounded half-up to 2 decimals exactly once."

        Design: Difficulty/combinatorial_formula/index_rounding_order_per_line_vs_sum
        """
        _, summed = _rounding_pair()

        A.assert_plan_figures(
            summed,
            rounding_mode="SUM_THEN_ROUND",
            base_payload_kg=5275.00,
            zero_fuel_weight_kg=47825.00,
            index_zfw=97.09,
            mac_zfw_pct=23.44,
            index_tow=105.69,
            mac_tow_pct=23.11,
        )

    def test_the_two_modes_differ_by_one_index_hundredth_on_the_same_mass(self):
        """Identical masses, identical weights, one hundredth of an index apart.

        PRD: "The two modes deliberately produce different values of `index_zfw`
        for the same distribution — the first retains accumulated per-row
        rounding, the second does not — and consequently different values of
        `mac_zfw_pct`."

        Design: Difficulty/combinatorial_formula/index_rounding_order_per_line_vs_sum
        """
        per_line, summed = _rounding_pair()

        A.assert_kg(
            float(per_line["base_payload_kg"]),
            float(summed["base_payload_kg"]),
            "the base payload under the two rounding modes",
        )
        A.assert_index(
            float(per_line["index_zfw"]) - float(summed["index_zfw"]),
            0.01,
            "the zero-fuel index gap between the two rounding modes",
        )
        A.assert_pct_mac(
            float(per_line["mac_zfw_pct"]) - float(summed["mac_zfw_pct"]),
            0.01,
            "the zero-fuel percent-MAC gap between the two rounding modes",
        )


# ---------------------------------------------------------------------------
# Weight-dependent aft envelope bound
# ---------------------------------------------------------------------------


def _knee_world():
    """One airframe carrying two flights, one over the knee weight and one under."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1", "H4", "H5"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    fx.flight_world(world, flight_number="LX1616")
    heavy_plan = fx.open_plan(world.flight_id)
    fx.add_pax_line(str(heavy_plan["id"]), world.compartment_id("OC"), male_count=54)
    fx.add_bag_allocation(str(heavy_plan["id"]), world.compartment_id("H1"), 92, 1200)
    fx.add_bag_allocation(str(heavy_plan["id"]), world.compartment_id("H4"), 184, 2400)
    fx.add_bag_allocation(str(heavy_plan["id"]), world.compartment_id("H5"), 69, 900)
    world.plan = heavy_plan

    light_flight = fx.create_flight(
        world.aircraft_id,
        world.runway_id,
        world.program_id,
        flight_number="LX1618",
        scheduled_off_block_utc="2026-08-15T14:00:00Z",
        scheduled_on_block_utc="2026-08-15T16:30:00Z",
    )
    light_plan = fx.open_plan(str(light_flight["id"]))
    fx.add_pax_line(str(light_plan["id"]), world.compartment_id("OC"), male_count=60)
    fx.add_bag_allocation(str(light_plan["id"]), world.compartment_id("H4"), 169, 2200)
    fx.add_bag_allocation(str(light_plan["id"]), world.compartment_id("H5"), 8, 100)
    return world, heavy_plan, light_flight, light_plan


class TestEnvelopeKneeEvaluationOrder:
    def test_a_takeoff_weight_above_the_knee_reduces_the_aft_bound_and_refuses(self):
        """Over the knee weight the aft bound tightens and the aft load is refused.

        PRD: "The effective aft takeoff bound is `tow_aft_limit_pct_mac`, plus
        `tow_aft_knee_adjust_pct_mac` when `takeoff_weight_kg` is strictly
        greater than `tow_knee_weight_kg` and plus nothing otherwise."

        Design: Difficulty/combinatorial_formula/envelope_knee_evaluation_order_weight_then_limit
        """
        world, heavy_plan, _, _ = _knee_world()

        response = api_client.compute_load_plan(str(heavy_plan["id"]), LOAD_CONTROLLER)

        validate_error(response, E.CG_OUT_OF_ENVELOPE, 422)
        A.assert_plan_figures(
            fx.refresh_plan(world),
            status="DRAFT",
            envelope_ok=False,
            base_payload_kg=0.00,
        )
        A.assert_flight_state(fx.refresh_flight(world), status="PLANNING")

    def test_a_takeoff_weight_at_or_below_the_knee_keeps_the_unreduced_aft_bound(self):
        """Under the knee weight the same aft-heavy geometry passes the envelope.

        PRD: "`envelope_ok` is true only when the zero-fuel percent-MAC figure
        sits at or above `zfw_fwd_limit_pct_mac` and at or below
        `zfw_aft_limit_pct_mac`, **and** the takeoff percent-MAC figure sits at
        or above `tow_fwd_limit_pct_mac` and at or below that effective aft
        bound."

        Design: Difficulty/combinatorial_formula/envelope_knee_evaluation_order_weight_then_limit
        """
        _, _, light_flight, light_plan = _knee_world()

        computed = get_success_data(
            api_client.compute_load_plan(str(light_plan["id"]), LOAD_CONTROLLER), 200
        )

        A.assert_plan_figures(
            computed,
            status="COMPUTED",
            base_payload_kg=7580.00,
            index_zfw=111.54,
            mac_zfw_pct=29.23,
            takeoff_weight_kg=59680.00,
            index_tow=120.14,
            mac_tow_pct=27.98,
            envelope_ok=True,
        )
        flight = get_success_data(
            api_client.get_flight(str(light_flight["id"]), LOAD_CONTROLLER)
        )
        A.assert_flight_state(flight, status="LOAD_CONTROLLED")

    def test_the_refused_compute_persists_nothing(self):
        """A refused compute leaves the plan and the flight exactly where they were.

        PRD: "A compute, an offload application or a gate-bag absorption that
        would leave either percent-MAC figure outside its weight-adjusted bound
        is refused with `ERR_CG_OUT_OF_ENVELOPE` and persists nothing at all."

        Design: Difficulty/combinatorial_formula/envelope_knee_evaluation_order_weight_then_limit
        """
        world, heavy_plan, _, _ = _knee_world()
        before = get_success_data(
            api_client.get_load_plan(str(heavy_plan["id"]), LOAD_CONTROLLER)
        )

        validate_error(
            api_client.compute_load_plan(str(heavy_plan["id"]), LOAD_CONTROLLER),
            E.CG_OUT_OF_ENVELOPE,
            422,
        )

        after = get_success_data(
            api_client.get_load_plan(str(heavy_plan["id"]), LOAD_CONTROLLER)
        )
        A.assert_unchanged(before, after, "a plan whose compute was refused")
        A.assert_plan_figures(
            after,
            status="DRAFT",
            base_payload_kg=0.00,
            takeoff_weight_kg=0.00,
            index_zfw=0.00,
            envelope_ok=False,
        )
