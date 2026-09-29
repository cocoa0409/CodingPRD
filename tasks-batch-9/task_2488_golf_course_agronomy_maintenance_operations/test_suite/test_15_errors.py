"""The error catalogue read from the outside: each declared not-found code reported by its
own read, and six named failures that each leave the store exactly as they found it."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_FOUND,
    ERR_APPLICATOR_NOT_FOUND,
    ERR_DUPLICATE_LICENSE_NUMBER,
    ERR_EQUIPMENT_NOT_FOUND,
    ERR_IRRIGATION_RUN_NOT_FOUND,
    ERR_PLAN_NOT_FOUND,
    ERR_PLAN_TASK_NOT_FOUND,
    ERR_PLAY_EVENT_NOT_FOUND,
    ERR_PLAY_EVENT_STATE_INVALID,
    ERR_PRODUCT_NOT_FOUND,
    ERR_PUMP_STATION_NOT_FOUND,
    ERR_TASK_STATE_INVALID,
    ERR_TURF_AREA_NOT_FOUND,
    ERR_WEATHER_EVENT_NOT_FOUND,
    ERR_WINDOW_NOT_FOUND,
    ERR_ZERO_ALLOTMENT,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_3dp,
    assert_applicator,
    assert_course,
    assert_irrigation_run,
    assert_maintenance_window,
    assert_plan,
    assert_plan_task,
    assert_play_event,
    assert_total_count,
    assert_turf_area,
)
from test_helpers.factories import (
    AERATION,
    applicator_payload,
    application_payload,
    irrigation_run_payload,
    schedule_task_payload,
)
from test_helpers.fixtures import (
    approve_plan,
    complete_irrigation_run,
    create_applicator,
    create_course,
    create_green,
    create_irrigation_run,
    create_maintenance_window,
    create_plan,
    create_plan_task,
    create_pump_station,
    create_tournament_round,
    declare_weather_event,
    get_applicator,
    get_course,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_play_event,
    get_pump_station,
    get_turf_area,
    list_applicators,
    list_applications,
    list_course_weather_events,
    list_irrigation_runs,
    schedule_plan_task,
    set_clock,
    submit_plan,
)
from test_helpers.test_users import (
    AGRO_HEADERS,
    SUPER_HEADERS,
    TOURN_HEADERS,
    make_applicator_headers,
)
from test_helpers.types import (
    LicenseCategory,
    PlanTaskStatus,
    PlayEventStatus,
    PlayPosture,
    ReadinessStatus,
    SourceType,
    WaterPosture,
    WeatherEventStatus,
    WeatherEventType,
    WindowStatus,
)


def _reclaimed_station_that_has_drawn_its_whole_cap():
    """A reclaimed station whose 341 gallon cap is exactly the demand of one hour at a
    10-point deficit on a 5500 sq ft green, with that hour already delivered today."""
    set_clock("2026-08-05T00:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green3 = create_green(course["id"], hole_number=3, area_sq_ft=5500,
                          distance_to_water_ft=40)
    station = create_pump_station(
        course["id"], source_type=SourceType.RECLAIMED.value, max_flow_gpm=200,
        max_concurrent_zones=2, daily_withdrawal_cap_gal=341,
    )
    run_a = create_irrigation_run(
        station["id"], green3["id"],
        "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 10,
        expected_pump_station_version=station["version"],
    )
    completed = complete_irrigation_run(run_a["id"])
    return course, green3, station, completed


def _active_plan_whose_only_task_is_already_bound():
    """One aeration task bound to the first of two identical aeration windows, both of which
    sit inside the task's planned ten days."""
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=40.0)
    task1 = create_plan_task(plan["id"], green7["id"], task_type=AERATION)
    w_first = create_maintenance_window(
        course["id"], green7["id"], AERATION,
        "2026-08-11T06:00:00Z", "2026-08-11T08:00:00Z",
    )
    w_second = create_maintenance_window(
        course["id"], green7["id"], AERATION,
        "2026-08-12T06:00:00Z", "2026-08-12T08:00:00Z",
    )
    submitted = submit_plan(plan["id"])
    active = approve_plan(plan["id"], submitted["version"])
    schedule_plan_task(task1["id"], w_first["id"], active["version"])
    return plan, task1, w_first, w_second


# --------------------------------------------------------------------------
# Every declared not-found code, reported by its own read
# --------------------------------------------------------------------------
def test_the_agronomy_reads_each_report_their_own_missing_row():
    """Against an empty store the five agronomy reads answer 404 with five different
    identifiers rather than one shared code.

    "`ERR_TURF_AREA_NOT_FOUND` (404) — for `GET /turf-areas/{id}`,
    `GET /turf-areas/{id}/playability-readings`, `POST /plan-tasks`, `POST /applications`,
    `POST /irrigation-runs`, `POST /maintenance-windows`, `POST /playability-readings`,
    `POST /weather-events`; on the last of these it covers every member of
    `affected_turf_area_ids`."

    "`ERR_PLAN_NOT_FOUND` (404) — for `GET /agronomic-plans/{id}`,
    `POST /agronomic-plans/{id}/submit`, `POST /agronomic-plans/{id}/return`,
    `POST /agronomic-plans/{id}/approve`, `POST /plan-tasks`."

    "`ERR_PLAN_TASK_NOT_FOUND` (404) — for `GET /plan-tasks/{id}`,
    `POST /plan-tasks/{id}/schedule`, `POST /applications`, `POST /maintenance-windows`."

    "`ERR_APPLICATOR_NOT_FOUND` (404) — for `GET /applicators/{id}`, `POST /applications`,
    `POST /applications/{id}/verify`."

    "`ERR_APPLICATION_NOT_FOUND` (404) — for `GET /applications/{id}`,
    `POST /applications/{id}/verify`, `POST /applications/{id}/void`,
    `POST /applications/{id}/release-posting`."

    Design: Corner/errors/every_declared_get_by_id_returns_its_own_not_found_error
    """
    validate_error(
        api_client.get_turf_area(NON_EXISTENT_UUID, SUPER_HEADERS),
        ERR_TURF_AREA_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_plan(NON_EXISTENT_UUID, SUPER_HEADERS),
        ERR_PLAN_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_plan_task(NON_EXISTENT_UUID, SUPER_HEADERS),
        ERR_PLAN_TASK_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_applicator(NON_EXISTENT_UUID, SUPER_HEADERS),
        ERR_APPLICATOR_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_application(NON_EXISTENT_UUID, SUPER_HEADERS),
        ERR_APPLICATION_NOT_FOUND,
        404,
    )


def test_the_operations_reads_each_report_their_own_missing_row():
    """The water, crew, play and fleet reads likewise answer 404 with their own identifiers,
    so a caller can tell which of several referenced rows was the one that was missing.

    "`ERR_PUMP_STATION_NOT_FOUND` (404) — for `GET /pump-stations/{id}`,
    `PATCH /pump-stations/{id}/status`, `POST /irrigation-runs`."

    "`ERR_IRRIGATION_RUN_NOT_FOUND` (404) — for `GET /irrigation-runs/{id}`,
    `POST /irrigation-runs/{id}/complete`, `POST /irrigation-runs/{id}/reverse`."

    "`ERR_WINDOW_NOT_FOUND` (404) — for `GET /maintenance-windows/{id}`,
    `POST /maintenance-windows/{id}/start`, `POST /maintenance-windows/{id}/complete`,
    `POST /maintenance-windows/{id}/reschedule`, `POST /plan-tasks/{id}/schedule`."

    "`ERR_PLAY_EVENT_NOT_FOUND` (404) — for `GET /play-events/{id}`,
    `POST /play-events/{id}/certify-conditions`."

    "`ERR_EQUIPMENT_NOT_FOUND` (404) — for `GET /equipment-units/{id}`,
    `POST /equipment-units/{id}/log-hours`, `POST /equipment-units/{id}/service`,
    `POST /equipment-units/{id}/retire`; on retire it covers a supplied
    `replacement_unit_id` as well as the path id."

    Design: Corner/errors/every_declared_get_by_id_returns_its_own_not_found_error
    """
    validate_error(
        api_client.get_pump_station(NON_EXISTENT_UUID, SUPER_HEADERS),
        ERR_PUMP_STATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_irrigation_run(NON_EXISTENT_UUID, SUPER_HEADERS),
        ERR_IRRIGATION_RUN_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_maintenance_window(NON_EXISTENT_UUID, SUPER_HEADERS),
        ERR_WINDOW_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_play_event(NON_EXISTENT_UUID, SUPER_HEADERS),
        ERR_PLAY_EVENT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_equipment_unit(NON_EXISTENT_UUID, SUPER_HEADERS),
        ERR_EQUIPMENT_NOT_FOUND,
        404,
    )


def test_clearing_an_event_that_was_never_declared_is_a_miss():
    """With a course on file the failure cannot be blamed on a missing course, so the clear
    answers 404 `ERR_WEATHER_EVENT_NOT_FOUND` and the weather log stays empty.

    "The event must be `ACTIVE`, else `ERR_WEATHER_STATE_INVALID` (HTTP 409); an event that
    does not exist is `ERR_WEATHER_EVENT_NOT_FOUND`."

    "`ERR_WEATHER_EVENT_NOT_FOUND` (404) — for `POST /weather-events/{id}/clear`."

    Design: Corner/errors/clearing_an_unknown_weather_event_returns_not_found
    """
    course = create_course(annual_water_allocation_gal=500000)

    refused = api_client.clear_weather_event(NON_EXISTENT_UUID, SUPER_HEADERS)
    validate_error(refused, ERR_WEATHER_EVENT_NOT_FOUND, 404)

    _rows, meta = list_course_weather_events(course["id"])
    assert_total_count(meta, 0)
    reread = get_course(course["id"])
    assert_course(reread, expected_version=1, play_posture=PlayPosture.OPEN.value)


def test_a_spray_naming_a_product_that_is_not_on_file_writes_nothing():
    """The area and the applicator both resolve, so the miss is attributed to the label
    record: 404 `ERR_PRODUCT_NOT_FOUND`, no record written, and the green's ledger at zero.

    "`ERR_PRODUCT_NOT_FOUND` (404) — for `POST /applications`."

    Design: Corner/errors/application_naming_an_unknown_product_returns_not_found
    """
    set_clock("2026-08-01T06:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    dana = create_applicator(
        license_category=LicenseCategory.CAT_3_TURF.value,
        license_expires_on="2027-06-30",
    )

    refused = api_client.create_application(
        application_payload(
            green7["id"], NON_EXISTENT_UUID, dana["id"], "2026-08-01T06:00:00Z",
            rate_lb_per_acre=100, wind_speed_mph=4, distance_to_water_ft=40,
        ),
        make_applicator_headers(dana["id"]),
    )
    validate_error(refused, ERR_PRODUCT_NOT_FOUND, 404)

    _rows, meta = list_applications(turf_area_id=green7["id"])
    assert_total_count(meta, 0)
    reread = get_turf_area(green7["id"])
    assert_turf_area(reread, expected_version=1)
    assert_3dp(reread["nitrogen_applied_lb_per_1000_ytd"], 0.000)


# --------------------------------------------------------------------------
# Uniqueness, headroom, state and cancellation
# --------------------------------------------------------------------------
def test_a_second_applicator_cannot_reuse_a_license_number():
    """The repeat licence number is refused with 409 `ERR_DUPLICATE_LICENSE_NUMBER` and
    creates nothing, while the very same registration under a distinct number is accepted.

    "a `license_number` which may not be empty and which must be globally unique across all
    applicators — a repeat is rejected with `ERR_DUPLICATE_LICENSE_NUMBER` (HTTP 409)"

    "`ERR_DUPLICATE_LICENSE_NUMBER` (409) — for `POST /applicators`."

    Design: Corner/errors/a_reused_license_number_is_rejected
    """
    dana = create_applicator(
        full_name="Dana Reyes",
        license_number="OR-CAT3-15001",
        license_category=LicenseCategory.CAT_3_TURF.value,
        license_expires_on="2027-06-30",
    )

    refused = api_client.create_applicator(
        applicator_payload(
            full_name="Miguel Santos",
            license_number="OR-CAT3-15001",
            license_category=LicenseCategory.CAT_7_AQUATIC.value,
            license_expires_on="2028-01-31",
        ),
        SUPER_HEADERS,
    )
    validate_error(refused, ERR_DUPLICATE_LICENSE_NUMBER, 409)

    miguel = create_applicator(
        full_name="Miguel Santos",
        license_number="OR-CAT3-15002",
        license_category=LicenseCategory.CAT_7_AQUATIC.value,
        license_expires_on="2028-01-31",
    )
    assert_applicator(
        miguel,
        expected_version=1,
        license_category=LicenseCategory.CAT_7_AQUATIC.value,
    )

    _rows, meta = list_applicators()
    assert_total_count(meta, 2)
    assert_applicator(get_applicator(dana["id"]), expected_version=1)


def test_a_station_that_has_drawn_its_whole_cap_can_book_no_further_run():
    """With headroom floored at zero the second run's allotment collapses to nothing, so the
    booking answers 422 `ERR_ZERO_ALLOTMENT` — not the allocation error, from which a
    reclaimed source is exempt.

    "Separately, the station's remaining daily headroom is its `daily_withdrawal_cap_gal` less
    its `withdrawn_today_gal`, floored at zero so it never goes negative."

    "Last, the computed `allotted_gal` must be strictly greater than zero, else
    `ERR_ZERO_ALLOTMENT` (HTTP 422) — which is what a `SUSPENDED` posture, a zero deficit, or
    an exhausted daily headroom each collapse into."

    Design: Corner/errors/a_run_with_no_remaining_daily_headroom_is_rejected
    """
    course, green3, station, completed = _reclaimed_station_that_has_drawn_its_whole_cap()

    assert_irrigation_run(completed, allotted_gal=341.0, flow_gpm=5.68, volume_gal=341.0)
    drawn_out = get_pump_station(station["id"])
    assert_1dp(drawn_out["withdrawn_today_gal"], 341.0)

    refused = api_client.create_irrigation_run(
        irrigation_run_payload(
            station["id"], green3["id"],
            "2026-08-05T06:00:00Z", "2026-08-05T07:00:00Z", 10,
            drawn_out["version"],
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_ZERO_ALLOTMENT, 422)

    _rows, meta = list_irrigation_runs(pump_station_id=station["id"])
    assert_total_count(meta, 1)
    reread_course = get_course(course["id"])
    assert_1dp(reread_course["water_used_gal"], 341.0)
    assert reread_course["water_posture"] == WaterPosture.OPEN.value


def test_a_task_already_bound_to_a_window_cannot_be_bound_to_another():
    """The pinned plan version is current, so the refusal is the state rule and not the
    precondition failure: 409 `ERR_TASK_STATE_INVALID`, with the first binding intact and the
    second window still free.

    "the task must be in `PLANNED`, else `ERR_TASK_STATE_INVALID`"

    "`ERR_TASK_STATE_INVALID` (409) — for `POST /plan-tasks/{id}/schedule`,
    `POST /applications`."

    Design: Corner/errors/scheduling_a_task_that_is_already_scheduled_is_rejected
    """
    plan, task1, w_first, w_second = _active_plan_whose_only_task_is_already_bound()
    version_now = get_plan(plan["id"])["version"]

    refused = api_client.schedule_plan_task(
        task1["id"],
        schedule_task_payload(w_second["id"], version_now),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_TASK_STATE_INVALID, 409)

    assert_plan_task(
        get_plan_task(task1["id"]),
        status=PlanTaskStatus.SCHEDULED.value,
    )
    # The binding's back-reference lives on the window, not on the task: PRD 3.3 says
    # "The window records the task's identifier in its own `plan_task_id`" and never
    # declares a `maintenance_window_id` field on the plan-task resource.
    assert get_maintenance_window(w_first["id"])["plan_task_id"] == task1["id"]
    assert_maintenance_window(
        get_maintenance_window(w_second["id"]),
        plan_task_id=None,
        status=WindowStatus.SCHEDULED.value,
    )
    assert_plan(get_plan(plan["id"]), expected_version=version_now)


def test_a_round_cancelled_by_lightning_cannot_be_certified():
    """Two rules are broken at once — the round is `CANCELLED` and the course is `CLOSED` —
    and the smaller priority answers, so the response is 409
    `ERR_PLAY_EVENT_STATE_INVALID` and the readiness dimension never moves.

    "Two conditions block the attempt outright: a play event whose schedule status is
    `CANCELLED` cannot be certified and yields `ERR_PLAY_EVENT_STATE_INVALID` (HTTP 409), and
    a course whose play posture is `CLOSED` refuses certification with `ERR_COURSE_CLOSED`."

    "When one request violates two or more rules, the rule with the numerically smallest
    priority determines the response and no later rule's error is reported."

    Design: Corner/errors/certifying_a_cancelled_play_event_is_rejected
    """
    set_clock("2026-08-01T06:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    round_posted = create_tournament_round(
        course["id"],
        start_at="2026-08-01T14:00:00Z",
        end_at="2026-08-01T18:00:00Z",
        holes_in_play=18,
    )
    lightning = declare_weather_event(
        course["id"], WeatherEventType.LIGHTNING.value, "2026-08-01T18:00:00Z",
        expected_course_version=course["version"],
    )

    refused = api_client.certify_conditions(round_posted["id"], TOURN_HEADERS)
    validate_error(refused, ERR_PLAY_EVENT_STATE_INVALID, 409)

    assert_play_event(
        get_play_event(round_posted["id"]),
        status=PlayEventStatus.CANCELLED.value,
        readiness_status=ReadinessStatus.PENDING.value,
        readiness_index=None,
    )
    reread = get_course(course["id"])
    assert_course(
        reread, expected_version=2, play_posture=PlayPosture.CLOSED.value
    )
    assert lightning["status"] == WeatherEventStatus.ACTIVE.value
