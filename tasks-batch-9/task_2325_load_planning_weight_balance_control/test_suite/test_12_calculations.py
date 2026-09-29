"""Derived figures: the dry pair, the performance limit, the payload waterfall."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    AUDIT_INSPECTOR,
    LOAD_CONTROLLER,
    LOAD_CONTROLLER_1,
    RAMP_AGENT,
    api_client,
)
from test_helpers import ApiErrorId as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import load_controller_headers

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


def _controller():
    return load_controller_headers(LOAD_CONTROLLER_1)


def _flight(world: fx.Scenario, flight_number: str, **overrides):
    return api_client.create_flight(
        F.flight_payload(
            world.aircraft_id,
            world.runway_id,
            world.program_id,
            flight_number=flight_number,
            **overrides,
        ),
        LOAD_CONTROLLER,
    )


# ---------------------------------------------------------------------------
# The dry operating pair
# ---------------------------------------------------------------------------


class TestCrewAftOfReference:
    def test_a_crew_station_aft_of_the_reference_arm_raises_the_index(self):
        """A lighter crew seated aft moves the index up and the payload out.

        PRD: "`dry_operating_index` is obtained by taking the crew index delta —
        the crew weight multiplied by the difference between `crew_arm_m` and
        `ref_arm_m`, divided by `index_c`, that quotient rounded half-up to 2
        decimals — and adding it to `basic_index`, the sum then rounded half-up to
        2 decimals."

        Design: Corner/calculations/dry_operating_weight_and_index_with_a_forward_of_reference_crew
        """
        world = fx.reference_world(
            compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]]
        )

        response = _flight(
            world, "LX1608", crew_weight_kg=980, crew_arm_m=18.400
        )

        flight = get_success_data(response, 201)
        A.assert_flight_capacity(
            flight,
            dry_operating_weight_kg=42380.00,
            dry_operating_index=67.93,
            performance_limited_takeoff_weight_kg=73810.00,
            allowed_payload_kg=20350.00,
            limiting_factor="MZFW",
        )


# ---------------------------------------------------------------------------
# The performance-limited takeoff weight
# ---------------------------------------------------------------------------


class TestWindCreditCap:
    def test_ten_and_twelve_knots_of_headwind_buy_exactly_the_same_credit(self):
        """The credit saturates, so the extra two knots change nothing at all.

        PRD: "The wind credit is 90 kilograms per knot of headwind, computed from
        the headwind component with negative values — tailwinds — treated as zero
        knots, and then capped at 900 kilograms, so the credit saturates once the
        headwind reaches 10 knots and grows no further."

        Design: Corner/calculations/wind_credit_is_capped_by_the_declared_maximum
        """
        world = fx.reference_world(
            compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]]
        )

        at_the_cap = get_success_data(
            _flight(world, "LX1610", headwind_component_kt=10), 201
        )
        beyond_the_cap = get_success_data(
            _flight(
                world,
                "LX1612",
                headwind_component_kt=12,
                scheduled_off_block_utc="2026-08-15T13:20:00Z",
                scheduled_on_block_utc="2026-08-15T15:00:00Z",
            ),
            201,
        )

        for flight in (at_the_cap, beyond_the_cap):
            A.assert_flight_capacity(
                flight,
                performance_limited_takeoff_weight_kg=74170.00,
                allowed_payload_kg=20180.00,
                limiting_factor="MZFW",
            )


# ---------------------------------------------------------------------------
# The allowed payload waterfall
# ---------------------------------------------------------------------------


class TestAllowedPayloadWaterfall:
    def test_three_flights_make_three_different_limits_bind(self):
        """Fuel and weather decide which candidate wins the fixed precedence walk.

        PRD: "`limiting_factor` names which limit bound the flight, and it is
        resolved by walking a fixed precedence order — `PERFORMANCE`, then `MTOW`,
        then `MZFW`, then `MLW`, then `MAX_TAXI` — and taking the first candidate
        equal to the minimum."

        Design: Corner/calculations/allowed_payload_waterfall_reports_each_binding_limit_in_turn
        """
        world = fx.reference_world(
            compartment_specs=[],
            band_specs=[F.CANONICAL_BANDS[1], F.CANONICAL_BANDS[2]],
        )

        structural = get_success_data(_flight(world, "LX1620"), 201)
        landing_bound = get_success_data(
            _flight(
                world,
                "LX1622",
                ramp_fuel_kg=14000,
                scheduled_off_block_utc="2026-08-15T13:20:00Z",
                scheduled_on_block_utc="2026-08-15T15:00:00Z",
            ),
            201,
        )
        performance_bound = get_success_data(
            _flight(
                world,
                "LX1624",
                outside_air_temp_c=30,
                runway_condition="WET",
                scheduled_off_block_utc="2026-08-15T15:50:00Z",
                scheduled_on_block_utc="2026-08-15T17:30:00Z",
            ),
            201,
        )

        A.assert_flight_capacity(
            structural, allowed_payload_kg=20180.00, limiting_factor="MZFW"
        )
        A.assert_flight_capacity(
            landing_bound, allowed_payload_kg=16960.00, limiting_factor="MLW"
        )
        A.assert_flight_capacity(
            performance_bound,
            performance_limited_takeoff_weight_kg=65120.00,
            allowed_payload_kg=13020.00,
            limiting_factor="PERFORMANCE",
        )


# ---------------------------------------------------------------------------
# The base payload input set
# ---------------------------------------------------------------------------

_CG_STOWED = "724-11000001"
_CG_UNSTOWED = "724-11000002"
_CG_DG = "724-11000003"
_CG_REJECTED = "724-11000004"


class TestBasePayloadInputSet:
    def test_only_the_stowed_accepted_consignment_reaches_the_payload_and_the_index(self):
        """Four consignments sit on the flight and exactly one is counted.

        PRD: "Consignments in `BOOKED`, `REJECTED`, `OFFLOADED` or `DEFERRED`
        status are excluded, and every gate bag is excluded regardless of status."

        Design: Corner/calculations/base_payload_input_set_excludes_unstowed_booked_and_rejected_consignments
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC", "H1", "H4"),
            band_specs=[F.CANONICAL_BANDS[1]],
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})
        fx.seat(world, "OC", male_count=25, female_count=35)
        fx.stow_bags(world, "H1", 112, 1450)
        fx.book_and_stow_cargo(
            world, _CG_STOWED, "H4", item_kind="GENERAL", weight_kg=400, length_m=1.2
        )
        fx.book_cargo(world, _CG_UNSTOWED, item_kind="GENERAL", weight_kg=300, length_m=1.0)
        fx.book_and_stow_cargo(
            world, _CG_DG, "H4", item_kind="GENERAL", weight_kg=400, length_m=1.2,
            is_dangerous_goods=True,
        )
        fx.book_cargo(world, _CG_REJECTED, item_kind="GATE_BAG", weight_kg=250, length_m=0.8)
        validate_success(
            api_client.reject_cargo_item(world.cargo_id(_CG_REJECTED), RAMP_AGENT), 200
        )

        computed = fx.compute_plan(world)

        A.assert_plan_figures(
            computed,
            base_payload_kg=6500.00,
            planned_payload_kg=6500.00,
            index_zfw=81.70,
            zero_fuel_weight_kg=49050.00,
            mac_zfw_pct=15.39,
            takeoff_weight_kg=58600.00,
            index_tow=90.30,
            mac_tow_pct=16.37,
            underload_kg=13680.00,
        )
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_STOWED), status="ACCEPTED")
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_UNSTOWED), status="ACCEPTED")
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_DG), status="BOOKED")
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_REJECTED), status="REJECTED")


# ---------------------------------------------------------------------------
# The audit discrepancy bands
# ---------------------------------------------------------------------------


class TestAuditSeverityThreshold:
    def test_one_centikilogram_moves_the_finding_from_minor_to_major(self):
        """The minor band closes at exactly 500 kilograms, inclusive.

        PRD: "`severity` follows from that total against two thresholds, half a
        tonne and one tonne, with both band boundaries inclusive at their upper
        end: `NONE` when the total is exactly 0, `MINOR` when it is strictly above
        0 and at most 500 kilograms, `MAJOR` when it is strictly above 500
        kilograms and at most 1000 kilograms, and `CRITICAL` when it is strictly
        above 1000 kilograms."

        Design: Corner/calculations/audit_severity_threshold_between_minor_and_major
        """
        world = fx.fx_a_computed(flight_overrides={"flight_number": "LX1602"})

        minor = get_success_data(
            api_client.create_load_audit(
                F.load_audit_payload(world.flight_id, "DOCUMENTED_BASIS", 5150, 1450, 0),
                AUDIT_INSPECTOR,
            ),
            201,
        )
        major = get_success_data(
            api_client.create_load_audit(
                F.load_audit_payload(
                    world.flight_id, "DOCUMENTED_BASIS", 5150.01, 1450, 0
                ),
                AUDIT_INSPECTOR,
            ),
            201,
        )

        A.assert_audit_figures(
            minor,
            pax_delta_kg=500.00,
            bag_delta_kg=0.00,
            cargo_delta_kg=0.00,
            total_absolute_discrepancy_kg=500.00,
            severity="MINOR",
            status="OPEN",
        )
        A.assert_audit_figures(
            major,
            pax_delta_kg=500.01,
            total_absolute_discrepancy_kg=500.01,
            severity="MAJOR",
        )


# ---------------------------------------------------------------------------
# The last-minute-change allowance
# ---------------------------------------------------------------------------


class TestAllowanceHardCap:
    def test_a_generous_underload_still_grants_only_the_capped_allowance(self):
        """Fourteen tonnes of spare capacity buy the same 500 kilograms as four.

        PRD: "Issuance also computes the sheet's `lmc_allowance_kg`: the smaller of
        a hard cap of 500 kilograms and the plan's live `underload_kg`, with a
        negative underload treated as 0 — so a plan with 320 kilograms of spare
        capacity grants a 320-kilogram allowance, a plan with 4 tonnes of spare
        capacity grants the 500-kilogram cap, and a plan with no spare capacity
        grants none."

        Design: Corner/calculations/last_minute_change_allowance_is_hard_capped_at_issuance
        """
        world = fx.fx_a_computed(flight_overrides={"flight_number": "LX1602"})
        A.assert_plan_figures(world.plan, underload_kg=14080.00)

        response = api_client.create_load_sheet(
            F.load_sheet_payload(world.plan_id, int(world.plan["version"])), _controller()
        )

        sheet = get_success_data(response, 201)
        A.assert_sheet_figures(
            sheet,
            sheet_no=1,
            status="ISSUED",
            issued_by_user_id=LOAD_CONTROLLER_1,
            issued_takeoff_weight_kg=58200.00,
            issued_index_tow=87.26,
            issued_payload_kg=6100.00,
            weight_program_documentation_ref="OM-A 8.1.3 rev 12",
            lmc_allowance_kg=500.00,
            lmc_net_weight_delta_kg=0.00,
            lmc_absolute_weight_delta_kg=0.00,
            final_takeoff_weight_kg=58200.00,
            final_index_tow=87.26,
            final_mac_tow_pct=15.24,
            final_payload_kg=6100.00,
        )
        A.assert_plan_figures(fx.refresh_plan(world), status="SHEET_ISSUED")


# ---------------------------------------------------------------------------
# The weight-programme variant selector
# ---------------------------------------------------------------------------


class TestActualWeightDiscipline:
    def test_the_programme_decides_the_field_and_the_caller_may_not_differ(self):
        """Supplying the weighed figure is as wrong as omitting it, in each case.

        PRD: "Under a `STANDARD` programme the field is forbidden and supplying it
        is `ERR_ACTUAL_WEIGHT_NOT_PERMITTED`; under an `ACTUAL` programme the field
        is mandatory and omitting it is `ERR_ACTUAL_WEIGHT_REQUIRED`."

        Design: Corner/calculations/actual_weight_field_is_permitted_only_under_an_actual_weight_program
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        actual_program = fx.create_actual_weight_program()
        standard_flight = fx.create_flight(
            world.aircraft_id, world.runway_id, world.program_id, flight_number="LX1630"
        )
        actual_flight = fx.create_flight(
            world.aircraft_id,
            world.runway_id,
            str(actual_program["id"]),
            flight_number="LX1632",
            scheduled_off_block_utc="2026-08-15T13:20:00Z",
            scheduled_on_block_utc="2026-08-15T15:00:00Z",
        )
        standard_plan = fx.open_plan(str(standard_flight["id"]))
        actual_plan = fx.open_plan(str(actual_flight["id"]))

        validate_error(
            api_client.create_pax_line(
                F.pax_line_payload(
                    str(standard_plan["id"]),
                    world.compartment_id("OC"),
                    male_count=25,
                    female_count=35,
                    actual_weight_kg=4700,
                ),
                LOAD_CONTROLLER,
            ),
            E.ACTUAL_WEIGHT_NOT_PERMITTED,
            422,
        )
        validate_error(
            api_client.create_pax_line(
                F.pax_line_payload(
                    str(actual_plan["id"]),
                    world.compartment_id("OC"),
                    male_count=25,
                    female_count=35,
                ),
                LOAD_CONTROLLER,
            ),
            E.ACTUAL_WEIGHT_REQUIRED,
            422,
        )

        for plan in (standard_plan, actual_plan):
            rows, meta = validate_paginated(
                api_client.list_pax_lines(
                    LOAD_CONTROLLER, {"load_plan_id": str(plan["id"])}
                )
            )
            A.assert_pagination_meta(meta, total_count=0)


# ---------------------------------------------------------------------------
# The offload recompute against a frozen posture
# ---------------------------------------------------------------------------

_CG_COMPANY = "724-12000001"
_CG_GENERAL = "724-12000002"
_CG_MAIL = "724-12000003"


def _restricted_hot_wet_world() -> fx.Scenario:
    """A performance-limited flight carrying 360 kg more than it may."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1", "H4"),
        band_specs=[F.CANONICAL_BANDS[1], F.CANONICAL_BANDS[2]],
    )
    fx.plan_world(
        world,
        flight_overrides={
            "flight_number": "LX1640",
            "outside_air_temp_c": 30,
            "runway_condition": "WET",
        },
    )
    fx.seat(world, "OC", male_count=60)
    fx.stow_bags(world, "H1", 346, 4500)
    fx.book_and_stow_cargo(
        world, _CG_COMPANY, "H4", item_kind="COMPANY", weight_kg=400, length_m=1.2
    )
    fx.book_and_stow_cargo(
        world, _CG_GENERAL, "H4", item_kind="GENERAL", weight_kg=2200, length_m=3.0
    )
    fx.book_and_stow_cargo(
        world, _CG_MAIL, "H4", item_kind="MAIL", weight_kg=1000, length_m=1.6
    )
    fx.compute_plan(world)
    return world


class TestOffloadPreservesFrozenPosture:
    def test_the_recompute_moves_the_live_figures_and_leaves_the_frozen_ones(self):
        """The plan flies again, yet still records the restriction it was computed with.

        PRD: "Second, the plan's `planned_payload_kg` and `underload_kg` are
        refreshed from the surviving distribution and the entire index and
        percent-MAC chain is recomputed against it — with `frozen_underload_kg` and
        `restriction_status` left untouched, since those are frozen."

        Design: Corner/calculations/offload_recompute_preserves_the_frozen_restriction_posture
        """
        world = _restricted_hot_wet_world()
        A.assert_plan_figures(
            world.plan,
            status="RESTRICTED",
            base_payload_kg=13380.00,
            frozen_underload_kg=-360.00,
            restriction_status="WEIGHT_RESTRICTED",
            index_zfw=85.94,
            mac_zfw_pct=15.30,
            mac_tow_pct=16.20,
        )
        A.assert_flight_state(fx.refresh_flight(world), status="PLANNING")

        response = api_client.apply_offload(world.plan_id, LOAD_CONTROLLER)

        relieved = get_success_data(response, 200)
        A.assert_plan_figures(
            relieved,
            status="COMPUTED",
            base_payload_kg=13380.00,
            frozen_underload_kg=-360.00,
            restriction_status="WEIGHT_RESTRICTED",
            planned_payload_kg=12980.00,
            underload_kg=40.00,
            index_zfw=82.90,
            zero_fuel_weight_kg=55530.00,
            mac_zfw_pct=14.11,
            takeoff_weight_kg=65080.00,
            index_tow=91.50,
            mac_tow_pct=15.18,
            envelope_ok=True,
        )
        A.assert_cargo_state(
            fx.refresh_cargo(world, _CG_COMPANY),
            status="OFFLOADED",
            assigned_compartment_id=None,
        )
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_GENERAL), status="ACCEPTED")
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_MAIL), status="ACCEPTED")
        A.assert_flight_state(fx.refresh_flight(world), status="LOAD_CONTROLLED")
