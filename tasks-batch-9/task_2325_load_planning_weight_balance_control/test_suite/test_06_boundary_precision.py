"""Figures probed exactly on the edge, one step inside it and one step past it."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ApiErrorId as E
from test_helpers import LOAD_CONTROLLER, LOAD_CONTROLLER_1, RAMP_AGENT, api_client
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import load_controller_headers

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


def _revise(flight_id: str, **conditions) -> dict:
    return get_success_data(
        api_client.patch_flight_conditions(flight_id, dict(conditions), LOAD_CONTROLLER)
    )


# ---------------------------------------------------------------------------
# The lower edge of a performance band's temperature interval
# ---------------------------------------------------------------------------


def _two_band_flight() -> fx.Scenario:
    """A runway publishing [15, 30) and [30, 45), flown at 22 degrees."""
    world = fx.reference_world(
        compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1], F.CANONICAL_BANDS[2]]
    )
    return fx.flight_world(world, flight_number="LX1650")


class TestTemperatureBandLowerBound:
    def test_a_tenth_below_the_edge_still_selects_the_warmer_band(self):
        """At 29.9 degrees the flight remains inside the band it was created in.

        PRD: "The interval is lower-inclusive and upper-exclusive: a band covers
        temperatures at or above `temp_lo_c` and strictly below `temp_hi_c`."

        Design: Difficulty/boundary_precision_check/temperature_band_lower_inclusive_boundary
        """
        world = _two_band_flight()
        A.assert_flight_capacity(
            world.flight,
            performance_limited_takeoff_weight_kg=73810.00,
            allowed_payload_kg=20180.00,
            limiting_factor="MZFW",
        )

        revised = _revise(world.flight_id, outside_air_temp_c=29.9)

        A.assert_flight_capacity(
            revised,
            performance_limited_takeoff_weight_kg=72790.00,
            allowed_payload_kg=20180.00,
            limiting_factor="MZFW",
        )

    def test_standing_exactly_on_the_edge_selects_the_next_band_and_flips_the_limit(self):
        """At exactly 30.0 degrees the next band applies and performance binds.

        PRD: "`limiting_factor` names which limit bound the flight, and it is
        resolved by walking a fixed precedence order — `PERFORMANCE`, then
        `MTOW`, then `MZFW`, then `MLW`, then `MAX_TAXI` — and taking the first
        candidate equal to the minimum."

        Design: Difficulty/boundary_precision_check/temperature_band_lower_inclusive_boundary
        """
        world = _two_band_flight()
        _revise(world.flight_id, outside_air_temp_c=29.9)

        revised = _revise(world.flight_id, outside_air_temp_c=30.0)

        A.assert_flight_capacity(
            revised,
            performance_limited_takeoff_weight_kg=70020.00,
            allowed_payload_kg=17920.00,
            limiting_factor="PERFORMANCE",
        )

    def test_the_temperature_penalty_resets_rather_than_carrying_across_the_bands(self):
        """The new band's penalty is measured from its own lower bound, not the old one.

        PRD: "The temperature penalty is 130 kilograms for each degree Celsius by
        which the flight's outside air temperature exceeds the band's `temp_lo_c`,
        and it is 0 when the temperature sits at or below that lower bound rather
        than becoming a credit."

        Design: Difficulty/boundary_precision_check/temperature_band_lower_inclusive_boundary
        """
        world = _two_band_flight()

        just_below = _revise(world.flight_id, outside_air_temp_c=29.9)
        at_the_edge = _revise(world.flight_id, outside_air_temp_c=30.0)

        A.assert_kg(
            float(just_below["performance_limited_takeoff_weight_kg"])
            - float(at_the_edge["performance_limited_takeoff_weight_kg"]),
            2770.00,
            "the performance drop across the band boundary",
        )
        for flight in (just_below, at_the_edge):
            A.assert_flight_capacity(
                flight, dry_operating_weight_kg=42550.00, dry_operating_index=62.53
            )


# ---------------------------------------------------------------------------
# A gate bag exactly as heavy as the remaining underload
# ---------------------------------------------------------------------------

_GATE_CARGO = "724-99990001"


def _hot_wet_world(flight_number: str, cargo_awb: str, cargo_weight_kg: float) -> fx.Scenario:
    """A performance-limited flight loaded to within a few hundred kilograms."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1", "H4"), band_specs=[F.CANONICAL_BANDS[2]]
    )
    fx.plan_world(
        world,
        flight_overrides={
            "flight_number": flight_number,
            "outside_air_temp_c": 30,
            "runway_condition": "WET",
        },
    )
    fx.seat(world, "OC", male_count=60)
    fx.stow_bags(world, "H1", 346, 4500)
    fx.book_and_stow_cargo(
        world, cargo_awb, "H4", item_kind="GENERAL", weight_kg=cargo_weight_kg, length_m=3.0
    )
    fx.compute_plan(world)
    return world


def _present_gate_bag(world: fx.Scenario, awb_number: str, weight_kg: float, length_m: float):
    return api_client.add_gate_bag(
        world.plan_id,
        F.gate_bag_payload(awb_number, weight_kg, world.compartment_id("H4"), length_m=length_m),
        RAMP_AGENT,
    )


class TestGateBagAtExactUnderload:
    def test_a_bag_exactly_as_heavy_as_the_underload_is_absorbed(self):
        """The absorption test is inclusive, so equality is admitted, not deferred.

        PRD: "When the plan's `gate_bag_policy` is `ABSORB_INTO_UNDERLOAD` and the
        bag's `weight_kg` is less than or equal to the plan's live `underload_kg`,
        the bag is set to `ACCEPTED`, `assigned_compartment_id` is set to the named
        hold, and both the live payload figures and the whole balance chain are
        re-run — so an absorbed bag can itself push the centre of gravity out of
        the envelope and be refused with `ERR_CG_OUT_OF_ENVELOPE`."

        Design: Difficulty/boundary_precision_check/gate_bag_absorbed_at_exact_underload_zero
        """
        world = _hot_wet_world("LX1660", _GATE_CARGO, 3040)
        A.assert_flight_capacity(
            fx.refresh_flight(world),
            performance_limited_takeoff_weight_kg=65120.00,
            allowed_payload_kg=13020.00,
            limiting_factor="PERFORMANCE",
        )
        A.assert_plan_figures(
            world.plan,
            base_payload_kg=12820.00,
            frozen_underload_kg=200.00,
            planned_payload_kg=12820.00,
            underload_kg=200.00,
            index_zfw=81.68,
            mac_zfw_pct=13.62,
            takeoff_weight_kg=64920.00,
            mac_tow_pct=14.77,
        )

        bag = get_success_data(_present_gate_bag(world, "GB-0001", 200, 0.6), 201)

        A.assert_cargo_state(
            bag,
            status="ACCEPTED",
            item_kind="GATE_BAG",
            assigned_compartment_id=world.compartment_id("H4"),
        )
        A.assert_plan_figures(
            fx.refresh_plan(world), planned_payload_kg=13020.00, underload_kg=0.00
        )

    def test_the_absorbed_bag_lands_the_takeoff_weight_exactly_on_the_performance_limit(self):
        """The aircraft is admissible at its limit, not one kilogram beyond it.

        PRD: "`envelope_ok` is true only when the zero-fuel percent-MAC figure
        sits at or above `zfw_fwd_limit_pct_mac` and at or below
        `zfw_aft_limit_pct_mac`, **and** the takeoff percent-MAC figure sits at or
        above `tow_fwd_limit_pct_mac` and at or below that effective aft bound."

        Design: Difficulty/boundary_precision_check/gate_bag_absorbed_at_exact_underload_zero
        """
        world = _hot_wet_world("LX1660", _GATE_CARGO, 3040)

        get_success_data(_present_gate_bag(world, "GB-0001", 200, 0.6), 201)

        plan = fx.refresh_plan(world)
        A.assert_plan_figures(
            plan,
            zero_fuel_weight_kg=55570.00,
            index_zfw=83.20,
            mac_zfw_pct=14.22,
            takeoff_weight_kg=65120.00,
            index_tow=91.80,
            mac_tow_pct=15.28,
            envelope_ok=True,
        )
        A.assert_kg(
            plan["takeoff_weight_kg"],
            float(fx.refresh_flight(world)["performance_limited_takeoff_weight_kg"]),
            "the takeoff weight against the performance limit",
        )
        A.assert_plan_figures(plan, base_payload_kg=12820.00, frozen_underload_kg=200.00)

    def test_the_next_bag_has_no_room_left_and_is_deferred(self):
        """One kilogram against a zero underload is deferred, changing no figure.

        PRD: "Otherwise — either because the policy is `DEFER_ALL`, or because the
        bag is heavier than the live underload — the bag moves `BOOKED` →
        `DEFERRED` and the plan's `deferred_bag_weight_kg` increases by the bag's
        `weight_kg`."

        Design: Difficulty/boundary_precision_check/gate_bag_absorbed_at_exact_underload_zero
        """
        world = _hot_wet_world("LX1660", _GATE_CARGO, 3040)
        get_success_data(_present_gate_bag(world, "GB-0001", 200, 0.6), 201)

        second = get_success_data(_present_gate_bag(world, "GB-0002", 1, 0.3), 201)

        A.assert_cargo_state(second, status="DEFERRED", assigned_compartment_id=None)
        A.assert_plan_figures(
            fx.refresh_plan(world),
            deferred_bag_weight_kg=1.00,
            planned_payload_kg=13020.00,
            underload_kg=0.00,
            index_tow=91.80,
        )


# ---------------------------------------------------------------------------
# A plan with no rows at all
# ---------------------------------------------------------------------------


def _empty_plan_world() -> fx.Scenario:
    world = fx.reference_world(compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]])
    return fx.plan_world(world, flight_overrides={"flight_number": "LX1670"})


class TestEmptyPlanCompute:
    def test_a_plan_with_no_rows_computes_a_zero_payload(self):
        """The three collections are all empty and the aggregate is 0.00, not an error.

        PRD: "The sum is published as `base_payload_kg`, and
        `frozen_underload_kg` is the flight's `allowed_payload_kg` less that base
        payload, rounded half-up to 2 decimals."

        Design: Difficulty/boundary_precision_check/empty_plan_zero_payload_compute
        """
        world = _empty_plan_world()

        computed = get_success_data(
            api_client.compute_load_plan(world.plan_id, LOAD_CONTROLLER), 200
        )

        A.assert_plan_figures(
            computed,
            status="COMPUTED",
            base_payload_kg=0.00,
            planned_payload_kg=0.00,
            frozen_underload_kg=20180.00,
            underload_kg=20180.00,
            restriction_status="UNRESTRICTED",
        )
        A.assert_flight_state(fx.refresh_flight(world), status="LOAD_CONTROLLED")

    def test_the_balance_chain_of_an_empty_plan_is_the_dry_operating_aircraft(self):
        """With no payload the zero-fuel figures are the dry operating figures.

        PRD: "Step two derives the weights, each rounded half-up to 2 decimals.
        `zero_fuel_weight_kg` is the flight's `dry_operating_weight_kg` plus the
        plan's `planned_payload_kg`."

        Design: Difficulty/boundary_precision_check/empty_plan_zero_payload_compute
        """
        world = _empty_plan_world()

        computed = get_success_data(
            api_client.compute_load_plan(world.plan_id, LOAD_CONTROLLER), 200
        )

        A.assert_plan_figures(
            computed,
            index_zfw=62.53,
            zero_fuel_weight_kg=42550.00,
            mac_zfw_pct=7.01,
            takeoff_weight_kg=52100.00,
            taxi_weight_kg=52350.00,
            landing_weight_kg=45200.00,
            index_tow=71.13,
            mac_tow_pct=9.66,
        )
        A.assert_index(
            computed["index_zfw"],
            float(fx.refresh_flight(world)["dry_operating_index"]),
            "the empty plan's zero-fuel index against the dry operating index",
        )

    def test_an_empty_plan_sits_inside_the_envelope_on_the_unreduced_aft_bound(self):
        """A takeoff weight under the knee weight is judged against the plain aft limit.

        PRD: "The effective aft takeoff bound is `tow_aft_limit_pct_mac`, plus
        `tow_aft_knee_adjust_pct_mac` when `takeoff_weight_kg` is strictly greater
        than `tow_knee_weight_kg` and plus nothing otherwise."

        Design: Difficulty/boundary_precision_check/empty_plan_zero_payload_compute
        """
        world = _empty_plan_world()

        computed = get_success_data(
            api_client.compute_load_plan(world.plan_id, LOAD_CONTROLLER), 200
        )

        A.assert_plan_figures(computed, envelope_ok=True)
        assert float(computed["takeoff_weight_kg"]) <= float(
            world.aircraft["tow_knee_weight_kg"]
        ), "an empty plan should not reach the knee weight"


# ---------------------------------------------------------------------------
# A last-minute change exactly consuming the allowance
# ---------------------------------------------------------------------------

_LMC_CARGO = "724-99991001"


def _tight_allowance_world() -> fx.Scenario:
    """An issued sheet whose allowance is the plan's 300 kg of spare capacity."""
    world = _hot_wet_world("LX1680", _LMC_CARGO, 2940)
    fx.issue_sheet(world, load_controller_headers(LOAD_CONTROLLER_1))
    return world


def _bag_addition(world: fx.Scenario, mass_kg: float):
    return api_client.create_last_minute_change(
        F.last_minute_change_payload(
            world.sheet_id, "BAG_ADD", world.compartment_id("H4"), mass_kg=mass_kg
        ),
        load_controller_headers(LOAD_CONTROLLER_1),
    )


class TestAllowanceExactBoundary:
    def test_the_allowance_is_the_smaller_of_the_cap_and_the_spare_capacity(self):
        """A plan with 300 kg of spare capacity grants a 300 kg allowance.

        PRD: "Issuance also computes the sheet's `lmc_allowance_kg`: the smaller of
        a hard cap of 500 kilograms and the plan's live `underload_kg`, with a
        negative underload treated as 0 — so a plan with 320 kilograms of spare
        capacity grants a 320-kilogram allowance, a plan with 4 tonnes of spare
        capacity grants the 500-kilogram cap, and a plan with no spare capacity
        grants none."

        Design: Difficulty/boundary_precision_check/lmc_allowance_exact_boundary
        """
        world = _tight_allowance_world()

        A.assert_plan_figures(
            fx.refresh_plan(world),
            base_payload_kg=12720.00,
            underload_kg=300.00,
            index_zfw=80.92,
            takeoff_weight_kg=64820.00,
            index_tow=89.52,
            mac_tow_pct=14.52,
        )
        A.assert_sheet_figures(
            world.sheet,
            lmc_allowance_kg=300.00,
            lmc_net_weight_delta_kg=0.00,
            lmc_absolute_weight_delta_kg=0.00,
            issued_takeoff_weight_kg=64820.00,
            issued_index_tow=89.52,
            issued_payload_kg=12720.00,
        )

    def test_a_change_that_exactly_consumes_the_allowance_is_admitted(self):
        """The admission test is an inequality that includes equality.

        PRD: "Admission of a new change is tested *before* it is persisted — the
        sheet's current absolute total plus the absolute value of the new change's
        `weight_delta_kg` must be less than or equal to `lmc_allowance_kg`, and a
        violation is refused with `ERR_LMC_ALLOWANCE_EXCEEDED` with nothing
        written."

        Design: Difficulty/boundary_precision_check/lmc_allowance_exact_boundary
        """
        world = _tight_allowance_world()

        change = get_success_data(_bag_addition(world, 300), 201)

        A.assert_kg(change["weight_delta_kg"], 300.00, "weight_delta_kg")
        A.assert_index(change["index_delta"], 2.28, "index_delta")
        assert change["status"] == "APPLIED", "an admitted change should read APPLIED"
        A.assert_sheet_figures(
            fx.refresh_sheet(world),
            lmc_net_weight_delta_kg=300.00,
            lmc_absolute_weight_delta_kg=300.00,
            final_takeoff_weight_kg=65120.00,
            final_index_tow=91.80,
            final_mac_tow_pct=15.28,
            final_payload_kg=13020.00,
        )

    def test_one_kilogram_past_the_allowance_is_refused_and_writes_nothing(self):
        """With the allowance exhausted the next kilogram is refused outright.

        PRD: "The allowance binds the absolute total, not the net one, which is
        the whole point: a 200-kilogram addition followed by a 200-kilogram
        removal nets to nothing but consumes 400 kilograms of allowance."

        Design: Difficulty/boundary_precision_check/lmc_allowance_exact_boundary
        """
        world = _tight_allowance_world()
        get_success_data(_bag_addition(world, 300), 201)

        response = _bag_addition(world, 1)

        validate_error(response, E.LMC_ALLOWANCE_EXCEEDED, 422)
        A.assert_sheet_figures(
            fx.refresh_sheet(world),
            lmc_absolute_weight_delta_kg=300.00,
            final_takeoff_weight_kg=65120.00,
        )
        rows, meta = validate_paginated(
            api_client.list_last_minute_changes(
                LOAD_CONTROLLER, {"load_sheet_id": world.sheet_id}
            )
        )
        A.assert_pagination_meta(meta, total_count=1)
