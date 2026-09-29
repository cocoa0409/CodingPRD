"""The layers that cut across every aggregate: the four pinned-version guards, the mechanical
one-increment-per-write rule, and a cumulative threshold that fires, resets, and fires again."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_EQUIPMENT_STATE_INVALID,
    ERR_STALE_COURSE_VERSION,
    ERR_STALE_PLAN_VERSION,
    ERR_STALE_PUMP_VERSION,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_3dp,
    assert_course,
    assert_equipment_unit,
    assert_instant,
    assert_irrigation_run,
    assert_maintenance_window,
    assert_plan,
    assert_plan_task,
    assert_pump_station,
    assert_replacement_scores,
    assert_total_count,
    assert_weather_event,
)
from test_helpers.factories import (
    AERATION,
    FERTILITY,
    approve_plan_payload,
    irrigation_run_payload,
    schedule_task_payload,
    service_payload,
    weather_event_payload,
)
from test_helpers.fixtures import (
    approve_plan,
    create_course,
    create_equipment_unit,
    create_green,
    create_irrigation_run,
    create_maintenance_window,
    create_plan,
    create_plan_task,
    create_pump_station,
    create_turf_area,
    declare_weather_event,
    get_course,
    get_equipment_unit,
    get_irrigation_run,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_pump_station,
    get_turf_area,
    list_course_weather_events,
    list_irrigation_runs,
    log_equipment_hours,
    return_plan,
    revise_water_allocation,
    schedule_plan_task,
    service_equipment_unit,
    set_clock,
    set_pump_station_status,
    submit_plan,
)
from test_helpers.test_users import AGRO_HEADERS, SUPER_HEADERS, TECH_HEADERS
from test_helpers.types import (
    AreaType,
    EquipmentStatus,
    IrrigationRunStatus,
    PlanStatus,
    PlanTaskStatus,
    PlayPosture,
    PumpStationStatus,
    SoilType,
    SourceType,
    UnitType,
    WaterPosture,
    WeatherEventStatus,
    WeatherEventType,
)


def _active_plan_with_two_tasks_each_holding_its_own_window():
    """A 40.00 lb plan carrying a 4.68 lb fertility task on a green and a zero-cost aeration
    task on a fairway, with one two-hour window waiting on each area."""
    course = create_course(annual_water_allocation_gal=500000)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=5500,
                           distance_to_water_ft=60, headers=AGRO_HEADERS)
    fw5 = create_turf_area(
        course["id"], area_type=AreaType.FAIRWAY.value, hole_number=5,
        area_sq_ft=130000, mowing_height_mm=11.0, distance_to_water_ft=90,
        soil_type=SoilType.NATIVE_LOAM.value, headers=AGRO_HEADERS,
    )
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=40.0)
    task_fert = create_plan_task(
        plan["id"], green12["id"], task_type=FERTILITY, nitrogen_lb_per_1000=0.85,
        planned_window_start="2026-08-01T00:00:00Z",
        planned_window_end="2026-08-31T00:00:00Z",
    )
    task_aer = create_plan_task(
        plan["id"], fw5["id"], task_type=AERATION,
        planned_window_start="2026-08-01T00:00:00Z",
        planned_window_end="2026-08-31T00:00:00Z",
    )
    w_fert = create_maintenance_window(
        course["id"], green12["id"], FERTILITY,
        "2026-08-10T06:00:00Z", "2026-08-10T08:00:00Z", crew_size=3,
    )
    w_aer = create_maintenance_window(
        course["id"], fw5["id"], AERATION,
        "2026-08-10T06:00:00Z", "2026-08-10T08:00:00Z", crew_size=4,
    )
    submitted = submit_plan(plan["id"])
    active = approve_plan(plan["id"], submitted["version"])
    return green12, plan, active, task_fert, task_aer, w_fert, w_aer


def _plan_submitted_returned_and_submitted_again():
    """One fertility task, one round trip through the review cycle, and therefore two
    different submission tokens in the approver's hands."""
    course = create_course(annual_water_allocation_gal=500000)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=5500,
                           distance_to_water_ft=60, headers=AGRO_HEADERS)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=40.0)
    task_fert = create_plan_task(
        plan["id"], green12["id"], task_type=FERTILITY, nitrogen_lb_per_1000=0.85,
        planned_window_start="2026-08-01T00:00:00Z",
        planned_window_end="2026-08-31T00:00:00Z",
    )
    first = submit_plan(plan["id"])
    return_plan(plan["id"], return_note="Split the August fertility into two applications.")
    second = submit_plan(plan["id"])
    return plan, task_fert, first, second


def _well_station_cycled_offline_and_back_online():
    """A station whose version the client read at registration and which has since been taken
    down for repair and put back, twice bumping the token the client is holding."""
    course = create_course(annual_water_allocation_gal=500000)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=5500,
                           distance_to_water_ft=60, headers=AGRO_HEADERS)
    station = create_pump_station(
        course["id"], source_type=SourceType.WELL.value, max_flow_gpm=300,
        max_concurrent_zones=4, daily_withdrawal_cap_gal=50000,
    )
    set_pump_station_status(
        station["id"], PumpStationStatus.OFFLINE.value, headers=TECH_HEADERS
    )
    set_pump_station_status(
        station["id"], PumpStationStatus.ONLINE.value, headers=TECH_HEADERS
    )
    return green12, station


def _two_identical_triplexes_with_a_two_hundred_fifty_hour_interval():
    """Two current-model-year triplex mowers with no hours on either meter, a 6000 hour design
    life and a 250 hour service interval, on the day 152 whole days remain in the year."""
    set_clock("2026-08-01T00:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    spec = dict(
        unit_type=UnitType.TRIPLEX_GREENS_MOWER.value, model_year=2026,
        purchase_cost=48000, expected_life_hours=6000,
        service_interval_hours=250, avg_daily_hours=3.5,
    )
    unit_a = create_equipment_unit(course["id"], **spec)
    unit_b = create_equipment_unit(course["id"], **spec)
    return unit_a, unit_b


# --------------------------------------------------------------------------
# The pinned plan version, on both operations that require it
# --------------------------------------------------------------------------
def test_a_plan_version_spent_on_one_task_no_longer_binds_the_other():
    """The aeration binding consumes version 3, so the fertility binding presented with the
    same token is refused 412 `ERR_STALE_PLAN_VERSION` and writes none of its four mutations;
    refetching version 4 lets the identical request through and posts 4.68 to the ledger.

    "Scheduling a plan task (`POST /plan-tasks/{id}/schedule`) requires
    `expected_plan_version`, carrying the client's last observed `version` of the
    `AgronomicPlan` that owns the task. A mismatch is rejected with `ERR_STALE_PLAN_VERSION`
    (HTTP 412)."

    "To make the difference concrete: a task planning 0.85 pounds per thousand on 5500 square
    feet gives an exact product of 4.675, which rounds to 4.68"

    "A successful binding produces four mutations. The task moves to `SCHEDULED` and its
    `version` increments by 1. The window records the task's identifier in its own
    `plan_task_id` and its `version` increments by 1. The plan's `committed_nitrogen_lb` is
    recomputed and its `version` increments by 1. The turf area's
    `nitrogen_projected_lb_per_1000` is recomputed by the planned-commitment rule and that
    area's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_blocks_task_scheduling
    """
    green12, plan, active, task_fert, task_aer, w_fert, w_aer = (
        _active_plan_with_two_tasks_each_holding_its_own_window()
    )

    assert_2dp(task_fert["commitment_lb"], 4.68)
    assert_2dp(task_aer["commitment_lb"], 0.00)
    assert_plan(active, expected_version=3, status=PlanStatus.ACTIVE.value)

    aerating = schedule_plan_task(task_aer["id"], w_aer["id"], active["version"])
    assert_plan_task(aerating, status=PlanTaskStatus.SCHEDULED.value)
    assert_plan(get_plan(plan["id"]), expected_version=4, committed_nitrogen_lb=0.00)

    refused = api_client.schedule_plan_task(
        task_fert["id"],
        schedule_task_payload(w_fert["id"], active["version"]),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_STALE_PLAN_VERSION, 412)

    assert_plan_task(
        get_plan_task(task_fert["id"]),
        expected_version=1,
        status=PlanTaskStatus.PLANNED.value,
    )
    assert_maintenance_window(
        get_maintenance_window(w_fert["id"]), expected_version=1, plan_task_id=None
    )
    assert_3dp(get_turf_area(green12["id"])["nitrogen_projected_lb_per_1000"], 0.850)

    fresh = get_plan(plan["id"])
    assert_plan(fresh, expected_version=4, committed_nitrogen_lb=0.00)

    retried = schedule_plan_task(task_fert["id"], w_fert["id"], fresh["version"])
    assert_plan_task(retried, status=PlanTaskStatus.SCHEDULED.value)
    assert_plan(
        get_plan(plan["id"]), expected_version=5, committed_nitrogen_lb=4.68
    )


def test_a_returned_and_resubmitted_plan_refuses_the_earlier_submission_token():
    """The plan is genuinely `SUBMITTED`, so the wrong-revision approval answers 412
    `ERR_STALE_PLAN_VERSION` rather than a state error, and approving on the second token
    activates a plan whose ledger is still empty.

    "Approving an agronomic plan (`POST /agronomic-plans/{id}/approve`) requires
    `expected_plan_version`, carrying the client's last observed `version` of that plan. A
    mismatch is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). A return that legitimately
    supersedes the submission, or a task addition that moved the committed ledger, both advance
    the plan's version, so a stale value means the approver is approving something other than
    what they read."

    "Approving it moves the plan `SUBMITTED → ACTIVE` and increments `version`; approval
    requires the pinned `expected_plan_version` to equal the plan's current `version`, failing
    which the request is refused with `ERR_STALE_PLAN_VERSION`, and it requires the approving
    caller's `X-User-ID` to differ from the `submitted_by_user_id` recorded at submission,
    failing which the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

    "The plan's `committed_nitrogen_lb` ledger is the sum of the `commitment_lb` values of the
    plan's tasks whose status is `SCHEDULED` or `COMPLETED`, with the whole sum then rounded
    half up to two decimal places."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_blocks_plan_approval
    """
    plan, task_fert, first, second = _plan_submitted_returned_and_submitted_again()

    assert_plan(first, expected_version=2, status=PlanStatus.SUBMITTED.value)
    assert_plan(second, expected_version=4, status=PlanStatus.SUBMITTED.value)

    refused = api_client.approve_plan(
        plan["id"], approve_plan_payload(first["version"]), SUPER_HEADERS
    )
    validate_error(refused, ERR_STALE_PLAN_VERSION, 412)

    assert_plan(
        get_plan(plan["id"]),
        expected_version=4,
        status=PlanStatus.SUBMITTED.value,
        return_count=1,
    )

    approved = approve_plan(plan["id"], second["version"])
    assert_plan(approved, expected_version=5, status=PlanStatus.ACTIVE.value)
    assert_plan_task(
        get_plan_task(task_fert["id"]), status=PlanTaskStatus.PLANNED.value
    )
    assert_2dp(get_plan(plan["id"])["committed_nitrogen_lb"], 0.00)


# --------------------------------------------------------------------------
# The pinned course version, and the pinned pump version
# --------------------------------------------------------------------------
def test_a_course_version_spent_on_the_allocation_revision_cannot_declare_weather():
    """The revision moves the course to version 2, so the frost declaration pinned at version
    1 answers 412 `ERR_STALE_COURSE_VERSION` and leaves the log empty and the posture `OPEN`;
    pinned at 2 it is accepted, stamped from the clock, and pushes the delay onto the course.

    "Declaring a weather event (`POST /weather-events`) requires `expected_course_version`,
    carrying the client's last observed `version` of the `Course` the event is declared on. A
    mismatch is rejected with `ERR_STALE_COURSE_VERSION` (HTTP 412)."

    "each of `annual_water_allocation_gal`, `water_restricted_threshold_pct` and
    `water_suspended_threshold_pct` is optional on that revision, and whatever is supplied
    replaces the stored value"

    "The course's `version` is incremented by 1 by the revision."

    "A declared event is created with status `ACTIVE`, a `declared_at` stamped from the logical
    clock, a `cleared_at` of null, and a `deferred_window_count` set to the number of
    maintenance windows the declaration actually deferred."

    "Otherwise, if any active event is a frost event, the posture is `FROST_DELAY` and
    `frost_delay_minutes` takes the delay of the **governing** frost event, which is the active
    frost event with the greatest `declared_at`, breaking a tie by the greatest `created_at`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_course_version_blocks_weather_declaration
    """
    set_clock("2026-08-01T05:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    assert_course(course, expected_version=1)

    revised = revise_water_allocation(
        course["id"], annual_water_allocation_gal=450000
    )
    assert_course(revised, expected_version=2)

    refused = api_client.create_weather_event(
        weather_event_payload(
            course["id"], WeatherEventType.FROST.value, "2026-08-01T07:30:00Z",
            expected_course_version=course["version"], delay_minutes=30,
        ),
        SUPER_HEADERS,
    )
    validate_error(refused, ERR_STALE_COURSE_VERSION, 412)

    _rows, meta = list_course_weather_events(course["id"])
    assert_total_count(meta, 0)
    before = get_course(course["id"])
    assert_course(
        before,
        expected_version=2,
        play_posture=PlayPosture.OPEN.value,
        frost_delay_minutes=0,
    )

    declared = declare_weather_event(
        course["id"], WeatherEventType.FROST.value, "2026-08-01T07:30:00Z",
        expected_course_version=before["version"], delay_minutes=30,
    )
    assert_weather_event(declared, status=WeatherEventStatus.ACTIVE.value)
    assert_instant(declared["declared_at"], "2026-08-01T05:00:00Z")

    assert_course(
        get_course(course["id"]),
        expected_version=3,
        play_posture=PlayPosture.FROST_DELAY.value,
        frost_delay_minutes=30,
    )


def test_a_pump_version_spent_on_a_repair_cycle_cannot_book_a_run():
    """Two status changes carry the station from version 1 to version 3, so the run pinned at
    version 1 answers 412 `ERR_STALE_PUMP_VERSION` and not the offline error the station has
    already left behind; pinned at 3 the run books 341.0 gallons at 5.68 gpm.

    "Creating an irrigation run (`POST /irrigation-runs`) requires
    `expected_pump_station_version`, carrying the client's last observed `version` of the
    `PumpStation` supplying the run. A mismatch is rejected with `ERR_STALE_PUMP_VERSION`
    (HTTP 412)."

    "Taking a station `OFFLINE` immediately transitions every run on that station in status
    `SCHEDULED` to `CANCELLED`, zeroing each cancelled run's withdrawn volume and incrementing
    each run's `version` by 1; the station's own `version` is incremented by 1 by the status
    change."

    "The run's `allotted_gal` is the **smaller** of the posture-scaled demand and the remaining
    daily headroom, rounded half up to one decimal place. Its `flow_gpm` is `allotted_gal`
    divided by the window duration in minutes, rounded half up to two decimal places."

    "A new run starts in `SCHEDULED` with `volume_gal` at 0 and `version` 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_pump_version_blocks_run_creation
    """
    green12, station = _well_station_cycled_offline_and_back_online()
    assert_pump_station(station, expected_version=1)

    refused = api_client.create_irrigation_run(
        irrigation_run_payload(
            station["id"], green12["id"],
            "2026-08-02T04:00:00Z", "2026-08-02T05:00:00Z", 10, station["version"],
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_STALE_PUMP_VERSION, 412)

    _rows, meta = list_irrigation_runs(pump_station_id=station["id"])
    assert_total_count(meta, 0)
    fresh = get_pump_station(station["id"])
    assert_pump_station(
        fresh, expected_version=3, status=PumpStationStatus.ONLINE.value
    )
    assert_1dp(fresh["withdrawn_today_gal"], 0.0)

    booked = create_irrigation_run(
        station["id"], green12["id"],
        "2026-08-02T04:00:00Z", "2026-08-02T05:00:00Z", 10,
        expected_pump_station_version=fresh["version"],
    )
    assert_irrigation_run(
        booked,
        expected_version=1,
        status=IrrigationRunStatus.SCHEDULED.value,
        allotted_gal=341.0,
        flow_gpm=5.68,
        volume_gal=0,
    )
    assert_1dp(get_irrigation_run(booked["id"])["allotted_gal"], 341.0)
    assert_pump_station(get_pump_station(station["id"]), expected_version=3)


# --------------------------------------------------------------------------
# One increment per write, and no increment for a read
# --------------------------------------------------------------------------
def test_each_revision_advances_the_version_by_exactly_one_and_the_read_by_none():
    """Two revisions that cannot move the posture — the course has used nothing — still carry
    the version 1 → 2 → 3, one step each, and the following read leaves it at 3 with each
    PATCH's own field standing where it was written.

    "`version` is an integer that starts at 1 when the resource is created and increases by
    exactly 1 on every mutation of that resource — including mutations the server performs on
    its own initiative, such as a ledger recomputation or an automatic status change cascaded
    from another entity."

    "The rule is mechanical: each resource that is actually mutated by the request has its own
    `version` incremented by 1 and its own `updated_at` refreshed, and a resource that a
    request merely reads is not touched."

    "The course's `version` is incremented by 1 by the revision."

    "If it is greater than or equal to `water_suspended_threshold_pct` the posture is
    `SUSPENDED`. Otherwise, if it is greater than or equal to `water_restricted_threshold_pct`
    the posture is `RESTRICTED`. Otherwise the posture is `OPEN`."

    Design: Corner/cross_cutting_complexity_layers/every_write_increments_the_entity_version
    """
    course = create_course(annual_water_allocation_gal=500000)
    assert_course(course, expected_version=1, water_posture=WaterPosture.OPEN.value)

    first = revise_water_allocation(
        course["id"], annual_water_allocation_gal=400000
    )
    assert_course(first, expected_version=2, water_posture=WaterPosture.OPEN.value)

    second = revise_water_allocation(course["id"], water_restricted_threshold_pct=75)
    assert_course(second, expected_version=3, water_posture=WaterPosture.OPEN.value)

    reread = get_course(course["id"])
    assert_course(
        reread,
        expected_version=3,
        annual_water_allocation_gal=400000,
        water_restricted_threshold_pct=75,
    )
    assert_1dp(reread["water_used_gal"], 0.0)


# --------------------------------------------------------------------------
# A cumulative threshold: inclusive, resettable, and re-armed
# --------------------------------------------------------------------------
def test_the_service_interval_fires_at_exactly_two_hundred_fifty_hours_and_rearms():
    """250 logged hours take one machine down and 249 leave its twin in service; the service
    zeroes the interval counter without touching the 250 hour meter, and the next 250 hours
    fire the same threshold again at 500 on the meter.

    "The entry raises `engine_hours` and therefore `hours_since_service`, recomputes both
    replacement scores and the replacement flag, and increments the unit's `version` by 1. **In
    the same request**, an automatic transition is then evaluated: a unit whose status is
    `IN_SERVICE` and whose `hours_since_service` has reached or passed its
    `service_interval_hours` moves `IN_SERVICE → DOWN_FOR_SERVICE`. The threshold is inclusive
    — hours exactly equal to the interval takes the unit down — and the auto-transition
    increments the unit's `version` again."

    "The service sets `engine_hours_at_last_service` to the current `engine_hours`, drives
    `hours_since_service` to 0, recomputes both replacement scores and the replacement flag,
    moves the unit `DOWN_FOR_SERVICE → IN_SERVICE`, and increments its `version` by 1."

    "The score is 100 multiplied by the sum of the capped usage ratio weighted at 0.45, the
    capped age ratio weighted at 0.35, and the capped overdue ratio weighted at 0.20, and the
    whole weighted sum is rounded half up to one decimal place once, at the end."

    "`replacement_flag` is a boolean derived from the **projection only**: it is true when
    `replacement_score_projected` is at or above a flag threshold of 70, and false otherwise."

    "The unit must be `DOWN_FOR_SERVICE`, else `ERR_EQUIPMENT_STATE_INVALID`."

    Design: Corner/cross_cutting_complexity_layers/cumulative_service_threshold_fires_at_exactly_the_interval_and_resets
    """
    unit_a, unit_b = _two_identical_triplexes_with_a_two_hundred_fifty_hour_interval()

    downed = log_equipment_hours(unit_a["id"], 250)
    assert_equipment_unit(
        downed,
        status=EquipmentStatus.DOWN_FOR_SERVICE.value,
        engine_hours=250.0,
        hours_since_service=250.0,
    )
    assert_replacement_scores(downed, 21.9, 25.9, False)

    still_running = log_equipment_hours(unit_b["id"], 249)
    assert_equipment_unit(
        still_running,
        status=EquipmentStatus.IN_SERVICE.value,
        engine_hours=249.0,
        hours_since_service=249.0,
    )
    assert_replacement_scores(still_running, 21.8, 25.8, False)

    serviced = service_equipment_unit(
        unit_a["id"], service_note="Reels backlapped, oil and filters."
    )
    assert_equipment_unit(
        serviced,
        status=EquipmentStatus.IN_SERVICE.value,
        engine_hours=250.0,
        hours_since_service=0.0,
        engine_hours_at_last_service=250.0,
    )
    assert_1dp(serviced["replacement_score"], 1.9)

    refired = log_equipment_hours(unit_a["id"], 250)
    assert_equipment_unit(
        refired,
        status=EquipmentStatus.DOWN_FOR_SERVICE.value,
        engine_hours=500.0,
        hours_since_service=250.0,
    )
    assert_replacement_scores(refired, 23.8, 27.7, False)

    refused = api_client.service_equipment_unit(
        unit_b["id"], TECH_HEADERS, service_payload("premature work order")
    )
    validate_error(refused, ERR_EQUIPMENT_STATE_INVALID, 409)

    assert_equipment_unit(
        get_equipment_unit(unit_b["id"]),
        status=EquipmentStatus.IN_SERVICE.value,
        engine_hours=249.0,
        hours_since_service=249.0,
    )
