"""Nesting yield mathematics: theoretical vs realized variants, rotation
branches, floor precision, and the layout feasibility gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_imposition_plan,
    create_brand_approved_revision,
    create_customer,
    create_design_revision_payload,
    create_draft_plan,
    create_imposition_plan_payload,
    create_job,
    get_job,
    make_brand_quality_headers,
    setup_in_production_job,
    setup_engineering_job,
    setup_press_ready_job,
    start_engineering,
    validate_error,
    validate_success,
    get_success_data,
)
from test_helpers.fixtures import ADMIN, DESIGNER, OPERATOR
from test_helpers.api_client import api_client


class TestTheoreticalVsRealizedYield:
    def test_realized_variant_fills_from_actuals_while_theoretical_stays_fixed(
        self, api
    ):
        """PRD §3.3: "The realized quality fields — `realized_sheets_printed` and `realized_good_sheets`, both zero at creation, and `realized_waste_milli_pct`, which stays null until a press booking completes — are filled in later from production actuals (§3.5); the theoretical fields never change once computed."
        PRD §3.5: "Third, the job's `LOCKED` imposition plan absorbs the realized picture: `realized_sheets_printed` takes the job's `sheets_consumed_actual`, `realized_good_sheets` takes the job's `good_sheets_actual`, and `realized_waste_milli_pct` is recomputed as the difference between printed and good sheets, multiplied by 100000 and floor-divided by the printed sheets — remaining null while no sheets have been printed."

        Design: Difficulty/dual_variant_calc/nesting_theoretical_vs_realized_yield
        """
        ctx = setup_in_production_job(quantity_ordered=3000)
        plan_before = validate_success(
            api.get_imposition_plan(ctx["plan"]["id"], ADMIN), 200
        )
        assert plan_before["gross_sheets"] == 130, "theoretical gross at creation"
        assert plan_before["net_sheets"] == 120
        assert plan_before["realized_sheets_printed"] == 0
        assert plan_before["realized_good_sheets"] == 0
        assert plan_before["realized_waste_milli_pct"] is None

        validate_success(
            api.complete_press_booking(
                ctx["booking"]["id"],
                {"sheets_printed": 130, "sheets_good": 120},
                OPERATOR,
            ),
            200,
        )

        plan_after = validate_success(
            api.get_imposition_plan(ctx["plan"]["id"], ADMIN), 200
        )
        assert_imposition_plan(plan_after)
        # Theoretical variant unchanged by actuals.
        assert plan_after["gross_sheets"] == 130
        assert plan_after["net_sheets"] == 120
        # Realized variant recomputed from job actuals.
        assert plan_after["realized_sheets_printed"] == 130
        assert plan_after["realized_good_sheets"] == 120
        # floor((130 - 120) * 100000 / 130) == 7692
        assert plan_after["realized_waste_milli_pct"] == 7692

    def test_realized_waste_null_until_first_completion(self, api):
        """PRD §3.3: "`realized_waste_milli_pct`, which stays null until a press booking completes".

        Design: Difficulty/dual_variant_calc/nesting_theoretical_vs_realized_yield
        """
        ctx = setup_press_ready_job(quantity_ordered=3000)
        plan = validate_success(api.get_imposition_plan(ctx["plan"]["id"], ADMIN), 200)
        assert plan["status"] == "LOCKED"
        assert plan["realized_sheets_printed"] == 0
        assert plan["realized_good_sheets"] == 0
        assert (
            plan["realized_waste_milli_pct"] is None
        ), "waste must stay null while no sheets have been printed"


class TestNestingRotationBranches:
    def _job_with_revision(self, api, brand_code, grain_allowed):
        customer = create_customer(name="Gamma", brand_code=brand_code)
        job = create_job(
            customer["id"],
            quantity_ordered=3000,
            blank_w_cin=500,
            blank_h_cin=1200,
            grain_rotation_allowed=grain_allowed,
            finish_coat=False,
            required_ink_slots=[],
        )
        job = start_engineering(job["id"])
        job = get_job(job["id"])
        revision = get_success_data(
            api.create_design_revision(
                create_design_revision_payload(
                    job["id"],
                    job["version"],
                    blank_w_cin=500,
                    blank_h_cin=1200,
                    grain_rotation_allowed=grain_allowed,
                ),
                DESIGNER,
            )
        )
        return job, revision

    def test_rotation_allowed_picks_strictly_better_rotated_yield(self, api):
        """PRD §3.3: "Otherwise `ups` is the larger of the two yields, with ties broken toward `NORMAL` — the `orientation` is `NORMAL` whenever the normal yield is at least the rotated yield, and `ROTATED` only when rotation strictly wins."
        PRD §3.3: "The `gross_sheets` applies the route's spoilage uplift to `net_sheets`: for an `OFFSET` job, `net_sheets` multiplied by 108 and divided by 100 with the quotient rounded up"

        Design: Difficulty/combinatorial_formula/nesting_rotation_branch_floors
        """
        job, revision = self._job_with_revision(api, "GMR", grain_allowed=True)
        plan = validate_success(
            api.create_imposition_plan(
                create_imposition_plan_payload(job["id"], revision["id"]), DESIGNER
            ),
            201,
        )
        assert_imposition_plan(plan)
        # usable 4680x3450: NORMAL 8x2=16 vs ROTATED 3x6=18 -> rotation wins.
        assert plan["ups"] == 18
        assert plan["orientation"] == "ROTATED"
        assert plan["net_sheets"] == 167  # ceil(3000/18)
        assert plan["gross_sheets"] == 181  # ceil(167*108/100), OFFSET uplift
        # floor(18 * 500 * 1200 * 100000 / (4800*3600)) == 62500
        assert plan["layout_yield_milli_pct"] == 62500

    def test_rotation_forbidden_forces_normal_yield(self, api):
        """PRD §3.3: "When the governing revision's `grain_rotation_allowed` is false, rotation is forbidden outright: the plan's `ups` is the normal yield and its `orientation` records `NORMAL`."

        Design: Difficulty/combinatorial_formula/nesting_rotation_branch_floors
        """
        job, revision = self._job_with_revision(api, "GMN", grain_allowed=False)
        plan = validate_success(
            api.create_imposition_plan(
                create_imposition_plan_payload(job["id"], revision["id"]), DESIGNER
            ),
            201,
        )
        assert plan["ups"] == 16
        assert plan["orientation"] == "NORMAL"
        assert plan["net_sheets"] == 188  # ceil(3000/16)
        assert plan["gross_sheets"] == 204  # ceil(188*108/100)
        # floor(16 * 500 * 1200 * 100000 / (4800*3600)) == 55555
        assert plan["layout_yield_milli_pct"] == 55555


def test_plan_layout_yield_floor_precision(api):
    """PRD §3.3: "The `layout_yield_milli_pct` expresses area efficiency: `ups` times the blank width times the blank height, multiplied by 100000, then floor-divided by the sheet area (`sheet_w_cin` times `sheet_h_cin`)."
    PRD §3.3: "The `net_sheets` is the job's `quantity_ordered` ceiling-divided by `ups`."

    Design: Corner/calculations/plan_layout_yield_floor_precision
    """
    ctx = setup_engineering_job(
        customer_name="Acme", brand_code="ACM", standard=False, stock=False,
        quantity_ordered=3000, required_ink_slots=[],
    )
    revision = get_success_data(
        api_client.create_design_revision(
            create_design_revision_payload(
                ctx["job"]["id"], ctx["job"]["version"]
            ),
            DESIGNER,
        )
    )
    plan = validate_success(
        api.create_imposition_plan(
            create_imposition_plan_payload(ctx["job"]["id"], revision["id"]),
            DESIGNER,
        ),
        201,
    )
    assert_imposition_plan(plan)
    # usable 4680x3450 -> 5x5 = 25 NORMAL (25 >= 21 rotated)
    assert plan["ups"] == 25
    assert plan["orientation"] == "NORMAL"
    assert plan["net_sheets"] == 120
    assert plan["gross_sheets"] == 130
    # floor(25 * 900 * 600 * 100000 / 17280000) == 78125 exactly
    assert plan["layout_yield_milli_pct"] == 78125
    assert plan["status"] == "DRAFT"
