"""The supply evaluation: basis variants, the margin thresholds and supersession."""
import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_flow,
    assert_margin,
    assert_percentage,
    assert_pressure,
)
from test_helpers.fixtures import (
    build_converged_stage,
    build_evaluated_stage,
    create_evaluation,
    create_flow_test,
    read_evaluation,
    read_project,
)

# Hydrant H-31 is chosen so its projected curve lands one hundredth below the
# inclusive 10.00 psi adequacy threshold on the very same design demand.
H31 = dict(
    hydrant_tag="H-31",
    static_psi=91.0,
    residual_psi=43.0,
    flow_gpm=3000.0,
    tested_at="2026-05-20T15:00:00.000Z",
)


class TestSupplyBasisVariants:
    def test_01_seasonal_basis_derates_both_pressures_and_the_test_flow(self, client):
        """Under `SEASONAL_ADJUSTED`, a seasonal allowance of 10.0 pounds per square inch
        is subtracted from both pressures ... and the test flow is derated to 90 percent of
        the witnessed value.

        Design: Difficulty/dual_variant_calc/supply_basis_raw_versus_seasonal_flips_margin_verdict
        """
        ctx = build_evaluated_stage(client)
        raw = ctx["evaluation"]
        assert_pressure(raw["basis_static_psi"], 80.0)
        assert_pressure(raw["basis_residual_psi"], 64.0)
        assert_flow(raw["basis_test_flow_gpm"], 2250.0)

        seasonal = create_evaluation(
            client,
            ctx["project_id"],
            ctx["flow_test_id"],
            ctx["calculation_id"],
            ctx["lead_id"],
            evaluation_basis="SEASONAL_ADJUSTED",
        )
        assert_pressure(seasonal["basis_static_psi"], 70.0)
        assert_pressure(seasonal["basis_residual_psi"], 54.0)
        assert_flow(seasonal["basis_test_flow_gpm"], 2025.0)

    def test_02_the_same_field_test_flips_the_verdict_under_the_seasonal_basis(self, client):
        """The same field test therefore yields a lower available pressure under the
        seasonal basis, and can flip the verdict.

        Design: Difficulty/dual_variant_calc/supply_basis_raw_versus_seasonal_flips_margin_verdict
        """
        ctx = build_evaluated_stage(client)
        raw = ctx["evaluation"]
        assert_margin(raw, 65.54, 10.00, 15.3, "ADEQUATE")

        seasonal = create_evaluation(
            client,
            ctx["project_id"],
            ctx["flow_test_id"],
            ctx["calculation_id"],
            ctx["lead_id"],
            evaluation_basis="SEASONAL_ADJUSTED",
        )
        assert_flow(seasonal["design_demand_gpm"], 2130.0)
        assert_pressure(seasonal["required_psi_at_demand"], 55.54)
        assert_margin(seasonal, 52.43, -3.11, -5.9, "INADEQUATE_PUMP_REQUIRED")
        assert seasonal["pinned_calculation_iteration_count"] == 3
        assert seasonal["state"] == "EVALUATED"

    def test_03_the_flipped_verdict_supersedes_the_raw_row_and_raises_the_pump_flag(
        self, client
    ):
        """The project's `pump_required_flag` is set to true exactly when the new verdict
        is anything other than `ADEQUATE`, and the project's `version` advances.

        Design: Difficulty/dual_variant_calc/supply_basis_raw_versus_seasonal_flips_margin_verdict
        """
        ctx = build_evaluated_stage(client)
        raw_id = ctx["evaluation_id"]
        before = read_project(client, ctx["project_id"])
        assert before["pump_required_flag"] is False

        create_evaluation(
            client,
            ctx["project_id"],
            ctx["flow_test_id"],
            ctx["calculation_id"],
            ctx["lead_id"],
            evaluation_basis="SEASONAL_ADJUSTED",
        )

        assert read_evaluation(client, raw_id)["state"] == "SUPERSEDED"
        after = read_project(client, ctx["project_id"])
        assert after["pump_required_flag"] is True
        assert after["version"] > before["version"]
        # The calculation itself is untouched: it converged against the raw curve.
        fetched = validate_success(
            client.get_hydraulic_calculation(ctx["calculation_id"], ctx["lead_headers"])
        )
        assert fetched["state"] == "CONVERGED"


class TestSafetyMarginThreshold:
    def test_04_a_margin_of_exactly_ten_psi_is_adequate(self, client):
        """`margin_verdict` is then a three-way threshold over the margin, evaluated in
        order: a `safety_margin_psi` of at least 10.00 pounds per square inch is
        `ADEQUATE`.

        Design: Difficulty/boundary_precision_check/safety_margin_exactly_ten_psi_is_adequate_and_nine_ninety_nine_is_marginal
        """
        ctx = build_converged_stage(client)
        on_boundary = create_evaluation(
            client,
            ctx["project_id"],
            ctx["flow_test_id"],
            ctx["calculation_id"],
            ctx["lead_id"],
        )
        assert_flow(on_boundary["design_demand_gpm"], 2130.0)
        assert_pressure(on_boundary["required_psi_at_demand"], 55.54)
        assert_margin(on_boundary, 65.54, 10.00, 15.3, "ADEQUATE")

    def test_05_a_margin_one_hundredth_below_the_threshold_is_only_marginal(self, client):
        """`safety_margin_psi` is `available_psi_at_demand` less `required_psi_at_demand`,
        rounded to 2 decimal places, and `safety_margin_pct` expresses that margin as a
        percentage of `available_psi_at_demand`, rounded to 1 decimal place.

        Design: Difficulty/boundary_precision_check/safety_margin_exactly_ten_psi_is_adequate_and_nine_ninety_nine_is_marginal
        """
        ctx = build_converged_stage(client)
        second_test = create_flow_test(client, ctx["project_id"], ctx["lead_id"], **H31)
        one_hundredth_short = create_evaluation(
            client,
            ctx["project_id"],
            second_test["id"],
            ctx["calculation_id"],
            ctx["lead_id"],
        )
        assert_pressure(one_hundredth_short["required_psi_at_demand"], 55.54)
        assert_margin(one_hundredth_short, 65.53, 9.99, 15.2, "MARGINAL")

    def test_06_the_superseded_row_keeps_the_margin_it_was_written_with(self, client):
        """Creating a new evaluation moves any existing evaluation of the same project in
        state `EVALUATED` to `SUPERSEDED` before the new row is inserted.

        Design: Difficulty/boundary_precision_check/safety_margin_exactly_ten_psi_is_adequate_and_nine_ninety_nine_is_marginal
        """
        ctx = build_converged_stage(client)
        preliminary_id = ctx["preliminary_evaluation"]["id"]
        adequate = create_evaluation(
            client,
            ctx["project_id"],
            ctx["flow_test_id"],
            ctx["calculation_id"],
            ctx["lead_id"],
        )
        second_test = create_flow_test(client, ctx["project_id"], ctx["lead_id"], **H31)
        marginal = create_evaluation(
            client,
            ctx["project_id"],
            second_test["id"],
            ctx["calculation_id"],
            ctx["lead_id"],
        )

        frozen = read_evaluation(client, adequate["id"])
        assert frozen["state"] == "SUPERSEDED"
        assert_pressure(frozen["safety_margin_psi"], 10.00)
        assert_percentage(frozen["safety_margin_pct"], 15.3)
        assert frozen["margin_verdict"] == "ADEQUATE"
        assert read_evaluation(client, preliminary_id)["state"] == "SUPERSEDED"
        assert read_evaluation(client, marginal["id"])["state"] == "EVALUATED"

    def test_07_a_marginal_newest_verdict_still_raises_the_pump_flag(self, client):
        """otherwise a margin of at least 0.00 is `MARGINAL`; otherwise, with the required
        pressure above what the supply can deliver, the verdict is
        `INADEQUATE_PUMP_REQUIRED`. ... The project's `pump_required_flag` is set to true
        exactly when the new verdict is anything other than `ADEQUATE`.

        Design: Difficulty/boundary_precision_check/safety_margin_exactly_ten_psi_is_adequate_and_nine_ninety_nine_is_marginal
        """
        ctx = build_converged_stage(client)
        create_evaluation(
            client,
            ctx["project_id"],
            ctx["flow_test_id"],
            ctx["calculation_id"],
            ctx["lead_id"],
        )
        second_test = create_flow_test(client, ctx["project_id"], ctx["lead_id"], **H31)
        marginal = create_evaluation(
            client,
            ctx["project_id"],
            second_test["id"],
            ctx["calculation_id"],
            ctx["lead_id"],
        )
        assert marginal["margin_verdict"] == "MARGINAL"
        project = read_project(client, ctx["project_id"])
        # MARGINAL is "anything other than ADEQUATE", so the flag goes up.
        assert project["pump_required_flag"] is True
        assert pytest.approx(project["total_system_demand_gpm"], abs=0.05) == 2130.0
