"""Optimistic concurrency and a saturating rate, exercised end to end."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
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


def _controller():
    return load_controller_headers(LOAD_CONTROLLER_1)


# ---------------------------------------------------------------------------
# The flight version quoted when a plan is opened
# ---------------------------------------------------------------------------


class TestStaleFlightVersionOnPlanCreation:
    def test_a_conditions_update_invalidates_the_version_the_caller_had_read(self):
        """The refused create leaves no plan behind and re-quoting succeeds.

        PRD: "A `POST /load-plans` request must carry `expected_flight_version` as a
        non-optional field of the body, holding the client's last observed `version`
        of the target `Flight`. If that value does not equal the flight's current
        `version`, the create is rejected with `ERR_STALE_FLIGHT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_flight_version_rejected_on_plan_creation
        """
        world = fx.reference_world(
            compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")
        version_before_the_update = int(world.flight["version"])
        retuned = get_success_data(
            api_client.patch_flight_conditions(
                world.flight_id, {"outside_air_temp_c": 24}, LOAD_CONTROLLER
            ),
            200,
        )
        current_version = int(retuned["version"])
        assert current_version > version_before_the_update, (
            "retuning the departure conditions should have advanced the flight version"
        )

        on_a_stale_read = api_client.create_load_plan(
            F.load_plan_payload(world.flight_id, version_before_the_update),
            LOAD_CONTROLLER,
        )

        validate_error(on_a_stale_read, E.STALE_FLIGHT_VERSION, 412)
        rows, meta = validate_paginated(
            api_client.list_flight_load_plans(world.flight_id, LOAD_CONTROLLER)
        )
        A.assert_pagination_meta(meta, total_count=0)
        assert rows == [], "a refused create should not have opened a plan"
        flight = fx.refresh_flight(world)
        A.assert_version_is(flight, current_version, "flight")
        assert float(flight["outside_air_temp_c"]) == 24, (
            "the flight should still carry the retuned outside air temperature"
        )

        after_refreshing = api_client.create_load_plan(
            F.load_plan_payload(world.flight_id, current_version), LOAD_CONTROLLER
        )

        plan = get_success_data(after_refreshing, 201)
        assert plan["revision_no"] == 1, (
            f"the flight's first plan should be revision 1 but was {plan['revision_no']}"
        )
        A.assert_plan_figures(plan, status="DRAFT")
        rows, meta = validate_paginated(
            api_client.list_flight_load_plans(world.flight_id, LOAD_CONTROLLER)
        )
        A.assert_pagination_meta(meta, total_count=1)
        assert A.ids_of(rows) == [str(plan["id"])], (
            "the flight should now list exactly the plan that was just opened"
        )


# ---------------------------------------------------------------------------
# The plan version quoted when a sheet is issued
# ---------------------------------------------------------------------------

_GATE_BAG = "724-26000001"


class TestStalePlanVersionOnSheetIssuance:
    def test_an_absorbed_gate_bag_moves_the_plan_on_without_leaving_computed(self):
        """The plan stays issuable, yet the revision the caller read is gone.

        PRD: "A `POST /load-sheets` request must carry `expected_load_plan_version` as
        a non-optional field of the body, holding the client's last observed `version`
        of the target `LoadPlan`. If that value does not equal the plan's current
        `version`, issuance is rejected with `ERR_STALE_LOAD_PLAN_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_rejected_on_sheet_issuance
        """
        world = fx.fx_a_computed(flight_overrides={"flight_number": "LX1602"})
        A.assert_plan_figures(
            world.plan,
            status="COMPUTED",
            base_payload_kg=6100.00,
            underload_kg=14080.00,
            index_tow=87.26,
        )
        version_before_the_bag = int(world.plan["version"])
        get_success_data(
            api_client.add_gate_bag(
                world.plan_id,
                F.gate_bag_payload(_GATE_BAG, 100, world.compartment_id("H1")),
                RAMP_AGENT,
            ),
            201,
        )

        absorbed = fx.refresh_plan(world)

        A.assert_plan_figures(
            absorbed,
            status="COMPUTED",
            base_payload_kg=6100.00,
            planned_payload_kg=6200.00,
            deferred_bag_weight_kg=0.00,
            underload_kg=13980.00,
            index_tow=86.48,
            mac_tow_pct=14.90,
        )
        current_version = int(absorbed["version"])
        assert current_version > version_before_the_bag, (
            "absorbing a gate bag should have advanced the plan version"
        )

        on_a_stale_read = api_client.create_load_sheet(
            F.load_sheet_payload(world.plan_id, version_before_the_bag), _controller()
        )

        validate_error(on_a_stale_read, E.STALE_LOAD_PLAN_VERSION, 412)
        rows, meta = validate_paginated(
            api_client.list_load_plan_load_sheets(world.plan_id, LOAD_CONTROLLER)
        )
        A.assert_pagination_meta(meta, total_count=0)
        assert rows == [], "a refused issuance should not have created a sheet"

        after_refreshing = api_client.create_load_sheet(
            F.load_sheet_payload(world.plan_id, current_version), _controller()
        )

        sheet = get_success_data(after_refreshing, 201)
        A.assert_sheet_figures(
            sheet,
            sheet_no=1,
            status="ISSUED",
            issued_takeoff_weight_kg=58300.00,
            issued_index_tow=86.48,
            issued_payload_kg=6200.00,
            lmc_allowance_kg=500.00,
            weight_program_documentation_ref="OM-A 8.1.3 rev 12",
        )


# ---------------------------------------------------------------------------
# The saturating headwind credit
# ---------------------------------------------------------------------------


class TestHeadwindCreditSaturation:
    def test_two_rotations_differing_only_in_headwind_derive_one_payload(self):
        """Past the ceiling the reported wind stops buying anything at all.

        PRD: "The wind credit is 90 kilograms per knot of headwind, computed from the
        headwind component with negative values — tailwinds — treated as zero knots,
        and then capped at 900 kilograms, so the credit saturates once the headwind
        reaches 10 knots and grows no further."

        Design: Corner/cross_cutting_complexity_layers/headwind_credit_saturates_at_the_declared_cap
        """
        world = fx.reference_world(
            compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]]
        )

        at_the_ceiling = api_client.create_flight(
            F.flight_payload(
                world.aircraft_id,
                world.runway_id,
                world.program_id,
                flight_number="LX1620",
                headwind_component_kt=10,
            ),
            LOAD_CONTROLLER,
        )
        beyond_the_ceiling = api_client.create_flight(
            F.flight_payload(
                world.aircraft_id,
                world.runway_id,
                world.program_id,
                flight_number="LX1622",
                headwind_component_kt=12,
                scheduled_off_block_utc="2026-08-15T14:00:00Z",
                scheduled_on_block_utc="2026-08-15T16:00:00Z",
            ),
            LOAD_CONTROLLER,
        )

        ten_knots = get_success_data(at_the_ceiling, 201)
        twelve_knots = get_success_data(beyond_the_ceiling, 201)
        for flight in (ten_knots, twelve_knots):
            A.assert_flight_capacity(
                flight,
                dry_operating_weight_kg=42550.00,
                dry_operating_index=62.53,
                performance_limited_takeoff_weight_kg=74170.00,
                allowed_payload_kg=20180.00,
                limiting_factor="MZFW",
            )
        confirmed = get_success_data(
            api_client.get_flight(str(twelve_knots["id"]), AUDIT_INSPECTOR), 200
        )
        A.assert_flight_capacity(
            confirmed, performance_limited_takeoff_weight_kg=74170.00
        )
