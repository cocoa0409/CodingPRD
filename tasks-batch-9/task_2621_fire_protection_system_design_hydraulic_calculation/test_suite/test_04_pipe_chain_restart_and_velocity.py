"""The pipe-sizing chain: the deficiency restart loop and the velocity ceiling."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import assert_flow, assert_pressure
from test_helpers.fixtures import (
    CHAIN_SUPPLY_ITERATION,
    append_iteration,
    build_iterating_stage,
    build_project_stage,
    create_calculation,
    create_evaluation,
    create_hazard_area,
    read_calculation,
    read_project,
)
from test_helpers.test_users import make_design_engineer_headers
from test_helpers.factories import build_iteration_payload

# The revised chain opens on a 130 gpm branch line, which re-derives the end head
# from 19.05 psi to 26.61 psi.
RESTART_ITERATION = dict(
    iteration_index=4, pipe_size_in="3", length_ft=30.0, fitting_equivalent_ft=10.0,
    flow_gpm=130.0, elevation_change_ft=0.0, restart_chain=True,
)
REPEAT_SUPPLY_ITERATION = dict(CHAIN_SUPPLY_ITERATION, iteration_index=5)


def _seasonally_evaluated_iterating(client):
    """HC-1 at two iterations, measured against a seasonally derated supply."""
    ctx = build_iterating_stage(client)
    ctx["seasonal_evaluation"] = create_evaluation(
        client,
        ctx["project_id"],
        ctx["flow_test_id"],
        ctx["calculation_id"],
        ctx["lead_id"],
        evaluation_basis="SEASONAL_ADJUSTED",
    )
    return ctx


class TestPressureDeficientRestartLoop:
    def test_01_a_short_supply_connection_marks_the_calculation_pressure_deficient(
        self, client
    ):
        """When that figure is strictly greater than the evaluation's
        `available_psi_at_demand`, the calculation moves `ITERATING → PRESSURE_DEFICIENT`
        instead, `deficiency_psi` records the shortfall.

        Design: Difficulty/non_linear_state_machine/calculation_pressure_deficient_restart_loop_reconverges_on_new_chain
        """
        ctx = _seasonally_evaluated_iterating(client)
        assert_pressure(ctx["seasonal_evaluation"]["available_psi_at_demand"], 52.43)

        closing = append_iteration(
            client, ctx["calculation_id"], ctx["lead_id"], **CHAIN_SUPPLY_ITERATION
        )
        assert_pressure(closing["cumulative_psi_after"], 50.54)

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "PRESSURE_DEFICIENT"
        assert_pressure(calculation["deficiency_psi"], 3.11)
        assert read_project(client, ctx["project_id"])["pump_required_flag"] is True

    def test_02_the_restart_moves_the_window_and_re_derives_the_end_head(self, client):
        """An iteration with `restart_chain` true raises the calculation's
        `chain_start_index` to that iteration's own `iteration_index`, resets
        `iteration_count` to 1, marks every earlier iteration `in_active_chain` false
        without deleting it, and re-derives `end_head_psi` from this iteration's
        `flow_gpm`.

        Design: Difficulty/non_linear_state_machine/calculation_pressure_deficient_restart_loop_reconverges_on_new_chain
        """
        ctx = _seasonally_evaluated_iterating(client)
        headers = make_design_engineer_headers(ctx["lead_id"])
        append_iteration(client, ctx["calculation_id"], ctx["lead_id"], **CHAIN_SUPPLY_ITERATION)

        restarted = append_iteration(
            client, ctx["calculation_id"], ctx["lead_id"], **RESTART_ITERATION
        )
        assert_pressure(restarted["friction_loss_psi"], 0.89)
        assert restarted["velocity_fps"] == 5.64
        assert_pressure(restarted["cumulative_psi_after"], 27.50)
        assert restarted["in_active_chain"] is True

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "ITERATING"
        assert calculation["chain_start_index"] == 4
        assert calculation["iteration_count"] == 1
        assert_pressure(calculation["end_head_psi"], 26.61)

        rows = validate_success(client.list_iterations(ctx["calculation_id"], headers))
        by_index = {row["iteration_index"]: row for row in rows}
        assert by_index[1]["in_active_chain"] is False
        assert by_index[2]["in_active_chain"] is False
        assert by_index[3]["in_active_chain"] is False
        assert by_index[4]["in_active_chain"] is True

    def test_03_the_revised_chain_reconverges_and_the_ledger_picks_it_up(self, client):
        """When that figure is less than or equal to the evaluation's
        `available_psi_at_demand`, the calculation moves `ITERATING → CONVERGED`,
        `deficiency_psi` is set to null, and the project demand ledger is recomputed.

        Design: Difficulty/non_linear_state_machine/calculation_pressure_deficient_restart_loop_reconverges_on_new_chain
        """
        ctx = _seasonally_evaluated_iterating(client)
        headers = make_design_engineer_headers(ctx["lead_id"])
        append_iteration(client, ctx["calculation_id"], ctx["lead_id"], **CHAIN_SUPPLY_ITERATION)
        append_iteration(client, ctx["calculation_id"], ctx["lead_id"], **RESTART_ITERATION)
        closing = append_iteration(
            client, ctx["calculation_id"], ctx["lead_id"], **REPEAT_SUPPLY_ITERATION
        )
        assert_pressure(closing["cumulative_psi_after"], 32.76)

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "CONVERGED"
        assert calculation["deficiency_psi"] is None
        assert calculation["iteration_count"] == 2
        assert_pressure(calculation["required_psi_at_base_of_riser"], 32.76)

        rows = validate_success(client.list_iterations(ctx["calculation_id"], headers))
        assert len(rows) == 5, "the restart must not delete superseded rows"

        project = read_project(client, ctx["project_id"])
        assert project["governing_hydraulic_calculation_id"] == ctx["calculation_id"]
        assert_flow(project["governing_demand_gpm"], 1380.0)
        assert_flow(project["total_system_demand_gpm"], 2130.0)


FP2604 = dict(
    project_number="FP-2604",
    building_name="Guadalupe Street Retail",
    occupancy_type="MERCANTILE",
    building_height_ft=22.0,
    underground_lead_in_loss_psi=0.0,
)

SALES_FLOOR = dict(
    label="Sales floor",
    hazard_class="ORDINARY_1",
    commodity_class="CLASS_II",
    storage_height_ft=6.0,
    ceiling_height_ft=16.0,
    area_sqft=9000.0,
    sprinkler_system_type="WET",
    ceiling_slope_pct=None,
    room_area_sqft=None,
    enclosure_rating_hours=None,
    room_has_unprotected_opening=None,
)

# 0.4085 * 334.7 / 2.067^2 lands on 32.00 fps exactly; a tenth of a gpm more
# lands on 32.01 fps.
AT_THE_LIMIT = dict(
    iteration_index=1, pipe_size_in="2", length_ft=20.0, fitting_equivalent_ft=5.0,
    flow_gpm=334.7, elevation_change_ft=0.0,
)
ONE_HUNDREDTH_OVER = dict(AT_THE_LIMIT, iteration_index=2, flow_gpm=334.8)


def _fresh_draft_calculation(client):
    ctx = build_project_stage(client, **FP2604)
    area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **SALES_FLOOR)
    calculation = create_calculation(
        client, ctx["project_id"], area["id"], ctx["lead_id"], k_factor=25.2
    )
    ctx["calculation_id"] = calculation["id"]
    return ctx


class TestVelocityLimitBoundary:
    def test_04_exactly_thirty_two_feet_per_second_is_accepted(self, client):
        """A segment whose derived `velocity_fps` exceeds the velocity limit of 32.00 feet
        per second is rejected with `ERR_VELOCITY_LIMIT_EXCEEDED`, and the boundary is
        inclusive at the limit: exactly 32.00 is accepted, and 32.01 is refused.

        Design: Difficulty/boundary_precision_check/velocity_limit_accepts_exactly_thirty_two_fps_and_rejects_thirty_two_point_zero_one
        """
        ctx = _fresh_draft_calculation(client)
        headers = make_design_engineer_headers(ctx["lead_id"])
        created = validate_success(
            client.append_iteration(
                ctx["calculation_id"], build_iteration_payload(**AT_THE_LIMIT), headers
            ),
            expected_status=201,
        )
        assert created["velocity_fps"] == 32.00
        assert_pressure(created["friction_loss_psi"], 21.95)
        assert_pressure(created["cumulative_psi_after"], 198.35)

        calculation = read_calculation(client, ctx["calculation_id"])
        assert_pressure(calculation["end_head_psi"], 176.40)
        assert_pressure(calculation["required_psi_at_base_of_riser"], 198.35)
        assert calculation["iteration_count"] == 1
        assert calculation["state"] == "ITERATING"

    def test_05_thirty_two_point_zero_one_is_refused_and_leaves_no_trace(self, client):
        """`velocity_fps` is 0.4085 multiplied by the segment's `flow_gpm`, divided by the
        square of the internal diameter, rounded to 2 decimal places.

        Design: Difficulty/boundary_precision_check/velocity_limit_accepts_exactly_thirty_two_fps_and_rejects_thirty_two_point_zero_one
        """
        ctx = _fresh_draft_calculation(client)
        headers = make_design_engineer_headers(ctx["lead_id"])
        validate_success(
            client.append_iteration(
                ctx["calculation_id"], build_iteration_payload(**AT_THE_LIMIT), headers
            ),
            expected_status=201,
        )
        refused = client.append_iteration(
            ctx["calculation_id"], build_iteration_payload(**ONE_HUNDREDTH_OVER), headers
        )
        validate_error(refused, "ERR_VELOCITY_LIMIT_EXCEEDED", expected_status=422)

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["iteration_count"] == 1
        assert_pressure(calculation["required_psi_at_base_of_riser"], 198.35)
        assert calculation["state"] == "ITERATING"
        rows = validate_success(client.list_iterations(ctx["calculation_id"], headers))
        assert len(rows) == 1
