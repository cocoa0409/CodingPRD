"""Five guards read at their exact edges: the inclusive wind and buffer limits, the first
value above the wind ceiling, the out-of-play gate on a measurement, the reclaimed-source
exemption from the annual allocation, and the containment test on a task's planned window."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_APPLICATION_OUTSIDE_PLAN_WINDOW,
    ERR_TURF_AREA_OUT_OF_PLAY,
    ERR_WATER_ALLOCATION_EXCEEDED,
    ERR_WIND_LIMIT_EXCEEDED,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_application,
    assert_instant,
    assert_irrigation_run,
    assert_maintenance_window,
    assert_nitrogen_ledgers,
    assert_plan,
    assert_plan_task,
    assert_playability_reading,
    assert_total_count,
    assert_turf_area,
)
from test_helpers.factories import (
    AERATION,
    application_payload,
    irrigation_run_payload,
    playability_reading_payload,
    schedule_task_payload,
)
from test_helpers.fixtures import (
    approve_plan,
    clear_weather_event,
    create_applicator,
    create_course,
    create_green,
    create_irrigation_run,
    create_maintenance_window,
    create_plan,
    create_plan_task,
    create_playability_reading,
    create_product,
    create_pump_station,
    declare_weather_event,
    get_course,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_turf_area,
    list_applications,
    list_irrigation_runs,
    list_playability_readings,
    record_application,
    schedule_plan_task,
    set_clock,
    submit_plan,
)
from test_helpers.test_users import (
    AGRO_HEADERS,
    TOURN_HEADERS,
    make_applicator_headers,
)
from test_helpers.types import (
    AgronomicStatus,
    IrrigationRunStatus,
    PlanStatus,
    PlanTaskStatus,
    PlayPosture,
    PostingStatus,
    RecordStatus,
    SourceType,
    WaterPosture,
    WeatherEventType,
    WindowStatus,
)


def _green_and_a_fungicide_with_a_twelve_mph_ceiling(distance_to_water_ft):
    """A 5500 sq ft green at the caller's chosen distance from water, plus a contact fungicide
    whose label reads 12 mph of wind, a 25 ft buffer, no re-entry interval and no nitrogen."""
    set_clock("2026-08-01T06:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(
        course["id"], hole_number=7, area_sq_ft=5500,
        distance_to_water_ft=distance_to_water_ft,
    )
    dana = create_applicator()
    fungicide = create_product(
        trade_name="Fairway Guard SC",
        epa_reg_no="1234-56",
        rei_hours=0,
        min_buffer_ft=25,
        max_wind_speed_mph=12,
        posting_required=False,
        nitrogen_pct=0,
    )
    return green7, dana, fungicide


def _green_taken_out_of_play_by_an_active_storm():
    """A green named by an active storm-damage declaration, which also closes the course."""
    set_clock("2026-08-01T06:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    storm = declare_weather_event(
        course["id"], WeatherEventType.STORM_DAMAGE.value, "2026-08-01T18:00:00Z",
        expected_course_version=course["version"],
        affected_turf_area_ids=[green7["id"]],
    )
    return course, green7, storm


def _three_hundred_gallon_course_with_a_well_and_a_reclaimed_source():
    """An allocation of only 300 gallons, and two identically sized stations that differ in
    nothing but their source type."""
    course = create_course(annual_water_allocation_gal=300)
    green3 = create_green(course["id"], hole_number=3, area_sq_ft=5500,
                          distance_to_water_ft=40)
    well = create_pump_station(
        course["id"], source_type=SourceType.WELL.value, max_flow_gpm=200,
        max_concurrent_zones=2, daily_withdrawal_cap_gal=10000,
    )
    reclaimed = create_pump_station(
        course["id"], source_type=SourceType.RECLAIMED.value, max_flow_gpm=200,
        max_concurrent_zones=2, daily_withdrawal_cap_gal=10000,
    )
    return course, green3, well, reclaimed


def _active_plan_with_two_tasks_and_three_candidate_windows():
    """Two aeration tasks planned for the ten days from 2026-08-10, and three aeration windows
    on the same green: one the day before the plan opens, one squarely inside it, and one
    ending exactly on the planned upper bound."""
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=40.0)
    task1 = create_plan_task(plan["id"], green7["id"], task_type=AERATION)
    task2 = create_plan_task(plan["id"], green7["id"], task_type=AERATION)
    early = create_maintenance_window(
        course["id"], green7["id"], AERATION,
        "2026-08-09T06:00:00Z", "2026-08-09T08:00:00Z",
    )
    inside = create_maintenance_window(
        course["id"], green7["id"], AERATION,
        "2026-08-10T06:00:00Z", "2026-08-10T08:00:00Z",
    )
    on_the_edge = create_maintenance_window(
        course["id"], green7["id"], AERATION,
        "2026-08-19T22:00:00Z", "2026-08-20T00:00:00Z",
    )
    submitted = submit_plan(plan["id"])
    active = approve_plan(plan["id"], submitted["version"])
    return plan, active, task1, task2, early, inside, on_the_edge


# --------------------------------------------------------------------------
# The inclusive edges of the spray gauntlet
# --------------------------------------------------------------------------
def test_wind_and_buffer_exactly_at_their_label_limits_are_both_admitted():
    """12 mph against a 12 mph ceiling and 25 ft against a 25 ft buffer are each permitted, so
    the spray records at 12.63 lb with no nitrogen and no posting.

    "Next, the observed `wind_speed_mph` must not exceed the product's `max_wind_speed_mph`;
    the comparison is inclusive, so wind exactly at the label limit is permitted, and anything
    above it is `ERR_WIND_LIMIT_EXCEEDED` (HTTP 422)."

    "Next comes the buffer zone: take the smaller of the application's observed
    `distance_to_water_ft` and the treated area's own recorded `distance_to_water_ft`, and
    require it to be greater than or equal to the product's `min_buffer_ft`; the comparison is
    inclusive, so a distance exactly equal to the buffer is permitted, and anything less is
    `ERR_BUFFER_ZONE_VIOLATION` (HTTP 422)."

    Design: Corner/validations/wind_and_buffer_exactly_at_their_inclusive_limits_are_admitted
    """
    green7, dana, fungicide = _green_and_a_fungicide_with_a_twelve_mph_ceiling(25)

    record = record_application(
        green7["id"], fungicide["id"], dana["id"], "2026-08-01T06:00:00Z",
        rate_lb_per_acre=100, wind_speed_mph=12, distance_to_water_ft=25,
    )

    assert_application(
        record,
        expected_version=1,
        record_status=RecordStatus.RECORDED.value,
        posting_status=PostingStatus.NOT_REQUIRED.value,
    )
    assert_2dp(record["total_lb"], 12.63)
    assert_2dp(record["nitrogen_lb"], 0.00)
    assert_instant(record["rei_expires_at"], "2026-08-01T06:00:00Z")
    reread = get_turf_area(green7["id"])
    assert_nitrogen_ledgers(reread, 0.000, 0.000)
    assert reread["rei_expires_at"] is None


def test_thirteen_mph_against_a_twelve_mph_ceiling_writes_nothing():
    """One mile per hour above the label refuses the spray with 422
    `ERR_WIND_LIMIT_EXCEEDED`, and the green is still on the version registration gave it.

    "Next, the observed `wind_speed_mph` must not exceed the product's `max_wind_speed_mph`;
    the comparison is inclusive, so wind exactly at the label limit is permitted, and anything
    above it is `ERR_WIND_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/wind_one_mph_above_the_product_limit_is_rejected
    """
    green7, dana, fungicide = _green_and_a_fungicide_with_a_twelve_mph_ceiling(40)

    refused = api_client.create_application(
        application_payload(
            green7["id"], fungicide["id"], dana["id"], "2026-08-01T06:00:00Z",
            rate_lb_per_acre=100, wind_speed_mph=13, distance_to_water_ft=40,
        ),
        make_applicator_headers(dana["id"]),
    )
    error = validate_error(refused, ERR_WIND_LIMIT_EXCEEDED, 422)
    assert error["message"].strip()

    _rows, meta = list_applications(turf_area_id=green7["id"])
    assert_total_count(meta, 0)
    assert_turf_area(get_turf_area(green7["id"]), expected_version=1)


# --------------------------------------------------------------------------
# The out-of-play gate on a measurement
# --------------------------------------------------------------------------
def test_a_reading_waits_for_the_storm_to_clear_before_it_can_be_taken():
    """While the green is `OUT_OF_PLAY` the reading is refused with 409
    `ERR_TURF_AREA_OUT_OF_PLAY`; once the storm clears the identical payload is accepted and
    moves the green's moisture to 19.0.

    "A reading may not be recorded on an `OUT_OF_PLAY` area, which is
    `ERR_TURF_AREA_OUT_OF_PLAY`."

    Design: Corner/validations/reading_on_an_out_of_play_green_is_rejected_until_the_storm_clears
    """
    course, green7, storm = _green_taken_out_of_play_by_an_active_storm()

    refused = api_client.create_playability_reading(
        playability_reading_payload(
            green7["id"], "2026-08-01T06:00:00Z",
            green_speed_ft=11.5, firmness_gravities=1.4, moisture_pct=19.0,
        ),
        TOURN_HEADERS,
    )
    validate_error(refused, ERR_TURF_AREA_OUT_OF_PLAY, 409)

    _rows, meta = list_playability_readings(green7["id"])
    assert_total_count(meta, 0)

    clear_weather_event(storm["id"])
    assert get_turf_area(green7["id"])["agronomic_status"] == (
        AgronomicStatus.ACTIVE.value
    )
    assert get_course(course["id"])["play_posture"] == PlayPosture.OPEN.value

    reading = create_playability_reading(
        green7["id"], "2026-08-01T06:00:00Z",
        green_speed_ft=11.5, firmness_gravities=1.4, moisture_pct=19.0,
        headers=TOURN_HEADERS,
    )
    assert_playability_reading(reading, within_tournament_spec=True)
    assert_turf_area(
        get_turf_area(green7["id"]), expected_version=4, current_moisture_pct=19.0
    )


# --------------------------------------------------------------------------
# The reclaimed-source exemption
# --------------------------------------------------------------------------
def test_the_reclaimed_station_books_the_run_the_well_could_not():
    """341.0 gallons against a 300 gallon allocation is refused on the well with 422
    `ERR_WATER_ALLOCATION_EXCEEDED` and admitted on the reclaimed source, whose booking still
    leaves the course ledger at zero.

    "It is enforced as a separate check: for a station whose `source_type` is not `RECLAIMED`,
    the course's `water_used_gal` plus the new run's `allotted_gal` must not exceed the
    course's `annual_water_allocation_gal`, and a breach is `ERR_WATER_ALLOCATION_EXCEEDED`
    (HTTP 422). For a `RECLAIMED` station the check is skipped entirely."

    Design: Corner/validations/reclaimed_water_is_exempt_from_the_allocation_check_that_stops_a_well
    """
    course, green3, well, reclaimed = (
        _three_hundred_gallon_course_with_a_well_and_a_reclaimed_source()
    )

    refused = api_client.create_irrigation_run(
        irrigation_run_payload(
            well["id"], green3["id"],
            "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 10, well["version"],
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_WATER_ALLOCATION_EXCEEDED, 422)

    _rows, meta = list_irrigation_runs(pump_station_id=well["id"])
    assert_total_count(meta, 0)

    admitted = create_irrigation_run(
        reclaimed["id"], green3["id"],
        "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 10,
        expected_pump_station_version=reclaimed["version"],
    )

    assert_irrigation_run(
        admitted,
        expected_version=1,
        status=IrrigationRunStatus.SCHEDULED.value,
        allotted_gal=341.0,
        flow_gpm=5.68,
        volume_gal=0,
    )
    reread_course = get_course(course["id"])
    assert_1dp(reread_course["water_used_gal"], 0.0)
    assert reread_course["water_posture"] == WaterPosture.OPEN.value


# --------------------------------------------------------------------------
# Containment inside the task's planned window
# --------------------------------------------------------------------------
def test_the_crew_window_must_sit_inside_the_planned_window_to_the_endpoint():
    """A window a day before the plan opens is refused with 422
    `ERR_APPLICATION_OUTSIDE_PLAN_WINDOW` and leaves the pinned version still current, while a
    window ending exactly on the planned upper bound binds.

    "the window's interval must be contained inside the task's planned window, meaning the
    window starts at or after `planned_window_start` and ends at or before
    `planned_window_end`, else `ERR_APPLICATION_OUTSIDE_PLAN_WINDOW`"

    Design: Corner/validations/scheduling_requires_the_window_to_sit_inside_the_planned_window
    """
    plan, active, task1, task2, early, inside, on_the_edge = (
        _active_plan_with_two_tasks_and_three_candidate_windows()
    )

    refused = api_client.schedule_plan_task(
        task1["id"],
        schedule_task_payload(early["id"], active["version"]),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_APPLICATION_OUTSIDE_PLAN_WINDOW, 422)

    assert_maintenance_window(
        get_maintenance_window(early["id"]),
        plan_task_id=None,
        status=WindowStatus.SCHEDULED.value,
    )
    assert_plan_task(
        get_plan_task(task1["id"]), status=PlanTaskStatus.PLANNED.value
    )

    schedule_plan_task(task1["id"], inside["id"], active["version"])
    assert get_plan_task(task1["id"])["status"] == PlanTaskStatus.SCHEDULED.value
    assert get_maintenance_window(inside["id"])["plan_task_id"] == task1["id"]

    schedule_plan_task(
        task2["id"], on_the_edge["id"], get_plan(plan["id"])["version"]
    )
    assert get_plan_task(task2["id"])["status"] == PlanTaskStatus.SCHEDULED.value
    assert get_maintenance_window(on_the_edge["id"])["plan_task_id"] == task2["id"]

    assert_plan(
        get_plan(plan["id"]),
        status=PlanStatus.ACTIVE.value,
        committed_nitrogen_lb=0.00,
    )
