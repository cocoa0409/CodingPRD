"""Three writes whose consequences travel several entities deep: a frost declaration, an
application void, and a fleet retirement, each of which ends inside a nitrogen ledger."""

from test_helpers.assertions import (
    assert_2dp,
    assert_applicator,
    assert_application,
    assert_maintenance_window,
    assert_nitrogen_ledgers,
    assert_plan,
    assert_turf_area,
)
from test_helpers.factories import FERTILITY, MOWING
from test_helpers.fixtures import (
    build_approved_plan,
    build_two_task_plan_environment,
    complete_maintenance_window,
    create_applicator,
    create_course,
    create_equipment_unit,
    create_green,
    create_maintenance_window,
    create_product,
    declare_weather_event,
    get_applicator,
    get_course,
    get_equipment_unit,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_turf_area,
    record_application,
    retire_equipment_unit,
    schedule_plan_task,
    set_clock,
    start_maintenance_window,
    void_application,
)
from test_helpers.types import (
    AgronomicStatus,
    EquipmentStatus,
    LicenseStatus,
    PlanStatus,
    PlanTaskStatus,
    PlayPosture,
    PostingStatus,
    RecordStatus,
    UnitType,
    VoidReason,
    WeatherEventStatus,
    WeatherEventType,
    WindowStatus,
)


def _two_task_plan_an_hour_before_the_first_window():
    """Both tasks bound, the ledger at 7.91, and the clock an hour before window one."""
    env = build_two_task_plan_environment(
        nitrogen_budget_lb=8.00, schedule_first=True, schedule_second=True
    )
    set_clock("2026-08-12T04:00:00Z")
    return env


def _completed_task_on_a_closed_plan():
    """A urea application satisfies the plan's only task, the window completes, the plan
    closes, and the clock then advances so the suspension instant is pinned."""
    set_clock("2026-08-12T06:00:00Z")
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    plan_env = build_approved_plan(
        course["id"],
        tasks=({"turf_area_id": green7["id"], "nitrogen_lb_per_1000": 0.85},),
        nitrogen_budget_lb=8.00,
    )
    task = plan_env.tasks[0]
    window = create_maintenance_window(
        course["id"], green7["id"], FERTILITY,
        "2026-08-12T05:00:00Z", "2026-08-12T07:00:00Z",
    )
    schedule_plan_task(task["id"], window["id"], plan_env.plan["version"])

    dana = create_applicator()
    urea = create_product()
    record = record_application(
        green7["id"], urea["id"], dana["id"], "2026-08-12T06:00:00Z",
        rate_lb_per_acre=200, wind_speed_mph=5, distance_to_water_ft=40,
        plan_task_id=task["id"],
    )

    start_maintenance_window(window["id"])
    complete_maintenance_window(window["id"])
    set_clock("2026-08-12T08:00:00Z")
    return green7, plan_env.plan, task, dana, record


def _sprayer_window_and_a_mower_decoy():
    """One bound FERTILITY window depending on the course's only sprayer, plus an
    unbound MOWING window depending on a triplex that is not being retired."""
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    plan_env = build_approved_plan(
        course["id"],
        tasks=({"turf_area_id": green7["id"], "nitrogen_lb_per_1000": 0.85},),
        nitrogen_budget_lb=8.00,
    )
    task = plan_env.tasks[0]
    spray_window = create_maintenance_window(
        course["id"], green7["id"], FERTILITY,
        "2026-08-12T05:00:00Z", "2026-08-12T07:00:00Z",
        required_unit_type=UnitType.SPRAYER.value,
    )
    mow_window = create_maintenance_window(
        course["id"], green7["id"], MOWING,
        "2026-08-13T05:00:00Z", "2026-08-13T06:00:00Z",
        crew_size=2,
        required_unit_type=UnitType.TRIPLEX_GREENS_MOWER.value,
    )
    schedule_plan_task(task["id"], spray_window["id"], plan_env.plan["version"])

    sprayer = create_equipment_unit(
        course["id"],
        unit_type=UnitType.SPRAYER.value,
        model_year=2022,
        purchase_cost=62000,
        expected_life_hours=5000,
        service_interval_hours=200,
        avg_daily_hours=2.0,
        initial_engine_hours=1000,
    )
    triplex = create_equipment_unit(
        course["id"],
        unit_type=UnitType.TRIPLEX_GREENS_MOWER.value,
        model_year=2024,
        purchase_cost=41000,
        expected_life_hours=6000,
        service_interval_hours=250,
        avg_daily_hours=3.0,
        initial_engine_hours=300,
    )
    return green7, plan_env.plan, task, spray_window, mow_window, sprayer, triplex


# --------------------------------------------------------------------------
# Frost: event -> window -> task -> ledgers
# --------------------------------------------------------------------------
def test_frost_declaration_debits_the_plan_ledger_through_the_window_it_defers():
    """One declaration defers window one, reverts task one to `PLANNED` and takes the
    plan ledger from 7.91 down to 3.23.

    "A `FROST`, `LIGHTNING`, or `HEAVY_RAIN` declaration defers qualifying maintenance
    windows `SCHEDULED → DEFERRED` — or cancels those that have exhausted their two
    deferrals — reverting any plan task each carried and recomputing the affected plans'
    committed nitrogen and the affected turf areas' projected nitrogen loads."

    Design: Difficulty/transitive_cascade/frost_declaration_defers_window_reverts_task_and_debits_ledger
    """
    env = _two_task_plan_an_hour_before_the_first_window()

    before = get_plan(env.plan["id"])
    assert_2dp(before["committed_nitrogen_lb"], 7.91)
    assert before["status"] == PlanStatus.ACTIVE.value

    frost = declare_weather_event(
        env.course["id"],
        WeatherEventType.FROST.value,
        "2026-08-12T06:00:00Z",
        delay_minutes=45,
    )

    assert frost["status"] == WeatherEventStatus.ACTIVE.value
    assert frost["deferred_window_count"] == 1
    assert_maintenance_window(
        get_maintenance_window(env.window1["id"]),
        status=WindowStatus.DEFERRED.value,
        deferral_count=1,
        plan_task_id=env.task1["id"],
    )
    assert get_plan_task(env.task1["id"])["status"] == PlanTaskStatus.PLANNED.value

    after = get_plan(env.plan["id"])
    assert_2dp(after["committed_nitrogen_lb"], 3.23)
    assert after["status"] == PlanStatus.ACTIVE.value
    assert_nitrogen_ledgers(get_turf_area(env.green7["id"]), 0.000, 0.850)


def test_the_window_that_does_not_intersect_the_frost_is_left_alone():
    """The 2026-08-13 window sits outside the frost's interval, so it and its task keep
    their scheduled state and the course reports the 45 minute delay.

    "The weather trigger fires when a frost, lightning, or heavy-rain event is declared
    on the same course and the window's half-open interval intersects the event's
    half-open interval from `declared_at` to `expected_clear_at`."

    Design: Difficulty/transitive_cascade/frost_declaration_defers_window_reverts_task_and_debits_ledger
    """
    env = _two_task_plan_an_hour_before_the_first_window()

    frost = declare_weather_event(
        env.course["id"],
        WeatherEventType.FROST.value,
        "2026-08-12T06:00:00Z",
        delay_minutes=45,
    )
    assert frost["declared_at"].startswith("2026-08-12T04:00:00")

    course = get_course(env.course["id"])
    assert course["play_posture"] == PlayPosture.FROST_DELAY.value
    assert course["frost_delay_minutes"] == 45

    assert_maintenance_window(
        get_maintenance_window(env.window2["id"]),
        expected_version=2,
        status=WindowStatus.SCHEDULED.value,
        deferral_count=0,
    )
    assert get_plan_task(env.task2["id"])["status"] == PlanTaskStatus.SCHEDULED.value


# --------------------------------------------------------------------------
# The void: record -> area -> licence -> task -> plan
# --------------------------------------------------------------------------
def test_safety_violation_void_reopens_the_closed_plan_and_reschedules_its_task():
    """Voiding the application that closed the plan reverts the task to `SCHEDULED` and
    reopens the plan to `ACTIVE` with its ledger still at 4.68.

    "And when the voided record cited a `plan_task_id` whose task had already reached
    `COMPLETED`, that task reverts `COMPLETED → SCHEDULED`, its plan's
    `committed_nitrogen_lb` is recomputed, and a plan that had reached `CLOSED` reopens
    `CLOSED → ACTIVE`, with each of those resources' `version` incremented by 1 in turn."

    Design: Difficulty/transitive_cascade/application_void_reverts_task_and_reopens_closed_plan
    """
    green7, plan, task, _dana, record = _completed_task_on_a_closed_plan()

    assert get_plan_task(task["id"])["status"] == PlanTaskStatus.COMPLETED.value
    closed = get_plan(plan["id"])
    assert closed["status"] == PlanStatus.CLOSED.value
    assert_2dp(closed["committed_nitrogen_lb"], 4.68)
    assert_nitrogen_ledgers(get_turf_area(green7["id"]), 2.113, 2.113)

    void_application(record["id"], VoidReason.SAFETY_VIOLATION.value)

    assert get_plan_task(task["id"])["status"] == PlanTaskStatus.SCHEDULED.value
    reopened = get_plan(plan["id"])
    assert_plan(
        reopened,
        status=PlanStatus.ACTIVE.value,
        committed_nitrogen_lb=4.68,
    )
    assert_nitrogen_ledgers(get_turf_area(green7["id"]), 0.000, 0.850)


def test_safety_violation_void_suspends_the_recording_applicator_at_the_clock():
    """The same void empties the applied ledger, clears the area's re-entry gate and
    stamps Dana's suspension at 2026-08-12T08:00:00Z.

    "When the reason is `SAFETY_VIOLATION`, the recording applicator's `license_status`
    becomes `SUSPENDED`, their `suspended_at` is stamped with the logical clock, and that
    applicator's `version` is incremented by 1; a `DATA_ENTRY_ERROR` void leaves the
    licence alone."

    Design: Difficulty/transitive_cascade/application_void_reverts_task_and_reopens_closed_plan
    """
    green7, _plan, _task, dana, record = _completed_task_on_a_closed_plan()

    voided = void_application(record["id"], VoidReason.SAFETY_VIOLATION.value)

    assert_application(
        voided,
        record_status=RecordStatus.VOIDED.value,
        void_reason=VoidReason.SAFETY_VIOLATION.value,
        posting_status=PostingStatus.NOT_REQUIRED.value,
    )
    assert_turf_area(
        get_turf_area(green7["id"]),
        nitrogen_applied_lb_per_1000_ytd=0.000,
        rei_expires_at=None,
    )
    assert_applicator(
        get_applicator(dana["id"]),
        license_status=LicenseStatus.SUSPENDED.value,
        suspended_at="2026-08-12T08:00:00Z",
    )


# --------------------------------------------------------------------------
# Retirement: unit -> window -> task -> plan ledger
# --------------------------------------------------------------------------
def test_retiring_the_only_sprayer_releases_the_plan_commitment_it_carried():
    """Retiring the course's only sprayer defers the window that needs one, reverts its
    task and empties the plan ledger to 0.00 without closing the plan.

    "Every maintenance window on that course in status `SCHEDULED` whose
    `required_unit_type` equals the retired unit's `unit_type`, and for which no other
    unit of that type on that course remains `IN_SERVICE`, moves `SCHEDULED → DEFERRED`
    under the rules of §3.6 — which itself reverts any plan task the window was carrying
    `SCHEDULED → PLANNED`, which itself recomputes that plan's `committed_nitrogen_lb`
    and the turf area's `nitrogen_projected_lb_per_1000`."

    Design: Difficulty/transitive_cascade/equipment_retirement_defers_dependent_window_and_releases_commitment
    """
    green7, plan, task, spray_window, _mow_window, sprayer, _triplex = (
        _sprayer_window_and_a_mower_decoy()
    )

    assert_2dp(get_plan(plan["id"])["committed_nitrogen_lb"], 4.68)
    assert get_plan_task(task["id"])["status"] == PlanTaskStatus.SCHEDULED.value

    retired = retire_equipment_unit(sprayer["id"])
    assert retired["status"] == EquipmentStatus.RETIRED.value
    assert retired["replaced_by_unit_id"] is None

    assert_maintenance_window(
        get_maintenance_window(spray_window["id"]),
        status=WindowStatus.DEFERRED.value,
        deferral_count=1,
        plan_task_id=task["id"],
    )
    assert get_plan_task(task["id"])["status"] == PlanTaskStatus.PLANNED.value
    reread_plan = get_plan(plan["id"])
    assert_2dp(reread_plan["committed_nitrogen_lb"], 0.00)
    assert reread_plan["status"] == PlanStatus.ACTIVE.value
    assert_nitrogen_ledgers(get_turf_area(green7["id"]), 0.000, 0.850)


def test_the_mowing_window_survives_because_its_machine_class_still_has_a_unit():
    """The triplex-dependent window is untouched by the sprayer's retirement, and the
    green's projected load never moves across the whole cascade.

    "The equipment trigger fires when a unit is retired whose `unit_type` equals the
    window's `required_unit_type` and no other unit of that type on that course remains
    `IN_SERVICE`."

    Design: Difficulty/transitive_cascade/equipment_retirement_defers_dependent_window_and_releases_commitment
    """
    green7, _plan, _task, _spray_window, mow_window, sprayer, triplex = (
        _sprayer_window_and_a_mower_decoy()
    )

    assert_nitrogen_ledgers(get_turf_area(green7["id"]), 0.000, 0.850)

    retire_equipment_unit(sprayer["id"])

    assert_maintenance_window(
        get_maintenance_window(mow_window["id"]),
        expected_version=1,
        status=WindowStatus.SCHEDULED.value,
        deferral_count=0,
    )
    assert get_equipment_unit(triplex["id"])["status"] == EquipmentStatus.IN_SERVICE.value
    assert_nitrogen_ledgers(get_turf_area(green7["id"]), 0.000, 0.850)
    assert (
        get_turf_area(green7["id"])["agronomic_status"] == AgronomicStatus.ACTIVE.value
    )
