"""Three quantities that come back to the value they left: committed nitrogen across a
defer and reschedule, withdrawn water across a run reversal, and the engine-hour meter
across a completed service."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_EQUIPMENT_STATE_INVALID
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_equipment_unit,
    assert_irrigation_run,
    assert_maintenance_window,
    assert_nitrogen_ledgers,
    assert_replacement_scores,
    assert_water_ledgers,
)
from test_helpers.factories import service_payload
from test_helpers.fixtures import (
    build_fleet_environment,
    build_two_task_plan_environment,
    complete_irrigation_run,
    create_course,
    create_green,
    create_irrigation_run,
    create_pump_station,
    declare_weather_event,
    get_course,
    get_equipment_unit,
    get_irrigation_run,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_pump_station,
    get_turf_area,
    log_equipment_hours,
    reschedule_maintenance_window,
    reverse_irrigation_run,
    service_equipment_unit,
    set_clock,
)
from test_helpers.test_users import TECH_HEADERS
from test_helpers.types import (
    EquipmentStatus,
    IrrigationRunStatus,
    PlanTaskStatus,
    PumpStationStatus,
    SourceType,
    WaterPosture,
    WeatherEventType,
    WindowStatus,
)


def _eight_hundred_gallon_course_with_a_full_days_run():
    """An 800 gal allocation and one 682.0 gal run booked but not yet completed, on the
    calendar day the run's window falls on."""
    set_clock("2026-08-05T00:00:00Z")
    course = create_course(
        annual_water_allocation_gal=800,
        water_restricted_threshold_pct=80,
        water_suspended_threshold_pct=100,
    )
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
        "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 20,
        expected_pump_station_version=station["version"],
    )
    return course, station, run


def _triplex_down_for_service_at_forty_five_hundred_hours():
    """A 2018 triplex with 4500 meter hours, 300 of them since its last service, which the
    hours entry has already downed for maintenance."""
    env = build_fleet_environment(initial_engine_hours=4200)
    logged = log_equipment_hours(env.unit["id"], 300)
    return env.unit, logged


# --------------------------------------------------------------------------
# Committed nitrogen: debited by weather, credited back by the reschedule
# --------------------------------------------------------------------------
def test_the_plan_ledger_returns_to_seven_ninety_one_to_the_cent():
    """Rain debits 4.68 lb from a 7.91 lb ledger and the reschedule credits exactly that
    figure back, with no rounding drift on the round trip.

    "When the window carries a plan task that is currently `PLANNED`, that task advances
    `PLANNED → SCHEDULED`, restoring its `commitment_lb` to both the plan's
    `committed_nitrogen_lb` and the turf area's `nitrogen_projected_lb_per_1000`."

    Design: Difficulty/compensating_invariant/nitrogen_ledger_returns_to_its_exact_value_after_defer_and_reschedule
    """
    env = build_two_task_plan_environment(
        nitrogen_budget_lb=8.00, schedule_first=True, schedule_second=True
    )

    assert_2dp(get_plan(env.plan["id"])["committed_nitrogen_lb"], 7.91)

    declare_weather_event(
        env.course["id"], WeatherEventType.HEAVY_RAIN.value, "2026-08-12T06:00:00Z"
    )
    assert_2dp(get_plan(env.plan["id"])["committed_nitrogen_lb"], 3.23)
    assert get_plan_task(env.task1["id"])["status"] == PlanTaskStatus.PLANNED.value

    reschedule_maintenance_window(
        env.window1["id"], "2026-08-15T05:00:00Z", "2026-08-15T07:00:00Z"
    )

    assert_2dp(get_plan(env.plan["id"])["committed_nitrogen_lb"], 7.91)
    assert get_plan_task(env.task1["id"])["status"] == PlanTaskStatus.SCHEDULED.value
    assert get_maintenance_window(env.window1["id"])["plan_task_id"] == env.task1["id"]


def test_the_deferral_counter_and_the_versions_do_not_come_back():
    """The quantity is compensated but the monotone counters are not: the window keeps its
    deferral and the plan's version has advanced past where it stood.

    "On success the window's `window_start` and `window_end` are replaced, `crew_hours` is
    recomputed from the new duration and crew size, the status moves `DEFERRED → SCHEDULED`
    (or remains `SCHEDULED` when the window had never been deferred), and the window's
    `version` is incremented by 1; `deferral_count` is not decremented."

    Design: Difficulty/compensating_invariant/nitrogen_ledger_returns_to_its_exact_value_after_defer_and_reschedule
    """
    env = build_two_task_plan_environment(
        nitrogen_budget_lb=8.00, schedule_first=True, schedule_second=True
    )
    version_before = get_plan(env.plan["id"])["version"]
    assert_nitrogen_ledgers(get_turf_area(env.green7["id"]), 0.000, 0.850)

    declare_weather_event(
        env.course["id"], WeatherEventType.HEAVY_RAIN.value, "2026-08-12T06:00:00Z"
    )
    assert_nitrogen_ledgers(get_turf_area(env.green7["id"]), 0.000, 0.850)

    reschedule_maintenance_window(
        env.window1["id"], "2026-08-15T05:00:00Z", "2026-08-15T07:00:00Z"
    )

    assert_maintenance_window(
        get_maintenance_window(env.window1["id"]),
        status=WindowStatus.SCHEDULED.value,
        deferral_count=1,
    )
    assert get_plan(env.plan["id"])["version"] > version_before
    assert_nitrogen_ledgers(get_turf_area(env.green7["id"]), 0.000, 0.850)


# --------------------------------------------------------------------------
# Withdrawn water: two ledgers and one derived posture, all unwound
# --------------------------------------------------------------------------
def test_completing_the_run_debits_both_ledgers_and_restricts_the_course():
    """682.0 gallons against an 800 gallon allocation is 85.25 percent, so both ledgers
    carry the withdrawal and the posture tightens onto the station.

    "The station's `withdrawn_today_gal` is recomputed as the sum of `volume_gal` over that
    station's runs in status `COMPLETED` whose `window_start` calendar date equals the
    logical clock's calendar date, and the station's `version` is incremented by 1."

    Design: Difficulty/compensating_invariant/water_ledger_and_posture_unwind_exactly_on_run_reversal
    """
    course, station, run = _eight_hundred_gallon_course_with_a_full_days_run()

    assert_irrigation_run(run, allotted_gal=682.0, flow_gpm=11.37, volume_gal=0)
    assert_1dp(get_course(course["id"])["water_used_gal"], 0)

    completed = complete_irrigation_run(run["id"])
    assert_1dp(completed["volume_gal"], 682.0)
    assert_water_ledgers(
        get_course(course["id"]), get_pump_station(station["id"]), 682.0, 682.0
    )
    assert get_course(course["id"])["water_posture"] == WaterPosture.RESTRICTED.value
    assert (
        get_pump_station(station["id"])["status"] == PumpStationStatus.RESTRICTED.value
    )


def test_reversing_the_run_restores_both_ledgers_and_reopens_the_course():
    """The reversal zeroes the delivered volume, returns both ledgers to 0.0 and relaxes
    the posture and the station together, while the authorised allotment is left alone.

    "Because the recomputed figure is smaller, the re-derivation here typically relaxes
    rather than tightens — `SUSPENDED → RESTRICTED`, `SUSPENDED → OPEN`, or
    `RESTRICTED → OPEN` — restoring restricted stations to `ONLINE`."

    Design: Difficulty/compensating_invariant/water_ledger_and_posture_unwind_exactly_on_run_reversal
    """
    course, station, run = _eight_hundred_gallon_course_with_a_full_days_run()
    complete_irrigation_run(run["id"])

    reversed_run = reverse_irrigation_run(
        run["id"], reversal_note="meter fault, withdrawal never happened"
    )

    assert_irrigation_run(
        reversed_run,
        status=IrrigationRunStatus.REVERSED.value,
        volume_gal=0,
        allotted_gal=682.0,
    )
    assert_water_ledgers(
        get_course(course["id"]), get_pump_station(station["id"]), 0.0, 0.0
    )
    assert get_course(course["id"])["water_posture"] == WaterPosture.OPEN.value
    assert get_pump_station(station["id"])["status"] == PumpStationStatus.ONLINE.value
    assert_1dp(get_irrigation_run(run["id"])["allotted_gal"], 682.0)


# --------------------------------------------------------------------------
# The engine-hour meter: conserved while the overdue term is reset
# --------------------------------------------------------------------------
def test_the_service_conserves_the_meter_while_clearing_the_overdue_term():
    """4500.0 hours stand on the meter before and after the service; only
    `hours_since_service` resets, taking the scores from 81.8 and 85.7 to 61.8 and 65.7.

    "The service sets `engine_hours_at_last_service` to the current `engine_hours`, drives
    `hours_since_service` to 0, recomputes both replacement scores and the replacement
    flag, moves the unit `DOWN_FOR_SERVICE → IN_SERVICE`, and increments its `version` by
    1."

    Design: Difficulty/compensating_invariant/engine_hour_meter_is_conserved_across_a_service
    """
    unit, logged = _triplex_down_for_service_at_forty_five_hundred_hours()

    assert_equipment_unit(
        logged,
        status=EquipmentStatus.DOWN_FOR_SERVICE.value,
        engine_hours=4500.0,
        hours_since_service=300.0,
        engine_hours_at_last_service=4200.0,
    )
    assert_replacement_scores(logged, 81.8, 85.7, True)

    serviced = service_equipment_unit(
        unit["id"], service_note="500 hour PM, blades reground"
    )

    assert_1dp(serviced["engine_hours"], 4500.0)
    assert_1dp(serviced["hours_since_service"], 0.0)
    assert_1dp(serviced["engine_hours_at_last_service"], 4500.0)
    assert_replacement_scores(serviced, 61.8, 65.7, False)
    assert serviced["status"] == EquipmentStatus.IN_SERVICE.value
    assert serviced["version"] == 4


def test_a_second_service_on_the_returned_unit_is_refused():
    """The compensation happens once: with the unit back `IN_SERVICE` a duplicate work
    order answers 409 `ERR_EQUIPMENT_STATE_INVALID` and the meter is untouched.

    "The unit must be `DOWN_FOR_SERVICE`, else `ERR_EQUIPMENT_STATE_INVALID`."

    Design: Difficulty/compensating_invariant/engine_hour_meter_is_conserved_across_a_service
    """
    unit, _logged = _triplex_down_for_service_at_forty_five_hundred_hours()
    service_equipment_unit(unit["id"], service_note="500 hour PM, blades reground")

    refused = api_client.service_equipment_unit(
        unit["id"], TECH_HEADERS, service_payload("duplicate work order")
    )
    validate_error(refused, ERR_EQUIPMENT_STATE_INVALID, 409)

    unchanged = get_equipment_unit(unit["id"])
    assert_equipment_unit(
        unchanged,
        expected_version=4,
        status=EquipmentStatus.IN_SERVICE.value,
        engine_hours=4500.0,
        hours_since_service=0.0,
    )
    assert_replacement_scores(unchanged, 61.8, 65.7, False)
