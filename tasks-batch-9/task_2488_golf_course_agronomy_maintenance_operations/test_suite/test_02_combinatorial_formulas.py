"""Three formulas whose answer depends on the order the contract pins: the plan ledger's
per-task rounding, the overage tier keyed on the base charge, and the nested minimum that
picks an irrigation run's binding constraint."""

from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_water_assessment,
)
from test_helpers.fixtures import (
    build_two_task_plan_environment,
    complete_irrigation_run,
    create_course,
    create_irrigation_run,
    create_pump_station,
    create_turf_area,
    get_course,
    get_irrigation_run,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_water_assessment,
    schedule_plan_task,
)
from test_helpers.types import (
    AreaType,
    IrrigationRunStatus,
    SoilType,
    SourceType,
    WaterPosture,
)


def _reclaimed_station_over_a_seven_thousand_gallon_allocation():
    """A 7000 gal allocation, a 130000 sq ft fairway and a RECLAIMED station capped at
    7600 gal, so the daily headroom binds and the annual check never runs."""
    course = create_course(
        annual_water_allocation_gal=7000,
        water_restricted_threshold_pct=80,
        water_suspended_threshold_pct=100,
    )
    fairway = create_turf_area(
        course["id"],
        area_type=AreaType.FAIRWAY.value,
        hole_number=7,
        area_sq_ft=130000,
        mowing_height_mm=12.7,
        distance_to_water_ft=15,
        soil_type=SoilType.NATIVE_LOAM.value,
    )
    station = create_pump_station(
        course["id"],
        source_type=SourceType.RECLAIMED.value,
        max_flow_gpm=200,
        max_concurrent_zones=3,
        daily_withdrawal_cap_gal=7600,
    )
    run = create_irrigation_run(
        station["id"],
        fairway["id"],
        "2026-08-05T04:00:00Z",
        "2026-08-05T05:00:00Z",
        10,
        expected_pump_station_version=station["version"],
    )
    return course, fairway, station, run


def _well_station_capped_at_four_thousand_gallons():
    """A green and a fairway on one 4000 gal WELL station, with two non-overlapping
    windows so neither zone nor flow capacity can bind."""
    course = create_course(annual_water_allocation_gal=100000)
    green7 = create_turf_area(
        course["id"],
        area_type=AreaType.GREEN.value,
        hole_number=7,
        area_sq_ft=5500,
        mowing_height_mm=3.2,
        distance_to_water_ft=40,
        soil_type=SoilType.SAND_USGA.value,
    )
    fairway7 = create_turf_area(
        course["id"],
        area_type=AreaType.FAIRWAY.value,
        hole_number=7,
        area_sq_ft=130000,
        mowing_height_mm=12.7,
        distance_to_water_ft=15,
        soil_type=SoilType.NATIVE_LOAM.value,
    )
    station = create_pump_station(
        course["id"],
        source_type=SourceType.WELL.value,
        max_flow_gpm=300,
        max_concurrent_zones=2,
        daily_withdrawal_cap_gal=4000,
    )
    return course, green7, fairway7, station


# --------------------------------------------------------------------------
# The plan ledger: round each task, then add
# --------------------------------------------------------------------------
def test_plan_ledger_adds_already_rounded_commitments_to_seven_ninety_one():
    """0.85 on 5500 sq ft and 0.75 on 4300 sq ft commit 4.68 and 3.23, and the plan totals
    7.91 rather than the 7.90 a sum-then-round order would print.

    "**The rounding order is pinned: each task's commitment is rounded first, at task
    creation, and the plan ledger adds the already-rounded per-task values.**"

    Design: Difficulty/combinatorial_formula/plan_ledger_rounds_per_task_then_sums_mode_b
    """
    env = build_two_task_plan_environment(
        nitrogen_budget_lb=8.00, schedule_first=True, schedule_second=True
    )

    assert_2dp(get_plan_task(env.task1["id"])["commitment_lb"], 4.68)
    assert_2dp(get_plan_task(env.task2["id"])["commitment_lb"], 3.23)

    plan = get_plan(env.plan["id"])
    assert_2dp(plan["committed_nitrogen_lb"], 7.91)
    assert plan["committed_nitrogen_lb"] != 7.90, (
        "summing the exact products first would print 7.90, which is non-conforming"
    )


def test_plan_ledger_shows_the_first_commitment_alone_before_the_second_binding():
    """After only the first task is bound the ledger reads 4.68, and the window it was
    bound to now names it.

    "The plan's `committed_nitrogen_lb` ledger is the sum of the `commitment_lb` values
    of the plan's tasks whose status is `SCHEDULED` or `COMPLETED`, with the whole sum
    then rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/plan_ledger_rounds_per_task_then_sums_mode_b
    """
    env = build_two_task_plan_environment(nitrogen_budget_lb=8.00, schedule_first=True)

    plan_after_first = get_plan(env.plan["id"])
    assert_2dp(plan_after_first["committed_nitrogen_lb"], 4.68)
    assert get_maintenance_window(env.window1["id"])["plan_task_id"] == env.task1["id"]

    schedule_plan_task(
        env.task2["id"], env.window2["id"], plan_after_first["version"]
    )
    assert_2dp(get_plan(env.plan["id"])["committed_nitrogen_lb"], 7.91)


# --------------------------------------------------------------------------
# The overage assessment: the tier comes from the base charge
# --------------------------------------------------------------------------
def test_overage_assessment_keys_its_tier_on_the_base_charge():
    """7600.0 gallons against a 7000 gallon allocation assess as T1 at 25.24, not as the
    T2 total of 25.54.

    "Third, the `tier` is selected **from `base_charge`, never from the final total**: a
    base charge below 25.00 is tier `T1`, a base charge below 100.00 but not below 25.00
    is tier `T2`, and a base charge of 100.00 or more is tier `T3`."

    Design: Difficulty/combinatorial_formula/water_overage_tier_keyed_on_base_charge_mode_c
    """
    course, _fairway, _station, run = (
        _reclaimed_station_over_a_seven_thousand_gallon_allocation()
    )

    complete_irrigation_run(run["id"])

    assessment = get_water_assessment(course["id"])
    assert_water_assessment(assessment, 600.0, 24.70, "T1", 0.90, 0.54, 25.24)
    assert assessment["total_charge"] != 25.54, (
        "keying the tier on the total would print 25.54, which is non-conforming"
    )


def test_completed_run_posts_seventy_six_hundred_gallons_and_suspends_the_posture():
    """The headroom-bound run withdraws 7600.0 gallons, which is 108.571 percent of the
    allocation, so the course's water posture reads `SUSPENDED`.

    "If it is greater than or equal to `water_suspended_threshold_pct` the posture is
    `SUSPENDED`."

    Design: Difficulty/combinatorial_formula/water_overage_tier_keyed_on_base_charge_mode_c
    """
    course, _fairway, _station, run = (
        _reclaimed_station_over_a_seven_thousand_gallon_allocation()
    )

    assert_1dp(run["allotted_gal"], 7600.0)
    assert_2dp(run["flow_gpm"], 126.67)
    assert_1dp(run["volume_gal"], 0)

    completed = complete_irrigation_run(run["id"])
    assert_1dp(completed["volume_gal"], 7600.0)

    reread = get_course(course["id"])
    assert_1dp(reread["water_used_gal"], 7600.0)
    assert reread["water_posture"] == WaterPosture.SUSPENDED.value


# --------------------------------------------------------------------------
# The allotment's nested minimum
# --------------------------------------------------------------------------
def test_green_run_is_demand_bound_while_the_fairway_run_is_headroom_bound():
    """On one 4000 gal station the green's run allots 272.8 gal from demand and the
    fairway's run allots 4000.0 gal from headroom.

    "The run's `allotted_gal` is the **smaller** of the posture-scaled demand and the
    remaining daily headroom, rounded half up to one decimal place."

    Design: Difficulty/combinatorial_formula/irrigation_allotment_nested_min_switches_binding_constraint_mode_a
    """
    _course, green7, fairway7, station = _well_station_capped_at_four_thousand_gallons()

    run_a = create_irrigation_run(
        station["id"],
        green7["id"],
        "2026-08-05T04:00:00Z",
        "2026-08-05T04:40:00Z",
        8,
        expected_pump_station_version=station["version"],
    )
    run_b = create_irrigation_run(
        station["id"],
        fairway7["id"],
        "2026-08-05T05:00:00Z",
        "2026-08-05T06:00:00Z",
        10,
        expected_pump_station_version=station["version"],
    )

    assert_1dp(run_a["allotted_gal"], 272.8)
    assert_1dp(run_b["allotted_gal"], 4000.0)


def test_both_runs_publish_their_own_flow_and_start_empty():
    """The 40-minute green run flows at 6.82 gpm and the 60-minute fairway run at 66.67
    gpm, and both are created scheduled with nothing withdrawn.

    "Its `flow_gpm` is `allotted_gal` divided by the window duration in minutes, rounded
    half up to two decimal places."

    Design: Difficulty/combinatorial_formula/irrigation_allotment_nested_min_switches_binding_constraint_mode_a
    """
    _course, green7, fairway7, station = _well_station_capped_at_four_thousand_gallons()

    run_a = create_irrigation_run(
        station["id"],
        green7["id"],
        "2026-08-05T04:00:00Z",
        "2026-08-05T04:40:00Z",
        8,
        expected_pump_station_version=station["version"],
    )
    run_b = create_irrigation_run(
        station["id"],
        fairway7["id"],
        "2026-08-05T05:00:00Z",
        "2026-08-05T06:00:00Z",
        10,
        expected_pump_station_version=station["version"],
    )

    assert_2dp(run_a["flow_gpm"], 6.82)
    assert_2dp(run_b["flow_gpm"], 66.67)

    for run in (run_a, run_b):
        reread = get_irrigation_run(run["id"])
        assert reread["status"] == IrrigationRunStatus.SCHEDULED.value
        assert_1dp(reread["volume_gal"], 0)
