"""Four requests that each break two rules at once, and the four rules that win: the
buffer zone over licence category, the re-entry interval over play occupancy, plan
lifecycle over the nitrogen budget, and pump hydraulics over the annual allocation."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_BUFFER_ZONE_VIOLATION,
    ERR_LICENSE_CATEGORY_MISMATCH,
    ERR_NITROGEN_BUDGET_EXCEEDED,
    ERR_PLAN_STATE_INVALID,
    ERR_PUMP_FLOW_CAPACITY,
    ERR_REI_ACTIVE,
    ERR_WATER_ALLOCATION_EXCEEDED,
    ERR_WINDOW_CONFLICTS_PLAY,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_instant,
    assert_maintenance_window,
    assert_plan,
    assert_total_count,
    assert_turf_area,
)
from test_helpers.factories import (
    MOWING,
    STORM_CLEANUP,
    application_payload,
    irrigation_run_payload,
    maintenance_window_payload,
    schedule_task_payload,
)
from test_helpers.fixtures import (
    approve_plan,
    create_applicator,
    create_course,
    create_green,
    create_irrigation_run,
    create_maintenance_window,
    create_play_event,
    create_plan,
    create_plan_task,
    create_product,
    create_pump_station,
    create_turf_area,
    get_course,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_pump_station,
    get_turf_area,
    list_applications,
    list_irrigation_runs,
    list_maintenance_windows,
    record_application,
    set_clock,
    submit_plan,
)
from test_helpers.test_users import AGRO_HEADERS, make_applicator_headers
from test_helpers.types import (
    AreaType,
    LicenseCategory,
    PlanStatus,
    PlanTaskStatus,
    PlayEventType,
    SoilType,
    SourceType,
)


def _aquatic_licence_against_a_fifty_foot_buffer():
    """A CAT_7_AQUATIC applicator, a CAT_3_TURF product with a 50 ft buffer, and a green
    only 40 ft from water, so both the buffer rule and the category rule are broken."""
    set_clock("2026-08-01T06:00:00Z")
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    wren = create_applicator(
        full_name="Wren Alvarez",
        license_number="OR-CAT7-33003",
        license_category=LicenseCategory.CAT_7_AQUATIC.value,
        license_expires_on="2027-06-30",
    )
    product = create_product(
        trade_name="Greenside WDG",
        epa_reg_no="4321-99",
        requires_license_category=LicenseCategory.CAT_3_TURF.value,
        rei_hours=12,
        min_buffer_ft=50,
        max_wind_speed_mph=15,
        posting_required=True,
        nitrogen_pct=0,
    )
    return course, green7, wren, product


def _rei_interval_overlapping_a_shotgun_start():
    """A 24 hour re-entry interval on hole 7 that runs until 2026-08-11T06:00:00Z, and a
    shotgun start that occupies every hole from 05:00Z to 10:00Z that same morning."""
    set_clock("2026-08-10T06:00:00Z")
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    dana = create_applicator()
    fungicide = create_product(
        trade_name="Fairway Guard SC",
        epa_reg_no="1234-56",
        rei_hours=24,
        min_buffer_ft=25,
        max_wind_speed_mph=12,
        posting_required=True,
        nitrogen_pct=0,
    )
    record_application(
        green7["id"], fungicide["id"], dana["id"], "2026-08-10T06:00:00Z",
        rate_lb_per_acre=200, wind_speed_mph=5, distance_to_water_ft=40,
    )
    shotgun = create_play_event(
        course["id"],
        event_type=PlayEventType.SHOTGUN_START.value,
        start_at="2026-08-11T05:00:00Z",
        end_at="2026-08-11T10:00:00Z",
        holes_in_play=18,
        field_size=144,
    )
    return course, green7, shotgun


def _submitted_plan_over_a_four_pound_budget():
    """A 4.00 lb budget carrying a single 4.68 lb commitment, left in `SUBMITTED`, with a
    window waiting inside the task's planned interval."""
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=4.0)
    task = create_plan_task(plan["id"], green7["id"], nitrogen_lb_per_1000=0.85)
    window = create_maintenance_window(
        course["id"], green7["id"], "FERTILITY",
        "2026-08-12T05:00:00Z", "2026-08-12T07:00:00Z",
    )
    submitted = submit_plan(plan["id"])
    return course, green7, plan, task, window, submitted


def _fifty_gpm_station_with_one_run_already_booked():
    """A 50 gpm station on a 5000 gal allocation, already carrying a 2.84 gpm run over
    04:00Z to 05:00Z, so a 134.33 gpm fairway run in the same interval cannot fit."""
    course = create_course(annual_water_allocation_gal=5000)
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
        max_flow_gpm=50,
        max_concurrent_zones=2,
        daily_withdrawal_cap_gal=10000,
    )
    run_a = create_irrigation_run(
        station["id"], green7["id"],
        "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 5,
        expected_pump_station_version=station["version"],
    )
    return course, green7, fairway7, station, run_a


# --------------------------------------------------------------------------
# Business safety (30) beats business referential integrity (35)
# --------------------------------------------------------------------------
def test_buffer_zone_violation_is_reported_instead_of_the_licence_mismatch():
    """A 40 ft swath under a 50 ft buffer, sprayed on an unauthorised licence category,
    answers 422 `ERR_BUFFER_ZONE_VIOLATION` and records nothing.

    "When one request violates two or more rules, the rule with the numerically smallest
    priority determines the response and no later rule's error is reported."

    Design: Difficulty/priority_pair_validation_conflict/buffer_zone_safety_outranks_license_category_referential
    """
    _course, green7, wren, product = _aquatic_licence_against_a_fifty_foot_buffer()

    refused = api_client.create_application(
        application_payload(
            green7["id"], product["id"], wren["id"], "2026-08-01T06:00:00Z",
            rate_lb_per_acre=100, wind_speed_mph=5, distance_to_water_ft=40,
        ),
        make_applicator_headers(wren["id"]),
    )
    validate_error(refused, ERR_BUFFER_ZONE_VIOLATION, 422)

    _rows, meta = list_applications(turf_area_id=green7["id"])
    assert_total_count(meta, 0)
    assert_turf_area(
        get_turf_area(green7["id"]),
        nitrogen_applied_lb_per_1000_ytd=0.000,
        rei_expires_at=None,
    )


def test_the_licence_category_rule_does_fire_once_the_buffer_is_satisfied():
    """The same applicator and product on a green 60 ft from water clears the buffer and
    then answers 422 `ERR_LICENSE_CATEGORY_MISMATCH`, which proves the suppressed
    condition was genuinely broken in the conflict case.

    "Licence **category** authority is then checked, and it is a distinct rule from
    licence validity: `CAT_3_AND_7` authorises both `CAT_3_TURF` and `CAT_7_AQUATIC`
    products, `CAT_3_TURF` authorises only `CAT_3_TURF` products, and `CAT_7_AQUATIC`
    authorises only `CAT_7_AQUATIC` products."

    Design: Difficulty/priority_pair_validation_conflict/buffer_zone_safety_outranks_license_category_referential
    """
    course, _green7, wren, product = _aquatic_licence_against_a_fifty_foot_buffer()
    far_green = create_green(
        course["id"], hole_number=12, area_sq_ft=4300, distance_to_water_ft=60
    )

    refused = api_client.create_application(
        application_payload(
            far_green["id"], product["id"], wren["id"], "2026-08-01T06:00:00Z",
            rate_lb_per_acre=100, wind_speed_mph=5, distance_to_water_ft=60,
        ),
        make_applicator_headers(wren["id"]),
    )
    validate_error(refused, ERR_LICENSE_CATEGORY_MISMATCH, 422)

    _rows, meta = list_applications(turf_area_id=far_green["id"])
    assert_total_count(meta, 0)


# --------------------------------------------------------------------------
# Business safety (32) beats temporal geometry (40)
# --------------------------------------------------------------------------
def test_running_reentry_interval_is_reported_instead_of_the_play_conflict():
    """A mowing window at 05:30Z on 2026-08-11 sits inside both the re-entry interval and
    the shotgun occupancy, and the crew-safety rule answers 409 `ERR_REI_ACTIVE`.

    "Fourth, a restricted-entry interval still running on the area blocks the booking:
    unless the task class is `STORM_CLEANUP`, `window_start` must be at or after the
    area's `rei_expires_at`, and a violation is `ERR_REI_ACTIVE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/rei_safety_outranks_play_conflict_temporal
    """
    course, green7, _shotgun = _rei_interval_overlapping_a_shotgun_start()

    refused = api_client.create_maintenance_window(
        maintenance_window_payload(
            course["id"], green7["id"], MOWING,
            "2026-08-11T05:30:00Z", "2026-08-11T05:45:00Z", crew_size=3,
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_REI_ACTIVE, 409)

    _rows, meta = list_maintenance_windows(turf_area_id=green7["id"])
    assert_total_count(meta, 0)
    assert_instant(
        get_turf_area(green7["id"])["rei_expires_at"], "2026-08-11T06:00:00Z"
    )


def test_the_play_conflict_surfaces_for_the_one_task_class_exempt_from_reentry():
    """Storm cleanup is exempt from the re-entry gate, so the very same interval then
    answers `ERR_WINDOW_CONFLICTS_PLAY`, proving the play occupancy was also breached.

    "Second, the window must not collide with play on its hole, using the half-open
    geometry with the 30-minute clearance buffer and the 12-minute hole pace of §2.11
    against play events in `SCHEDULED` or `DELAYED`; a collision is
    `ERR_WINDOW_CONFLICTS_PLAY`."

    Design: Difficulty/priority_pair_validation_conflict/rei_safety_outranks_play_conflict_temporal
    """
    course, green7, _shotgun = _rei_interval_overlapping_a_shotgun_start()

    refused = api_client.create_maintenance_window(
        maintenance_window_payload(
            course["id"], green7["id"], STORM_CLEANUP,
            "2026-08-11T05:30:00Z", "2026-08-11T05:45:00Z", crew_size=3,
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_WINDOW_CONFLICTS_PLAY, 409)

    _rows, meta = list_maintenance_windows(turf_area_id=green7["id"])
    assert_total_count(meta, 0)


# --------------------------------------------------------------------------
# State (17) beats fiscal limits (51)
# --------------------------------------------------------------------------
def test_submitted_plan_is_reported_instead_of_the_budget_overrun():
    """Binding a 4.68 lb task against a 4.00 lb budget on a plan still in `SUBMITTED`
    answers 409 `ERR_PLAN_STATE_INVALID` and leaves every row untouched.

    "Once a plan is `ACTIVE`, its tasks may be bound to crew windows."

    Design: Difficulty/priority_pair_validation_conflict/plan_state_outranks_nitrogen_budget_fiscal
    """
    _course, _green7, plan, task, window, submitted = (
        _submitted_plan_over_a_four_pound_budget()
    )

    refused = api_client.schedule_plan_task(
        task["id"],
        schedule_task_payload(window["id"], submitted["version"]),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_PLAN_STATE_INVALID, 409)

    reread_task = get_plan_task(task["id"])
    assert reread_task["status"] == PlanTaskStatus.PLANNED.value
    assert_2dp(reread_task["commitment_lb"], 4.68)
    assert_plan(
        get_plan(plan["id"]),
        expected_version=submitted["version"],
        status=PlanStatus.SUBMITTED.value,
        committed_nitrogen_lb=0.00,
    )
    assert_maintenance_window(get_maintenance_window(window["id"]), plan_task_id=None)


def test_the_budget_overrun_surfaces_once_the_plan_reaches_active():
    """Approving the plan clears the lifecycle gate, and the same binding then answers
    422 `ERR_NITROGEN_BUDGET_EXCEEDED`, so both rules were genuinely broken.

    "and the resulting committed total must not exceed the plan's `nitrogen_budget_lb`,
    else `ERR_NITROGEN_BUDGET_EXCEEDED`"

    Design: Difficulty/priority_pair_validation_conflict/plan_state_outranks_nitrogen_budget_fiscal
    """
    _course, _green7, plan, task, window, submitted = (
        _submitted_plan_over_a_four_pound_budget()
    )

    active = approve_plan(plan["id"], submitted["version"])
    assert active["status"] == PlanStatus.ACTIVE.value

    refused = api_client.schedule_plan_task(
        task["id"],
        schedule_task_payload(window["id"], active["version"]),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_NITROGEN_BUDGET_EXCEEDED, 422)

    assert get_plan_task(task["id"])["status"] == PlanTaskStatus.PLANNED.value
    assert_2dp(get_plan(plan["id"])["committed_nitrogen_lb"], 0.00)


# --------------------------------------------------------------------------
# Structural constraints (45) beat fiscal limits (50)
# --------------------------------------------------------------------------
def test_pump_flow_capacity_is_reported_instead_of_the_allocation_breach():
    """2.84 gpm already booked plus the new run's 134.33 gpm is 137.17 gpm against a
    50 gpm station, so the hydraulic limit answers 409 `ERR_PUMP_FLOW_CAPACITY`.

    "Flow capacity uses exactly that same intersecting set: add the `flow_gpm` values of
    those intersecting scheduled runs to the new run's `flow_gpm` and require the total
    not to exceed the station's `max_flow_gpm`, else `ERR_PUMP_FLOW_CAPACITY`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/pump_flow_constraint_outranks_water_allocation_fiscal
    """
    course, _green7, fairway7, station, run_a = (
        _fifty_gpm_station_with_one_run_already_booked()
    )

    assert_1dp(run_a["allotted_gal"], 170.5)
    assert_2dp(run_a["flow_gpm"], 2.84)

    pinned = get_pump_station(station["id"])
    refused = api_client.create_irrigation_run(
        irrigation_run_payload(
            station["id"], fairway7["id"],
            "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 10,
            pinned["version"],
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_PUMP_FLOW_CAPACITY, 409)

    _rows, meta = list_irrigation_runs(pump_station_id=station["id"])
    assert_total_count(meta, 1)
    assert_1dp(get_pump_station(station["id"])["withdrawn_today_gal"], 0)
    assert_1dp(get_course(course["id"])["water_used_gal"], 0)


def test_the_allocation_breach_surfaces_on_a_station_with_hydraulic_headroom():
    """The same 8060.0 gal fairway run on a 500 gpm station clears the flow ceiling and
    then answers 422 `ERR_WATER_ALLOCATION_EXCEEDED` against the 5000 gal allocation.

    "It is enforced as a separate check: for a station whose `source_type` is not
    `RECLAIMED`, the course's `water_used_gal` plus the new run's `allotted_gal` must not
    exceed the course's `annual_water_allocation_gal`, and a breach is
    `ERR_WATER_ALLOCATION_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/pump_flow_constraint_outranks_water_allocation_fiscal
    """
    course, _green7, fairway7, _station, _run_a = (
        _fifty_gpm_station_with_one_run_already_booked()
    )
    roomy = create_pump_station(
        course["id"],
        source_type=SourceType.WELL.value,
        max_flow_gpm=500,
        max_concurrent_zones=2,
        daily_withdrawal_cap_gal=10000,
    )

    refused = api_client.create_irrigation_run(
        irrigation_run_payload(
            roomy["id"], fairway7["id"],
            "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 10,
            roomy["version"],
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_WATER_ALLOCATION_EXCEEDED, 422)

    _rows, meta = list_irrigation_runs(pump_station_id=roomy["id"])
    assert_total_count(meta, 0)
    assert_1dp(get_course(course["id"])["water_used_gal"], 0)


def test_zone_capacity_is_not_what_refused_the_overlapping_fairway_run():
    """A second, low-flow run in the very same interval is admitted, so the station's two
    zones were never the obstacle — only the 50 gpm flow ceiling was.

    "Zone capacity is next: count the station's runs in status `SCHEDULED` whose half-open
    intervals intersect the new run's half-open interval per §2.11, add one for the new
    run, and require the result not to exceed `max_concurrent_zones`, else
    `ERR_PUMP_ZONE_CAPACITY` (HTTP 409); adjacent runs that merely touch endpoints are not
    counted."

    Design: Difficulty/priority_pair_validation_conflict/pump_flow_constraint_outranks_water_allocation_fiscal
    """
    course, _green7, fairway7, station, _run_a = (
        _fifty_gpm_station_with_one_run_already_booked()
    )
    small_green = create_green(
        course["id"], hole_number=12, area_sq_ft=1000, distance_to_water_ft=200
    )

    refused = api_client.create_irrigation_run(
        irrigation_run_payload(
            station["id"], fairway7["id"],
            "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 10,
            station["version"],
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_PUMP_FLOW_CAPACITY, 409)

    admitted = create_irrigation_run(
        station["id"], small_green["id"],
        "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 1,
        expected_pump_station_version=get_pump_station(station["id"])["version"],
    )
    assert_1dp(admitted["allotted_gal"], 6.2)
    assert_2dp(admitted["flow_gpm"], 0.10)

    _rows, meta = list_irrigation_runs(pump_station_id=station["id"])
    assert_total_count(meta, 2)
    assert_1dp(get_pump_station(station["id"])["withdrawn_today_gal"], 0)
    assert_1dp(get_course(course["id"])["water_used_gal"], 0)
