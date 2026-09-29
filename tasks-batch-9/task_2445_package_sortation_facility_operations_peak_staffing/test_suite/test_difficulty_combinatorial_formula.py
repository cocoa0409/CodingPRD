"""Combinatorial formulas: the pinned cube rounding order, the pinned flex-premium
evaluation order, and the automation tier interacting with the posture multiplier
and the per-line floor.

Every test builds its own world from scratch — the harness relaunches the API
server before each individual test, so the database is empty and the logical
clock sits at its startup default 2026-08-01T00:00:00Z.
"""

import pytest

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers.api_errors import ERR_LABOR_BUDGET_EXCEEDED
from test_helpers.assertions import (
    expected_batch_cube,
    expected_cube_after_scan,
    expected_cube_utilization_pct,
    expected_planned_labor_cents,
    expected_provisional_cost_per_package,
    expected_required_headcount,
)
from test_helpers.test_users import LABOR_PLANNER_USER_ID, OPS_MANAGER_HEADERS

# ─── The mixed size-class batch ───
BATCH_SMALL = 1201
BATCH_MEDIUM = 907
BATCH_LARGE = 301
BATCH_OVERSIZED = 13
BATCH_PACKAGES = BATCH_SMALL + BATCH_MEDIUM + BATCH_LARGE + BATCH_OVERSIZED
BATCH_TRAILER_CUBE = 3800.00
INDUCTED_PACKAGES = 3000

# ─── The peak shift both approval tests price ───
PEAK_SHIFT_DATE = "2026-08-03"
PEAK_SHIFT_START = "2026-08-03T06:00:00Z"
PEAK_SHIFT_END = "2026-08-03T14:00:00Z"
PEAK_SHIFT_HOURS = 8.00
PEAK_FORECAST_VOLUME = 96000
PEAK_CORE = 10
FLEX_POOL_TOTAL = 20
PEAK_BUDGET_CENTS = 300000
BASE_BEFORE_PREMIUM_CENTS = 231520
PRICED_SHIFT_CENTS = 243096


def _two_line_mid_tier_center(world):
    """A center on the mid automation tier with two commissioned lines, so the
    line count is 2 and the per-line floor is eight associates."""
    center = world.create_center(
        automation_utilization_pct=70.00, flex_pool_total=FLEX_POOL_TOTAL
    )
    world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    world.create_chute(center["id"], chute_number=2, throughput_pph=1200)
    return world.center(center["id"])


def _restricted_manual_center(world):
    """A center whose automation utilization of 40 puts it on the bottom
    throughput tier and, being below 45, makes it `RESTRICTED` from creation."""
    center = world.create_center(
        automation_utilization_pct=40.00, flex_pool_total=FLEX_POOL_TOTAL
    )
    world.create_chute(center["id"], chute_number=1, throughput_pph=900)
    world.create_chute(center["id"], chute_number=2, throughput_pph=900)
    return center


def _submitted_peak_plan(world, center_id, labor_budget_cents):
    """A submitted plan for a 96,000-package peak shift staffed with ten core
    bodies, so a requirement of 13 leaves a flex draw of 3."""
    return world.create_submitted_plan(
        center_id,
        shift_date=PEAK_SHIFT_DATE,
        shift_window_start=PEAK_SHIFT_START,
        shift_window_end=PEAK_SHIFT_END,
        forecast_volume=PEAK_FORECAST_VOLUME,
        planned_core_headcount=PEAK_CORE,
        planned_seasonal_headcount=0,
        labor_budget_cents=labor_budget_cents,
    )


def test_mixed_size_class_batch_rounds_every_class_line_before_the_lines_are_summed(
    world, facility
):
    """PRD §3.8: "Each class line is computed on its own and rounded half up to two decimal places: the small line is its count multiplied by 0.335 cubic feet per package, the medium line its count multiplied by 1.205, the large line its count multiplied by 3.755, and the oversized line its count multiplied by 11.505."
    PRD §3.8: "Summing the unrounded products and rounding once at the end is explicitly *not* the contract and diverges from it on realistic batch mixes."

    Design: Difficulty/combinatorial_formula/cube_consumption_per_line_rounding_then_sum
    """
    center = facility["center"]
    lane = facility["lane"]
    world.induct_packages(
        center["id"], facility["inbound_door"]["id"], INDUCTED_PACKAGES
    )
    load = world.stage_load(
        center["id"],
        facility["outbound_door"]["id"],
        lane["id"],
        trailer_cube_cuft=BATCH_TRAILER_CUBE,
    )

    load = world.scan(
        load["id"],
        small_count=BATCH_SMALL,
        medium_count=BATCH_MEDIUM,
        large_count=BATCH_LARGE,
        oversized_count=BATCH_OVERSIZED,
    )

    expected_cube = expected_batch_cube(
        BATCH_SMALL, BATCH_MEDIUM, BATCH_LARGE, BATCH_OVERSIZED
    )
    assert expected_cube == pytest.approx(2775.11, abs=1e-6), (
        f"402.34 + 1092.94 + 1130.26 + 149.57 is 2775.11 cubic feet, got {expected_cube}"
    )
    assert float(load["cube_used_cuft"]) == pytest.approx(2775.11, abs=1e-6), (
        f"expected cube_used_cuft 2775.11, got {load['cube_used_cuft']}"
    )
    assert float(load["cube_used_cuft"]) != pytest.approx(2775.09, abs=1e-6), (
        "2775.09 is the figure the forbidden sum-then-round order produces"
    )

    expected_pct = expected_cube_utilization_pct(2775.11, BATCH_TRAILER_CUBE)
    assert expected_pct == pytest.approx(73.03, abs=1e-6), (
        f"2775.11 / 3800.00 * 100 is 73.03 percent, got {expected_pct}"
    )
    assert float(load["cube_utilization_pct"]) == pytest.approx(73.03, abs=1e-6), (
        f"expected cube_utilization_pct 73.03, got {load['cube_utilization_pct']}"
    )
    assert load["package_count"] == BATCH_PACKAGES, (
        f"expected package_count {BATCH_PACKAGES}, got {load['package_count']}"
    )
    assert load["load_status"] == "LOADING", (
        f"the first successful scan advances the load to LOADING, got {load['load_status']}"
    )

    assert world.lane(lane["id"])["sorted_package_count"] == BATCH_PACKAGES, (
        "the scanned quantity lands on the destination lane"
    )
    assert world.center(center["id"])["wip_package_count"] == (
        INDUCTED_PACKAGES - BATCH_PACKAGES
    ), "the scanned quantity leaves work-in-process"


def test_second_scan_adds_its_batch_cube_onto_the_already_rounded_stored_cube(
    world, facility
):
    """PRD §3.8: "The batch's cube is added to the load's stored `cube_used_cuft` and the sum is rounded half up to two decimal places again."

    Design: Difficulty/combinatorial_formula/cube_consumption_per_line_rounding_then_sum
    """
    center = facility["center"]
    world.induct_packages(center["id"], facility["inbound_door"]["id"], 100)
    load = world.stage_load(
        center["id"], facility["outbound_door"]["id"], facility["lane"]["id"]
    )

    first = world.scan(load["id"], small_count=3)
    assert float(first["cube_used_cuft"]) == pytest.approx(1.01, abs=1e-6), (
        "3 * 0.335 is 1.005 cubic feet, which rounds half up to 1.01, got "
        f"{first['cube_used_cuft']}"
    )

    second = world.scan(load["id"], small_count=3)
    expected_running = expected_cube_after_scan(1.01, small=3)
    assert expected_running == pytest.approx(2.02, abs=1e-6), (
        f"1.01 stored plus a 1.01 batch is 2.02 cubic feet, got {expected_running}"
    )
    assert float(second["cube_used_cuft"]) == pytest.approx(2.02, abs=1e-6), (
        "the second batch accumulates on top of the stored figure, got "
        f"{second['cube_used_cuft']}"
    )
    assert float(second["cube_used_cuft"]) != pytest.approx(2.01, abs=1e-6), (
        "2.01 is what recomputing six small packages from scratch would produce"
    )
    assert float(second["cube_utilization_pct"]) == pytest.approx(0.20, abs=1e-6), (
        f"2.02 / 1000.00 * 100 is 0.20 percent, got {second['cube_utilization_pct']}"
    )
    assert second["package_count"] == 6, (
        f"six small packages have been scanned in total, got {second['package_count']}"
    )
    assert second["load_status"] == "LOADING", (
        f"every subsequent scan is a LOADING self-loop, got {second['load_status']}"
    )


def test_planned_labor_prices_the_flex_premium_from_the_drawn_headcount(world):
    """PRD §3.5: "`planned_labor_cents` is the base cost multiplied by one plus the premium, rounded half up to whole cents."
    PRD §3.5: "The premium tier follows from that ratio: no premium at all when the ratio is below 0.20; a premium of 5 percent when the ratio is at least 0.20 but below 0.35; a premium of 12 percent when the ratio is at least 0.35."

    Design: Difficulty/combinatorial_formula/planned_labor_flex_premium_evaluation_order
    """
    center = _two_line_mid_tier_center(world)
    plan = _submitted_peak_plan(world, center["id"], PEAK_BUDGET_CENTS)

    assert plan["required_headcount"] == 13, (
        "96,000 packages over 950 packages per associate-hour and 8.00 hours ceils to "
        f"13 associates, got {plan['required_headcount']}"
    )

    approved = world.approve_plan(plan["id"], center["id"])

    assert approved["status"] == "APPROVED", (
        f"expected the plan to be APPROVED, got {approved['status']}"
    )
    assert approved["flex_draw_count"] == 3, (
        "13 required less 10 core and 0 seasonal draws 3 bodies from the bench, got "
        f"{approved['flex_draw_count']}"
    )

    expected_price = expected_planned_labor_cents(PEAK_CORE, 0, 3, PEAK_SHIFT_HOURS)
    assert expected_price == PRICED_SHIFT_CENTS, (
        "a base of 172,000 + 59,520 = 231,520 cents at a flex ratio of 3/13 attracts "
        f"the 5 percent tier and prices at 243,096 cents, got {expected_price}"
    )
    assert approved["planned_labor_cents"] == PRICED_SHIFT_CENTS, (
        f"expected planned_labor_cents {PRICED_SHIFT_CENTS}, got "
        f"{approved['planned_labor_cents']}"
    )
    assert approved["planned_labor_cents"] != BASE_BEFORE_PREMIUM_CENTS, (
        "231,520 cents is the pre-premium base, not the priced shift"
    )

    expected_provisional = expected_provisional_cost_per_package(
        PRICED_SHIFT_CENTS, PEAK_FORECAST_VOLUME
    )
    assert expected_provisional == pytest.approx(2.66, abs=1e-6), (
        f"(243,096 + 12,000) / 96,000 is 2.66 cents per package, got {expected_provisional}"
    )
    assert float(approved["provisional_cost_per_package_cents"]) == pytest.approx(
        2.66, abs=1e-6
    ), (
        "expected provisional_cost_per_package_cents 2.66, got "
        f"{approved['provisional_cost_per_package_cents']}"
    )
    assert approved["committed_headcount"] == 13, (
        "10 core plus 0 seasonal plus a draw of 3 is committed, got "
        f"{approved['committed_headcount']}"
    )
    assert approved["staffing_gap"] == 0, (
        f"the requirement is fully covered, got {approved['staffing_gap']}"
    )

    reread = world.center(center["id"])
    assert reread["flex_pool_available"] == 17, (
        f"the bench of 20 gives up 3 bodies, got {reread['flex_pool_available']}"
    )
    assert reread["flex_pool_reserved"] == 3, (
        f"the draw is reserved against the plan, got {reread['flex_pool_reserved']}"
    )


def test_approve_rejected_when_only_the_post_premium_price_exceeds_the_budget(world, api):
    """PRD §3.5: "The budget gate compares that post-premium `planned_labor_cents` against the plan's `labor_budget_cents` and refuses with `ERR_LABOR_BUDGET_EXCEEDED` (HTTP 402) when the priced shift is the larger."
    PRD §3.5: "Comparing the pre-premium base against the budget is not the contract."

    Design: Difficulty/combinatorial_formula/planned_labor_flex_premium_evaluation_order
    """
    center = _two_line_mid_tier_center(world)
    budget = 240000
    assert BASE_BEFORE_PREMIUM_CENTS <= budget < PRICED_SHIFT_CENTS, (
        "the budget must sit between the pre-premium base and the priced shift for "
        "this test to isolate the premium"
    )
    plan = _submitted_peak_plan(world, center["id"], budget)

    response = api.approve_shift_plan(
        plan["id"],
        f.approve_payload(world.center_version(center["id"])),
        OPS_MANAGER_HEADERS,
    )
    validate_error(response, ERR_LABOR_BUDGET_EXCEEDED)

    unchanged = world.plan(plan["id"])
    assert unchanged["status"] == "SUBMITTED", (
        f"the refused approve leaves the plan submitted, got {unchanged['status']}"
    )
    assert unchanged["flex_draw_count"] == 0, (
        f"no flex is reserved by a refused approve, got {unchanged['flex_draw_count']}"
    )
    assert unchanged["planned_labor_cents"] == 0, (
        f"no cost field is written by a refused approve, got {unchanged['planned_labor_cents']}"
    )

    reread = world.center(center["id"])
    assert reread["flex_pool_available"] == FLEX_POOL_TOTAL, (
        f"the bench is untouched, got {reread['flex_pool_available']}"
    )
    assert reread["flex_pool_reserved"] == 0, (
        f"nothing is reserved, got {reread['flex_pool_reserved']}"
    )


def test_required_headcount_applies_the_posture_multiplier_before_the_single_ceiling(
    world,
):
    """PRD §3.4: "The order in step 4 through step 6 is contractual and not merely suggestive: the posture multiplier is applied to the exact quotient and the ceiling is taken exactly once, afterwards."

    Design: Difficulty/combinatorial_formula/required_headcount_tier_times_posture_multiplier
    """
    center = _restricted_manual_center(world)

    assert center["ops_posture"] == "RESTRICTED", (
        "an automation utilization of 40 is below 45, so the center is born "
        f"RESTRICTED, got {center['ops_posture']}"
    )
    assert center["open_jam_count"] == 0, f"no jam is held, got {center['open_jam_count']}"
    assert center["open_serious_injury_count"] == 0, (
        f"no serious injury is open, got {center['open_serious_injury_count']}"
    )

    plan = world.create_submitted_plan(
        center["id"],
        shift_date=PEAK_SHIFT_DATE,
        shift_window_start=PEAK_SHIFT_START,
        shift_window_end=PEAK_SHIFT_END,
        forecast_volume=PEAK_FORECAST_VOLUME,
        planned_core_headcount=20,
        planned_seasonal_headcount=0,
        labor_budget_cents=500000,
    )

    assert plan["status"] == "SUBMITTED", (
        f"submission advances the plan out of DRAFT, got {plan['status']}"
    )
    assert plan["submitted_by_user_id"] == LABOR_PLANNER_USER_ID, (
        "the submitting operator identifier is retained on the plan, got "
        f"{plan['submitted_by_user_id']}"
    )
    assert float(plan["shift_hours"]) == pytest.approx(8.00, abs=1e-6), (
        f"the shift window is eight hours long, got {plan['shift_hours']}"
    )

    expected = expected_required_headcount(
        PEAK_FORECAST_VOLUME, 8.00, 40.00, "RESTRICTED", 2
    )
    assert expected == 19, (
        "96,000 over 700 packages per associate-hour and 8.00 hours is 17.142857, "
        f"times 1.10 is 18.857143, ceiled once to 19, got {expected}"
    )
    assert plan["required_headcount"] == 19, (
        f"expected required_headcount 19, got {plan['required_headcount']}"
    )
    assert plan["required_headcount"] != 20, (
        "20 is what ceiling the quotient before applying the posture multiplier "
        "would produce"
    )


def test_required_headcount_falls_back_to_the_per_line_floor_on_a_light_forecast(world):
    """PRD §3.4: "Only now is the result rounded **up** to the next whole associate, and `required_headcount` is the larger of that ceiling and the per-line floor of 4 associates per line (4 multiplied by the line count)."

    Design: Difficulty/combinatorial_formula/required_headcount_tier_times_posture_multiplier
    """
    center = _restricted_manual_center(world)

    plan = world.create_submitted_plan(
        center["id"],
        shift_date=PEAK_SHIFT_DATE,
        shift_window_start=PEAK_SHIFT_START,
        shift_window_end=PEAK_SHIFT_END,
        forecast_volume=1000,
        planned_core_headcount=0,
        planned_seasonal_headcount=0,
        labor_budget_cents=500000,
    )

    expected = expected_required_headcount(1000, 8.00, 40.00, "RESTRICTED", 2)
    assert expected == 8, (
        "1,000 over 700 packages per associate-hour and 8.00 hours times 1.10 ceils "
        f"to a single associate, so the floor of 4 per line across two lines wins, got {expected}"
    )
    assert plan["required_headcount"] == 8, (
        "the per-line floor of 4 associates across two commissioned lines governs, "
        f"got {plan['required_headcount']}"
    )
    assert plan["required_headcount"] != 1, (
        "1 is the bare ceiling of the multiplied quotient, before the floor competes"
    )
    assert float(plan["shift_hours"]) == pytest.approx(8.00, abs=1e-6), (
        f"the shift window is eight hours long, got {plan['shift_hours']}"
    )
