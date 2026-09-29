"""Fire pump selection: the catalogue walk, the curve figures and the seal it unblocks."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_fire_pump_shape,
    assert_flow,
    assert_margin,
    assert_pressure,
)
from test_helpers.fixtures import (
    append_iteration,
    build_converged_stage,
    build_project_stage,
    create_auxiliary_system,
    create_calculation,
    create_evaluation,
    create_fire_pump,
    create_flow_test,
    create_hazard_area,
    qc_pass,
    read_calculation,
    read_evaluation,
    read_project,
)
from test_helpers.test_users import make_design_engineer_headers

FP2602 = dict(
    project_number="FP-2602",
    building_name="Balcones Light Industrial",
    occupancy_type="INDUSTRIAL",
    building_height_ft=24.0,
    underground_lead_in_loss_psi=0.0,
)

ROOM_140 = dict(
    label="Assembly Room 140",
    hazard_class="ORDINARY_1",
    commodity_class="CLASS_III",
    storage_height_ft=8.0,
    ceiling_height_ft=12.0,
    area_sqft=1800.0,
    sprinkler_system_type="WET",
    ceiling_slope_pct=4.0,
    room_area_sqft=1200.0,
    enclosure_rating_hours=2.0,
    room_has_unprotected_opening=False,
)

H31 = dict(
    hydrant_tag="H-31",
    static_psi=110.0,
    residual_psi=50.0,
    flow_gpm=1300.0,
    tested_at="2026-06-02T16:00:00.000Z",
)

# HC-2 closes on a 247.5 gpm supply connection 25 ft above the previous node,
# which lands the required pressure at 109.20 psi against 79.77 psi available.
HC2_CHAIN = [
    dict(iteration_index=1, pipe_size_in="1.25", length_ft=100.0,
         fitting_equivalent_ft=30.0, flow_gpm=30.0, elevation_change_ft=20.0),
    dict(iteration_index=2, pipe_size_in="2", length_ft=120.0,
         fitting_equivalent_ft=25.0, flow_gpm=160.0, elevation_change_ft=0.0),
]
HC2_SUPPLY = dict(iteration_index=3, pipe_size_in="3", length_ft=220.0,
                  fitting_equivalent_ft=40.0, flow_gpm=247.5,
                  elevation_change_ft=25.0, is_supply_connection=True)


def _deficient_fp2602(client):
    """FP-2602 driven to a PRESSURE_DEFICIENT HC-2 and an inadequate evaluation."""
    ctx = build_project_stage(client, **FP2602)
    project_id, engineer_id = ctx["project_id"], ctx["lead_id"]
    area = create_hazard_area(client, project_id, engineer_id, **ROOM_140)
    ctx["standpipe"] = create_auxiliary_system(
        client, project_id, engineer_id,
        system_type="STANDPIPE_CLASS_II", label="Hose station risers", riser_count=5,
    )
    calculation = create_calculation(
        client, project_id, area["id"], engineer_id, k_factor=5.6
    )
    ctx["calculation_id"] = calculation["id"]
    for segment in HC2_CHAIN:
        append_iteration(client, calculation["id"], engineer_id, **segment)
    flow_test = create_flow_test(client, project_id, engineer_id, **H31)
    ctx["flow_test_id"] = flow_test["id"]
    create_evaluation(client, project_id, flow_test["id"], calculation["id"], engineer_id)
    append_iteration(client, calculation["id"], engineer_id, **HC2_SUPPLY)
    ctx["evaluation"] = create_evaluation(
        client, project_id, flow_test["id"], calculation["id"], engineer_id
    )
    ctx["evaluation_id"] = ctx["evaluation"]["id"]
    return ctx


class TestPumpCatalogueAndCurve:
    def test_01_the_catalogue_walk_and_the_ceil_to_five_rated_pressure(self, client):
        """`rated_flow_gpm` is the smallest catalogue rating that is greater than or equal
        to the evaluation's `design_demand_gpm`.

        Design: Difficulty/combinatorial_formula/fire_pump_sizing_catalogue_step_churn_and_150_pct_combination
        """
        ctx = _deficient_fp2602(client)
        assert_flow(ctx["standpipe"]["demand_gpm"], 400.0)
        assert_flow(ctx["evaluation"]["design_demand_gpm"], 897.5)
        assert_margin(ctx["evaluation"], 79.77, -29.43, -36.9, "INADEQUATE_PUMP_REQUIRED")

        pump = create_fire_pump(
            client,
            ctx["project_id"],
            ctx["evaluation_id"],
            ctx["evaluation"]["version"],
            ctx["lead_id"],
            model_tag="VT-1000-50",
        )
        assert_fire_pump_shape(pump)
        assert_flow(pump["rated_flow_gpm"], 1000.0)
        assert_pressure(pump["required_discharge_psi"], 119.20)
        assert pump["rated_pressure_psi"] == 50

    def test_02_suction_is_taken_at_the_catalogue_rated_flow_not_at_the_demand(self, client):
        """`suction_psi_at_rated` is the supply pressure available at the catalogue rated
        flow — not at the design demand.

        Design: Difficulty/combinatorial_formula/fire_pump_sizing_catalogue_step_churn_and_150_pct_combination
        """
        ctx = _deficient_fp2602(client)
        pump = create_fire_pump(
            client,
            ctx["project_id"],
            ctx["evaluation_id"],
            ctx["evaluation"]["version"],
            ctx["lead_id"],
            model_tag="VT-1000-50",
        )
        assert_pressure(pump["suction_psi_at_rated"], 73.07)
        # The projection at the 897.5 gpm demand would read 79.77 psi instead.
        assert_pressure(ctx["evaluation"]["available_psi_at_demand"], 79.77)

    def test_03_the_churn_point_above_the_relief_valve_ceiling_decides_the_verdict(
        self, client
    ):
        """Otherwise, if `churn_discharge_psi` is greater than the maximum churn pressure
        of 175.0 pounds per square inch, the verdict is `REQUIRES_PRESSURE_RELIEF_VALVE`.

        Design: Difficulty/combinatorial_formula/fire_pump_sizing_catalogue_step_churn_and_150_pct_combination
        """
        ctx = _deficient_fp2602(client)
        pump = create_fire_pump(
            client,
            ctx["project_id"],
            ctx["evaluation_id"],
            ctx["evaluation"]["version"],
            ctx["lead_id"],
            model_tag="VT-1000-50",
        )
        assert_pressure(pump["churn_discharge_psi"], 180.0)
        assert_flow(pump["flow_150_pct_gpm"], 1500.0)
        assert_pressure(pump["suction_psi_at_150_pct"], 31.81)
        assert_pressure(pump["available_psi_at_150_pct"], 64.31)
        assert pump["sizing_verdict"] == "REQUIRES_PRESSURE_RELIEF_VALVE"
        assert pump["state"] == "SIZED"

    def test_04_sizing_marks_the_evaluation_and_the_project(self, client):
        """The write also sets the evaluation's `pump_sized` to true and advances the
        evaluation's `version`, sets the project's `pump_required_flag` to true and
        advances the project's `version`.

        Design: Difficulty/combinatorial_formula/fire_pump_sizing_catalogue_step_churn_and_150_pct_combination
        """
        ctx = _deficient_fp2602(client)
        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "PRESSURE_DEFICIENT"
        assert_pressure(calculation["required_psi_at_base_of_riser"], 109.20)
        assert_pressure(calculation["deficiency_psi"], 29.43)

        create_fire_pump(
            client,
            ctx["project_id"],
            ctx["evaluation_id"],
            ctx["evaluation"]["version"],
            ctx["lead_id"],
            model_tag="VT-1000-50",
        )
        evaluation = read_evaluation(client, ctx["evaluation_id"])
        assert evaluation["pump_sized"] is True
        assert evaluation["version"] > ctx["evaluation"]["version"]
        assert read_project(client, ctx["project_id"])["pump_required_flag"] is True


H52 = dict(
    hydrant_tag="H-52",
    static_psi=50.0,
    residual_psi=30.0,
    flow_gpm=4000.0,
    tested_at="2026-06-02T14:00:00.000Z",
)


def _qc_passed_with_inadequate_supply(client):
    """HC-1 is QC-passed, then a weak hydrant leaves the newest evaluation inadequate."""
    ctx = build_converged_stage(client)
    ctx["calculation"] = qc_pass(
        client,
        ctx["calculation_id"],
        ctx["second_id"],
        review_note="Independent check of the most demanding area",
    )
    weak_test = create_flow_test(client, ctx["project_id"], ctx["lead_id"], **H52)
    ctx["weak_evaluation"] = create_evaluation(
        client,
        ctx["project_id"],
        weak_test["id"],
        ctx["calculation_id"],
        ctx["lead_id"],
    )
    return ctx


class TestSealBlockedUntilAnAcceptablePumpExists:
    def test_05_an_inadequate_newest_evaluation_refuses_the_seal(self, client):
        """Neither condition holding is refused with `ERR_SAFETY_MARGIN_UNRESOLVED` — a
        pump whose verdict is `REQUIRES_PRESSURE_RELIEF_VALVE`,
        `INSUFFICIENT_SUCTION_AT_150_PCT` or `INSUFFICIENT_AT_150_PCT` does not resolve
        anything.

        Design: Difficulty/cross_entity_state_dependency/seal_blocked_by_inadequate_evaluation_until_an_acceptable_fire_pump_references_it
        """
        ctx = _qc_passed_with_inadequate_supply(client)
        assert_margin(ctx["weak_evaluation"], 43.77, -11.77, -26.9, "INADEQUATE_PUMP_REQUIRED")

        refused = client.seal_calculation(
            ctx["calculation_id"], make_design_engineer_headers(ctx["lead_id"])
        )
        validate_error(refused, "ERR_SAFETY_MARGIN_UNRESOLVED", expected_status=409)

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "QC_PASSED"
        assert calculation["sealed_by_engineer_id"] is None
        assert calculation["sealed_at"] is None
        assert read_project(client, ctx["project_id"])["sealed_calculation_count"] == 0

    def test_06_an_acceptable_pump_against_that_evaluation_resolves_the_margin(self, client):
        """Otherwise the verdict is `ACCEPTABLE`.

        Design: Difficulty/cross_entity_state_dependency/seal_blocked_by_inadequate_evaluation_until_an_acceptable_fire_pump_references_it
        """
        ctx = _qc_passed_with_inadequate_supply(client)
        evaluation = ctx["weak_evaluation"]
        pump = create_fire_pump(
            client,
            ctx["project_id"],
            evaluation["id"],
            evaluation["version"],
            ctx["lead_id"],
            model_tag="Aurora 2500-A",
        )
        assert_flow(pump["rated_flow_gpm"], 2500.0)
        assert_pressure(pump["suction_psi_at_rated"], 41.62)
        assert_pressure(pump["required_discharge_psi"], 65.54)
        assert pump["rated_pressure_psi"] == 40
        assert_pressure(pump["churn_discharge_psi"], 106.0)
        assert_flow(pump["flow_150_pct_gpm"], 3750.0)
        assert_pressure(pump["suction_psi_at_150_pct"], 32.25)
        assert_pressure(pump["available_psi_at_150_pct"], 58.25)
        assert pump["sizing_verdict"] == "ACCEPTABLE"
        assert pump["state"] == "SIZED"
        assert read_evaluation(client, evaluation["id"])["pump_sized"] is True
        assert read_project(client, ctx["project_id"])["pump_required_flag"] is True

    def test_07_the_identical_seal_request_then_succeeds(self, client):
        """When all four pass, the calculation moves `QC_PASSED → SEALED`,
        `sealed_by_engineer_id` records the acting engineer, `sealed_at` records the
        current logical clock reading, the project's `sealed_calculation_count` rises by 1.

        Design: Difficulty/cross_entity_state_dependency/seal_blocked_by_inadequate_evaluation_until_an_acceptable_fire_pump_references_it
        """
        ctx = _qc_passed_with_inadequate_supply(client)
        headers = make_design_engineer_headers(ctx["lead_id"])
        validate_error(
            client.seal_calculation(ctx["calculation_id"], headers),
            "ERR_SAFETY_MARGIN_UNRESOLVED",
            expected_status=409,
        )
        evaluation = ctx["weak_evaluation"]
        create_fire_pump(
            client,
            ctx["project_id"],
            evaluation["id"],
            evaluation["version"],
            ctx["lead_id"],
            model_tag="Aurora 2500-A",
        )

        sealed = validate_success(
            client.seal_calculation(ctx["calculation_id"], headers), expected_status=200
        )
        assert sealed["state"] == "SEALED"
        assert sealed["sealed_by_engineer_id"] == ctx["lead_id"]
        assert str(sealed["sealed_at"]).startswith("2026-08-01T00:00:00")
        assert read_project(client, ctx["project_id"])["sealed_calculation_count"] == 1
