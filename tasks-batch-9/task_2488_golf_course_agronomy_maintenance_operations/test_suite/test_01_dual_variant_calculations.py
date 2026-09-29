"""The two quantities this contract publishes twice from one row: the turf area's
applied-actual nitrogen against its planned-commitment nitrogen, and the fleet unit's
as-of-now replacement score against its fiscal-year projection."""

from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_3dp,
    assert_nitrogen_ledgers,
    assert_replacement_scores,
)
from test_helpers.fixtures import (
    build_application_environment,
    build_fleet_environment,
    create_plan,
    create_plan_task,
    get_equipment_unit,
    get_plan,
    get_turf_area,
    log_equipment_hours,
    record_application,
    set_clock,
)
from test_helpers.types import EquipmentStatus

APPLIED_AT = "2026-08-01T06:00:00Z"


def _green_with_a_planned_fertility_task():
    """A 5500 sq ft green carrying one 0.85 lb/1000 fertility task, plus the licence
    and label needed to spray it at 200 lb/acre."""
    set_clock(APPLIED_AT)
    env = build_application_environment()
    plan = create_plan(env.course["id"], nitrogen_budget_lb=40.00)
    task = create_plan_task(
        plan["id"], env.green7["id"], nitrogen_lb_per_1000=0.85
    )
    env.plan = plan
    env.task = task
    return env


# --------------------------------------------------------------------------
# The turf area's two nitrogen figures
# --------------------------------------------------------------------------
def test_turf_area_publishes_applied_actual_beside_planned_commitment():
    """One green, one 0.85 lb/1000 planned task and one 200 lb/acre spray: the applied
    figure reads 2.113 while the planned figure reads 2.963.

    "**The planned-commitment figure**, persisted as `nitrogen_projected_lb_per_1000`,
    starts from the applied-actual figure and adds the raw `nitrogen_lb_per_1000` rates
    of the area's fertility tasks whose status is `PLANNED` or `SCHEDULED`, rounding the
    total half up to three decimal places."

    Design: Difficulty/dual_variant_calc/turf_nitrogen_applied_actual_vs_planned_commitment
    """
    env = _green_with_a_planned_fertility_task()

    assert_2dp(env.task["commitment_lb"], 4.68)

    record = record_application(
        env.green7["id"],
        env.product["id"],
        env.applicator["id"],
        APPLIED_AT,
        rate_lb_per_acre=200,
    )
    assert_2dp(record["total_lb"], 25.25)
    assert_2dp(record["nitrogen_lb"], 11.62)

    area = get_turf_area(env.green7["id"])
    assert_nitrogen_ledgers(area, 2.113, 2.963)
    assert area["nitrogen_projected_lb_per_1000"] > area[
        "nitrogen_applied_lb_per_1000_ytd"
    ], "an unexecuted fertility task must leave the planned figure strictly larger"


def test_the_planned_figure_carries_the_unexecuted_task_before_any_spray():
    """Before the spray the same green reads 0.000 applied and 0.850 planned, and the
    plan's own ledger still reads 0.00 because the task is only `PLANNED`.

    "The plan's `committed_nitrogen_lb` ledger is the sum of the `commitment_lb` values
    of the plan's tasks whose status is `SCHEDULED` or `COMPLETED`, with the whole sum
    then rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/turf_nitrogen_applied_actual_vs_planned_commitment
    """
    env = _green_with_a_planned_fertility_task()

    before = get_turf_area(env.green7["id"])
    assert_nitrogen_ledgers(before, 0.000, 0.850)
    assert_2dp(get_plan(env.plan["id"])["committed_nitrogen_lb"], 0.00)

    record_application(
        env.green7["id"],
        env.product["id"],
        env.applicator["id"],
        APPLIED_AT,
        rate_lb_per_acre=200,
    )

    after = get_turf_area(env.green7["id"])
    assert_nitrogen_ledgers(after, 2.113, 2.963)
    assert_3dp(
        round(
            after["nitrogen_projected_lb_per_1000"]
            - after["nitrogen_applied_lb_per_1000_ytd"],
            3,
        ),
        0.850,
    )
    assert_2dp(get_plan(env.plan["id"])["committed_nitrogen_lb"], 0.00)


# --------------------------------------------------------------------------
# The fleet unit's two replacement scores
# --------------------------------------------------------------------------
def test_intake_scores_diverge_between_the_meter_now_and_the_fiscal_projection():
    """A 2018 triplex entering the fleet at 4200 meter hours scores 59.5 as it stands
    and 63.5 on the projection, and is not flagged.

    "The **as-of-now variant**, persisted as `replacement_score`, uses the usage ratio
    computed as `engine_hours` divided by `expected_life_hours` — the meter reading
    standing right now — and ignores `avg_daily_hours` entirely."

    Design: Difficulty/dual_variant_calc/equipment_replacement_score_now_vs_fiscal_year_projection
    """
    env = build_fleet_environment(initial_engine_hours=4200)

    assert_1dp(env.unit["engine_hours"], 4200.0)
    assert_1dp(env.unit["hours_since_service"], 0.0)
    assert_replacement_scores(env.unit, 59.5, 63.5, False)
    assert env.unit["status"] == EquipmentStatus.IN_SERVICE.value

    assert_replacement_scores(get_equipment_unit(env.unit["id"]), 59.5, 63.5, False)


def test_logged_hours_push_the_projection_past_the_flag_threshold():
    """300 more hours take the same unit to 81.8 now and 85.7 projected, raise the flag,
    and down it for service in the same request.

    "`replacement_flag` is a boolean derived from the **projection only**: it is true
    when `replacement_score_projected` is at or above a flag threshold of 70, and false
    otherwise."

    Design: Difficulty/dual_variant_calc/equipment_replacement_score_now_vs_fiscal_year_projection
    """
    env = build_fleet_environment(initial_engine_hours=4200)

    logged = log_equipment_hours(env.unit["id"], 300)

    assert_1dp(logged["engine_hours"], 4500.0)
    assert_1dp(logged["hours_since_service"], 300.0)
    assert_1dp(logged["engine_hours_at_last_service"], 4200.0)
    assert_replacement_scores(logged, 81.8, 85.7, True)
    assert logged["status"] == EquipmentStatus.DOWN_FOR_SERVICE.value

    reread = get_equipment_unit(env.unit["id"])
    assert_replacement_scores(reread, 81.8, 85.7, True)
    assert reread["replacement_score"] < reread["replacement_score_projected"], (
        "the projection must stand above the as-of-now score while hours still accrue"
    )
