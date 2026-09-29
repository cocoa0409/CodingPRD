"""Four writes whose legality is decided by the state of a different row: the course's play
posture over a crew start, the verifier's licence over a sign-off, the station's status over
a run booking, and the window's status over a task binding."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_COURSE_CLOSED,
    ERR_LICENSE_EXPIRED,
    ERR_PUMP_OFFLINE,
    ERR_RUN_STATE_INVALID,
    ERR_WINDOW_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_3dp,
    assert_applicator,
    assert_application,
    assert_instant,
    assert_irrigation_run,
    assert_maintenance_window,
    assert_plan,
    assert_total_count,
    assert_turf_area,
)
from test_helpers.factories import (
    FERTILITY,
    MOWING,
    STORM_CLEANUP,
    irrigation_run_payload,
    schedule_task_payload,
)
from test_helpers.fixtures import (
    approve_plan,
    create_applicator,
    create_course,
    create_green,
    create_irrigation_run,
    create_maintenance_window,
    create_plan,
    create_plan_task,
    create_product,
    create_pump_station,
    declare_weather_event,
    get_applicator,
    get_application,
    get_course,
    get_irrigation_run,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_pump_station,
    get_turf_area,
    list_irrigation_runs,
    record_application,
    reschedule_maintenance_window,
    schedule_plan_task,
    set_clock,
    set_pump_station_status,
    start_maintenance_window,
    submit_plan,
    void_application,
)
from test_helpers.test_users import (
    AGRO_HEADERS,
    TECH_HEADERS,
    make_applicator_headers,
)
from test_helpers.types import (
    AgronomicStatus,
    IrrigationRunStatus,
    LicenseStatus,
    PlanTaskStatus,
    PlayPosture,
    PumpStationStatus,
    RecordStatus,
    SourceType,
    VoidReason,
    WeatherEventType,
    WindowStatus,
)


def _closed_course_with_two_waiting_crews():
    """Lightning closes the course at 12:00Z while a mowing crew and a storm-cleanup crew
    both wait for a 14:00Z start that the strike interval never touches."""
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=4300,
                           distance_to_water_ft=200)
    win_mow = create_maintenance_window(
        course["id"], green7["id"], MOWING,
        "2026-08-05T14:00:00Z", "2026-08-05T15:00:00Z", crew_size=3,
    )
    win_clean = create_maintenance_window(
        course["id"], green12["id"], STORM_CLEANUP,
        "2026-08-05T14:00:00Z", "2026-08-05T15:00:00Z", crew_size=5,
    )
    set_clock("2026-08-05T12:00:00Z")
    lightning = declare_weather_event(
        course["id"],
        WeatherEventType.LIGHTNING.value,
        "2026-08-05T13:00:00Z",
        expected_course_version=course["version"],
    )
    return course, green12, win_mow, win_clean, lightning


def _suspended_verifier_and_an_untouched_record():
    """Miguel's licence is suspended by a safety void on his own spray, and Dana then
    records the unrelated application he will try to sign off."""
    set_clock("2026-08-01T06:00:00Z")
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=4300,
                           distance_to_water_ft=200)
    dana = create_applicator()
    miguel = create_applicator(
        full_name="Miguel Ortiz",
        license_number="OR-CAT37-22002",
        license_category="CAT_3_AND_7",
        license_expires_on="2028-03-31",
    )
    urea = create_product()
    miguels_spray = record_application(
        green12["id"], urea["id"], miguel["id"], "2026-08-01T06:00:00Z",
        rate_lb_per_acre=200, wind_speed_mph=5, distance_to_water_ft=200,
    )
    return green7, green12, dana, miguel, urea, miguels_spray


def _dana_records_after_the_void(green7, dana, urea, miguels_spray):
    """Void Miguel's record for a safety violation, then let Dana spray hole 7."""
    voided = void_application(miguels_spray["id"], VoidReason.SAFETY_VIOLATION.value)
    danas_spray = record_application(
        green7["id"], urea["id"], dana["id"], "2026-08-01T06:00:00Z",
        rate_lb_per_acre=200, wind_speed_mph=5, distance_to_water_ft=40,
    )
    return voided, danas_spray


def _online_station_carrying_one_scheduled_run():
    """A 300 gpm well station with one 170.5 gallon run booked from 04:00Z to 05:00Z."""
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    station = create_pump_station(
        course["id"],
        source_type=SourceType.WELL.value,
        max_flow_gpm=300,
        max_concurrent_zones=2,
        daily_withdrawal_cap_gal=10000,
    )
    run = create_irrigation_run(
        station["id"], green7["id"],
        "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 5,
        expected_pump_station_version=station["version"],
    )
    return course, green7, station, run


def _deferred_window_waiting_for_a_task():
    """Heavy rain defers an empty fertility window before any task is bound to it."""
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=8.0)
    task = create_plan_task(plan["id"], green7["id"], nitrogen_lb_per_1000=0.85)
    submitted = submit_plan(plan["id"])
    active = approve_plan(plan["id"], submitted["version"])
    window = create_maintenance_window(
        course["id"], green7["id"], FERTILITY,
        "2026-08-12T05:00:00Z", "2026-08-12T07:00:00Z",
    )
    rain = declare_weather_event(
        course["id"],
        WeatherEventType.HEAVY_RAIN.value,
        "2026-08-12T06:00:00Z",
        expected_course_version=course["version"],
    )
    return plan, active, task, window, rain


# --------------------------------------------------------------------------
# The course's play posture decides whether a crew may start
# --------------------------------------------------------------------------
def test_a_closed_course_refuses_the_mowing_crew_that_was_already_booked():
    """Lightning closes the course without deferring either window, and the mowing start
    is then refused with 409 `ERR_COURSE_CLOSED`.

    "The course's play posture must not be `CLOSED` unless the task class is
    `STORM_CLEANUP`, else `ERR_COURSE_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/window_start_depends_on_course_play_posture
    """
    course, _green12, win_mow, win_clean, lightning = (
        _closed_course_with_two_waiting_crews()
    )

    closed = get_course(course["id"])
    assert closed["play_posture"] == PlayPosture.CLOSED.value
    assert closed["frost_delay_minutes"] == 0
    assert lightning["deferred_window_count"] == 0
    for window in (win_mow, win_clean):
        assert_maintenance_window(
            get_maintenance_window(window["id"]),
            expected_version=1,
            status=WindowStatus.SCHEDULED.value,
        )

    refused = api_client.start_maintenance_window(win_mow["id"], AGRO_HEADERS)
    validate_error(refused, ERR_COURSE_CLOSED, 409)

    assert_maintenance_window(
        get_maintenance_window(win_mow["id"]),
        expected_version=1,
        status=WindowStatus.SCHEDULED.value,
    )


def test_the_storm_cleanup_crew_starts_on_the_same_closed_course():
    """Storm cleanup is the exempt task class, so its crew goes to work on the closed
    course and the area it occupies stays `ACTIVE`.

    "On success the window's `version` is incremented by 1, and when the task class is
    `AERATION` the turf area's `agronomic_status` becomes `UNDER_RENOVATION` with that
    area's `version` incremented by 1."

    Design: Difficulty/cross_entity_state_dependency/window_start_depends_on_course_play_posture
    """
    _course, green12, _win_mow, win_clean, _lightning = (
        _closed_course_with_two_waiting_crews()
    )

    started = start_maintenance_window(win_clean["id"])
    assert_maintenance_window(
        started,
        expected_version=2,
        status=WindowStatus.IN_PROGRESS.value,
        crew_hours=5.00,
    )
    assert_turf_area(
        get_turf_area(green12["id"]),
        agronomic_status=AgronomicStatus.ACTIVE.value,
    )


# --------------------------------------------------------------------------
# The verifier's licence decides whether a record may be signed off
# --------------------------------------------------------------------------
def test_a_suspended_verifier_cannot_sign_off_another_applicators_record():
    """Miguel's licence was suspended by a void on his own spray, so his sign-off on
    Dana's unrelated record is refused with 422 `ERR_LICENSE_EXPIRED`.

    "The verifying applicator, resolved from `X-User-ID`, is themselves subject to the
    licence tests: their `license_status` must be `ACTIVE`, else `ERR_LICENSE_EXPIRED`, and
    their `license_category` must authorise the product's `requires_license_category` by
    the same authority table, else `ERR_LICENSE_CATEGORY_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/application_verify_depends_on_verifier_applicator_license_state
    """
    green7, _green12, dana, miguel, urea, miguels_spray = (
        _suspended_verifier_and_an_untouched_record()
    )
    _voided, danas_spray = _dana_records_after_the_void(
        green7, dana, urea, miguels_spray
    )

    refused = api_client.verify_application(
        danas_spray["id"], make_applicator_headers(miguel["id"])
    )
    validate_error(refused, ERR_LICENSE_EXPIRED, 422)

    assert_application(
        get_application(danas_spray["id"]),
        expected_version=1,
        record_status=RecordStatus.RECORDED.value,
        verified_by_applicator_id=None,
    )
    assert_3dp(
        get_turf_area(green7["id"])["nitrogen_applied_lb_per_1000_ytd"], 2.113
    )


def test_the_safety_void_is_what_moved_the_verifier_out_of_active():
    """Before the void the hole 12 green carried 2.112 lb per thousand from a 19.74 lb
    spray; the void empties that ledger and suspends Miguel at the logical clock, while
    Dana's licence is untouched.

    "When the reason is `SAFETY_VIOLATION`, the recording applicator's `license_status`
    becomes `SUSPENDED`, their `suspended_at` is stamped with the logical clock, and that
    applicator's `version` is incremented by 1; a `DATA_ENTRY_ERROR` void leaves the
    licence alone."

    Design: Difficulty/cross_entity_state_dependency/application_verify_depends_on_verifier_applicator_license_state
    """
    green7, green12, dana, miguel, urea, miguels_spray = (
        _suspended_verifier_and_an_untouched_record()
    )

    assert_2dp(miguels_spray["total_lb"], 19.74)
    assert_2dp(miguels_spray["nitrogen_lb"], 9.08)
    assert_3dp(
        get_turf_area(green12["id"])["nitrogen_applied_lb_per_1000_ytd"], 2.112
    )

    _voided, _danas_spray = _dana_records_after_the_void(
        green7, dana, urea, miguels_spray
    )

    assert_3dp(
        get_turf_area(green12["id"])["nitrogen_applied_lb_per_1000_ytd"], 0.000
    )
    assert_applicator(
        get_applicator(miguel["id"]),
        license_status=LicenseStatus.SUSPENDED.value,
        suspended_at="2026-08-01T06:00:00Z",
    )
    reread_dana = get_applicator(dana["id"])
    assert reread_dana["license_status"] == LicenseStatus.ACTIVE.value
    assert reread_dana["suspended_at"] is None


# --------------------------------------------------------------------------
# The station's status decides whether a run may be booked
# --------------------------------------------------------------------------
def test_taking_the_station_offline_cancels_its_run_and_bars_the_next_one():
    """The technician's `OFFLINE` patch cancels the 170.5 gallon run and the next booking
    on that station is refused with 409 `ERR_PUMP_OFFLINE`.

    "The station must not be `OFFLINE`, else `ERR_PUMP_OFFLINE` (HTTP 409); both `ONLINE`
    and `RESTRICTED` stations admit runs, since a restricted station simply irrigates at
    the reduced posture factor."

    Design: Difficulty/cross_entity_state_dependency/irrigation_run_creation_depends_on_pump_station_status
    """
    _course, green7, station, run = _online_station_carrying_one_scheduled_run()

    assert_irrigation_run(
        run,
        status=IrrigationRunStatus.SCHEDULED.value,
        allotted_gal=170.5,
        flow_gpm=2.84,
        volume_gal=0,
    )

    offline = set_pump_station_status(
        station["id"], PumpStationStatus.OFFLINE.value, headers=TECH_HEADERS
    )
    assert offline["status"] == PumpStationStatus.OFFLINE.value

    cancelled = get_irrigation_run(run["id"])
    assert cancelled["status"] == IrrigationRunStatus.CANCELLED.value
    assert_1dp(cancelled["volume_gal"], 0)

    refused = api_client.create_irrigation_run(
        irrigation_run_payload(
            station["id"], green7["id"],
            "2026-08-05T06:00:00Z", "2026-08-05T07:00:00Z", 5,
            offline["version"],
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_PUMP_OFFLINE, 409)

    _rows, meta = list_irrigation_runs(pump_station_id=station["id"])
    assert_total_count(meta, 1)


def test_the_cancelled_run_reports_its_own_state_rather_than_the_station_status():
    """Completing the run the cascade cancelled answers `ERR_RUN_STATE_INVALID`, because
    the run-state rule is checked before the station rule, and neither ledger moves.

    "The run must be in `SCHEDULED`, else `ERR_RUN_STATE_INVALID` (HTTP 409); the supplying
    station must not be `OFFLINE`, else `ERR_PUMP_OFFLINE`; and the irrigated area must not
    be `OUT_OF_PLAY`, else `ERR_TURF_AREA_OUT_OF_PLAY`."

    Design: Difficulty/cross_entity_state_dependency/irrigation_run_creation_depends_on_pump_station_status
    """
    course, _green7, station, run = _online_station_carrying_one_scheduled_run()

    set_pump_station_status(
        station["id"], PumpStationStatus.OFFLINE.value, headers=TECH_HEADERS
    )

    refused = api_client.complete_irrigation_run(run["id"], AGRO_HEADERS, {})
    validate_error(refused, ERR_RUN_STATE_INVALID, 409)

    assert get_irrigation_run(run["id"])["status"] == (
        IrrigationRunStatus.CANCELLED.value
    )
    assert_1dp(get_pump_station(station["id"])["withdrawn_today_gal"], 0)
    assert_1dp(get_course(course["id"])["water_used_gal"], 0)


# --------------------------------------------------------------------------
# The window's status decides whether a task may be bound
# --------------------------------------------------------------------------
def test_a_deferred_window_cannot_receive_a_plan_task():
    """Rain deferred the empty window, so binding the task to it is refused with 409
    `ERR_WINDOW_STATE_INVALID` and the plan ledger stays empty.

    "the named window must be in status `SCHEDULED` and must not already carry a task,
    else `ERR_WINDOW_STATE_INVALID`"

    Design: Difficulty/cross_entity_state_dependency/task_scheduling_depends_on_target_window_state
    """
    plan, active, task, window, rain = _deferred_window_waiting_for_a_task()

    assert_maintenance_window(
        get_maintenance_window(window["id"]),
        status=WindowStatus.DEFERRED.value,
        deferral_count=1,
        plan_task_id=None,
    )
    assert rain["deferred_window_count"] == 1

    refused = api_client.schedule_plan_task(
        task["id"],
        schedule_task_payload(window["id"], active["version"]),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_WINDOW_STATE_INVALID, 409)

    assert get_plan_task(task["id"])["status"] == PlanTaskStatus.PLANNED.value
    assert_plan(
        get_plan(plan["id"]),
        expected_version=active["version"],
        committed_nitrogen_lb=0.00,
    )


def test_rescheduling_the_window_makes_the_same_binding_legal():
    """A reschedule returns the window to `SCHEDULED` without giving back its deferral,
    and the identical binding — reusing the plan version the refusal never bumped — then
    commits 4.68 lb.

    "When the window carries a plan task that is currently `PLANNED`, that task advances
    `PLANNED → SCHEDULED`, restoring its `commitment_lb` to both the plan's
    `committed_nitrogen_lb` and the turf area's `nitrogen_projected_lb_per_1000`."

    Design: Difficulty/cross_entity_state_dependency/task_scheduling_depends_on_target_window_state
    """
    plan, active, task, window, _rain = _deferred_window_waiting_for_a_task()

    refused = api_client.schedule_plan_task(
        task["id"],
        schedule_task_payload(window["id"], active["version"]),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_WINDOW_STATE_INVALID, 409)

    rescheduled = reschedule_maintenance_window(
        window["id"], "2026-08-15T05:00:00Z", "2026-08-15T07:00:00Z"
    )
    assert_maintenance_window(
        rescheduled,
        status=WindowStatus.SCHEDULED.value,
        deferral_count=1,
    )
    assert_instant(rescheduled["window_start"], "2026-08-15T05:00:00Z")

    schedule_plan_task(task["id"], window["id"], active["version"])

    assert get_plan_task(task["id"])["status"] == PlanTaskStatus.SCHEDULED.value
    assert get_maintenance_window(window["id"])["plan_task_id"] == task["id"]
    assert_2dp(get_plan(plan["id"])["committed_nitrogen_lb"], 4.68)
