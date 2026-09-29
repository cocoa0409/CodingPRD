"""One binding, four resources, and no settling period: every recomputed figure is already
final in the response that caused it and on the very first read of each neighbour."""

from test_helpers.assertions import (
    assert_2dp,
    assert_3dp,
    assert_maintenance_window,
    assert_plan,
    assert_plan_task,
    assert_turf_area,
    assert_untouched,
)
from test_helpers.factories import FERTILITY
from test_helpers.fixtures import (
    approve_plan,
    create_course,
    create_green,
    create_maintenance_window,
    create_plan,
    create_plan_task,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_turf_area,
    schedule_plan_task,
    set_clock,
    submit_plan,
)
from test_helpers.test_users import AGRO_HEADERS
from test_helpers.types import PlanTaskStatus


def _active_plan_one_fertility_task_and_the_window_it_belongs_in():
    """A 40.00 lb plan whose single 4.68 lb fertility task is still `PLANNED`, and one
    three-crew two-hour window on the same green waiting to receive it."""
    set_clock("2026-08-01T00:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=5500,
                           distance_to_water_ft=60, headers=AGRO_HEADERS)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=40.0)
    task = create_plan_task(
        plan["id"], green12["id"], task_type=FERTILITY, nitrogen_lb_per_1000=0.85,
        planned_window_start="2026-08-01T00:00:00Z",
        planned_window_end="2026-08-31T00:00:00Z",
    )
    window = create_maintenance_window(
        course["id"], green12["id"], FERTILITY,
        "2026-08-10T06:00:00Z", "2026-08-10T08:00:00Z", crew_size=3,
    )
    submitted = submit_plan(plan["id"])
    active = approve_plan(plan["id"], submitted["version"])
    return green12, plan, active, task, window


def test_every_field_the_binding_recomputes_is_final_on_its_first_read():
    """The schedule response already reads `SCHEDULED` at version 2 with a 4.68 lb commitment,
    and the first read of the plan, the green and the window each show their recomputed figure
    and their incremented version — with a second read of each moving nothing.

    "A successful binding produces four mutations. The task moves to `SCHEDULED` and its
    `version` increments by 1. The window records the task's identifier in its own
    `plan_task_id` and its `version` increments by 1. The plan's `committed_nitrogen_lb` is
    recomputed and its `version` increments by 1. The turf area's
    `nitrogen_projected_lb_per_1000` is recomputed by the planned-commitment rule and that
    area's `version` increments by 1."

    "The rule is mechanical: each resource that is actually mutated by the request has its own
    `version` incremented by 1 and its own `updated_at` refreshed, and a resource that a
    request merely reads is not touched. A resource whose version was bumped only because a
    derived field was recomputed still counts as mutated."

    "To make the difference concrete: a task planning 0.85 pounds per thousand on 5500 square
    feet gives an exact product of 4.675, which rounds to 4.68"

    "**The planned-commitment figure**, persisted as `nitrogen_projected_lb_per_1000`, starts
    from the applied-actual figure and adds the raw `nitrogen_lb_per_1000` rates of the area's
    fertility tasks whose status is `PLANNED` or `SCHEDULED`, rounding the total half up to
    three decimal places."

    "Its `crew_hours` figure is derived: the `crew_size` multiplied by the window duration
    expressed in hours, rounded half up to two decimal places."

    Design: Corner/consistency_model/immediate_visibility_of_every_recomputed_field_in_the_same_request
    """
    green12, plan, active, task, window = (
        _active_plan_one_fertility_task_and_the_window_it_belongs_in()
    )

    bound = schedule_plan_task(task["id"], window["id"], active["version"])
    assert_plan_task(
        bound, expected_version=2, status=PlanTaskStatus.SCHEDULED.value
    )
    assert_2dp(bound["commitment_lb"], 4.68)

    plan_first = get_plan(plan["id"])
    assert_plan(plan_first, expected_version=4)
    assert_2dp(plan_first["committed_nitrogen_lb"], 4.68)

    green_first = get_turf_area(green12["id"])
    assert_turf_area(green_first, expected_version=3)
    assert_3dp(green_first["nitrogen_projected_lb_per_1000"], 0.850)
    assert_3dp(green_first["nitrogen_applied_lb_per_1000_ytd"], 0.000)

    window_first = get_maintenance_window(window["id"])
    assert_maintenance_window(
        window_first, expected_version=2, plan_task_id=task["id"]
    )
    assert_2dp(window_first["crew_hours"], 6.00)

    assert_untouched(bound, get_plan_task(task["id"]))
    assert_untouched(plan_first, get_plan(plan["id"]))
    assert_untouched(green_first, get_turf_area(green12["id"]))
    assert_untouched(window_first, get_maintenance_window(window["id"]))

    assert_2dp(get_plan(plan["id"])["committed_nitrogen_lb"], 4.68)
    assert_3dp(
        get_turf_area(green12["id"])["nitrogen_projected_lb_per_1000"], 0.850
    )
    assert_2dp(get_maintenance_window(window["id"])["crew_hours"], 6.00)
