"""Setup builders and pytest fixtures.

Every test starts against an empty database whose logical clock reads
2026-08-01T00:00:00Z, so all preconditions are built here through the same
endpoints the PRD publishes.  Each builder validates the write it performs and
returns the created resource's data, so a test can capture ids and versions
without restating envelope handling.  Builders never assert business outcomes:
tests that expect a rejection call the client directly.
"""

from types import SimpleNamespace

import pytest

from prd_bench_local_runner.testing import validate_paginated, validate_success

from . import factories as f
from .api_client import api_client
from .constants import CLOCK_STARTUP
from .test_users import (
    AGRO_HEADERS,
    SUPER_HEADERS,
    TECH_HEADERS,
    TOURN_HEADERS,
    make_applicator_headers,
)
from .types import AreaType, PlayEventType, SoilType, UnitType


def _created(response):
    return validate_success(response, 201)


def _ok(response):
    return validate_success(response, 200)


# --------------------------------------------------------------------------
# The logical clock (PRD §2.5)
# --------------------------------------------------------------------------
def set_clock(current_utc, headers=SUPER_HEADERS):
    """Move the logical clock; "setting the clock does not itself mutate"."""
    return _ok(api_client.set_clock(current_utc, headers))


def reset_clock():
    return set_clock(CLOCK_STARTUP)


# --------------------------------------------------------------------------
# Courses (PRD §3.1)
# --------------------------------------------------------------------------
def create_course(headers=SUPER_HEADERS, **kwargs):
    return _created(api_client.create_course(f.course_payload(**kwargs), headers))


def get_course(course_id, headers=SUPER_HEADERS):
    return _ok(api_client.get_course(course_id, headers))


def revise_water_allocation(course_id, headers=SUPER_HEADERS, **kwargs):
    return _ok(
        api_client.revise_water_allocation(
            course_id, f.water_allocation_payload(**kwargs), headers
        )
    )


def get_water_assessment(course_id, headers=SUPER_HEADERS):
    return _ok(api_client.get_water_assessment(course_id, headers))


def list_course_weather_events(course_id, headers=SUPER_HEADERS, **params):
    return validate_paginated(
        api_client.list_course_weather_events(course_id, headers, params or None)
    )


# --------------------------------------------------------------------------
# Turf areas (PRD §3.2)
# --------------------------------------------------------------------------
def create_turf_area(course_id, headers=SUPER_HEADERS, **kwargs):
    return _created(
        api_client.create_turf_area(f.turf_area_payload(course_id, **kwargs), headers)
    )


def create_green(course_id, hole_number=7, area_sq_ft=5500, **kwargs):
    """A USGA sand green, the shape most of the agronomic arithmetic is stated on."""
    return create_turf_area(
        course_id,
        area_type=AreaType.GREEN.value,
        hole_number=hole_number,
        area_sq_ft=area_sq_ft,
        soil_type=SoilType.SAND_USGA.value,
        **kwargs,
    )


def get_turf_area(turf_area_id, headers=SUPER_HEADERS):
    return _ok(api_client.get_turf_area(turf_area_id, headers))


def list_turf_areas(headers=SUPER_HEADERS, **params):
    return validate_paginated(api_client.list_turf_areas(headers, params or None))


def list_playability_readings(turf_area_id, headers=SUPER_HEADERS, **params):
    return validate_paginated(
        api_client.list_turf_area_playability_readings(
            turf_area_id, headers, params or None
        )
    )


# --------------------------------------------------------------------------
# Agronomic plans and their tasks (PRD §3.3)
# --------------------------------------------------------------------------
def create_plan(course_id, headers=AGRO_HEADERS, **kwargs):
    return _created(api_client.create_plan(f.plan_payload(course_id, **kwargs), headers))


def get_plan(plan_id, headers=AGRO_HEADERS):
    return _ok(api_client.get_plan(plan_id, headers))


def list_plans(headers=AGRO_HEADERS, **params):
    return validate_paginated(api_client.list_plans(headers, params or None))


def create_plan_task(plan_id, turf_area_id, headers=AGRO_HEADERS, **kwargs):
    return _created(
        api_client.create_plan_task(
            f.plan_task_payload(plan_id, turf_area_id, **kwargs), headers
        )
    )


def get_plan_task(task_id, headers=AGRO_HEADERS):
    return _ok(api_client.get_plan_task(task_id, headers))


def list_plan_tasks(headers=AGRO_HEADERS, **params):
    return validate_paginated(api_client.list_plan_tasks(headers, params or None))


def submit_plan(plan_id, headers=AGRO_HEADERS):
    return _ok(api_client.submit_plan(plan_id, headers))


def return_plan(plan_id, return_note=None, headers=SUPER_HEADERS):
    return _ok(
        api_client.return_plan(plan_id, f.return_plan_payload(return_note), headers)
    )


def approve_plan(plan_id, expected_plan_version, headers=SUPER_HEADERS):
    return _ok(
        api_client.approve_plan(
            plan_id, f.approve_plan_payload(expected_plan_version), headers
        )
    )


def schedule_plan_task(
    task_id, maintenance_window_id, expected_plan_version, headers=AGRO_HEADERS
):
    return _ok(
        api_client.schedule_plan_task(
            task_id,
            f.schedule_task_payload(maintenance_window_id, expected_plan_version),
            headers,
        )
    )


def build_approved_plan(
    course_id,
    tasks=(),
    nitrogen_budget_lb=40.00,
    plan_year=2026,
    submitter=AGRO_HEADERS,
    approver=SUPER_HEADERS,
):
    """A plan carrying the given tasks, submitted and then approved so it is ACTIVE.

    `tasks` is a sequence of keyword dicts for `create_plan_task`, each naming at
    least a `turf_area_id`.  The returned namespace exposes the plan as it stands
    after approval, plus every task re-read at that same moment.
    """
    plan = create_plan(
        course_id,
        headers=submitter,
        plan_year=plan_year,
        nitrogen_budget_lb=nitrogen_budget_lb,
    )
    created = [
        create_plan_task(plan["id"], headers=submitter, **spec) for spec in tasks
    ]
    submitted = submit_plan(plan["id"], headers=submitter)
    approved = approve_plan(plan["id"], submitted["version"], headers=approver)
    return SimpleNamespace(
        plan=approved,
        draft=plan,
        submitted=submitted,
        tasks=[get_plan_task(task["id"]) for task in created],
    )


# --------------------------------------------------------------------------
# Applicators and product labels (PRD §3.4)
# --------------------------------------------------------------------------
def create_applicator(headers=SUPER_HEADERS, **kwargs):
    return _created(api_client.create_applicator(f.applicator_payload(**kwargs), headers))


def get_applicator(applicator_id, headers=SUPER_HEADERS):
    return _ok(api_client.get_applicator(applicator_id, headers))


def list_applicators(headers=SUPER_HEADERS, **params):
    return validate_paginated(api_client.list_applicators(headers, params or None))


def create_product(headers=SUPER_HEADERS, **kwargs):
    return _created(
        api_client.create_pesticide_product(f.product_payload(**kwargs), headers)
    )


def get_product(product_id, headers=SUPER_HEADERS):
    return _ok(api_client.get_pesticide_product(product_id, headers))


def list_products(headers=SUPER_HEADERS, **params):
    return validate_paginated(api_client.list_pesticide_products(headers, params or None))


def record_application(
    turf_area_id, product_id, applicator_id, applied_at, headers=None, **kwargs
):
    """Record an application as the applicator named in the payload."""
    return _created(
        api_client.create_application(
            f.application_payload(
                turf_area_id, product_id, applicator_id, applied_at, **kwargs
            ),
            headers or make_applicator_headers(applicator_id),
        )
    )


def get_application(application_id, headers=SUPER_HEADERS):
    return _ok(api_client.get_application(application_id, headers))


def list_applications(headers=SUPER_HEADERS, **params):
    return validate_paginated(api_client.list_applications(headers, params or None))


def verify_application(application_id, verifier_applicator_id):
    """Verify as a second applicator, which is what segregation of duties requires."""
    return _ok(
        api_client.verify_application(
            application_id, make_applicator_headers(verifier_applicator_id)
        )
    )


def void_application(application_id, void_reason, headers=SUPER_HEADERS):
    return _ok(
        api_client.void_application(application_id, f.void_payload(void_reason), headers)
    )


def release_posting(application_id, applicator_id):
    return _ok(
        api_client.release_application_posting(
            application_id, make_applicator_headers(applicator_id)
        )
    )


# --------------------------------------------------------------------------
# Irrigation (PRD §3.5)
# --------------------------------------------------------------------------
def create_pump_station(course_id, headers=SUPER_HEADERS, **kwargs):
    return _created(
        api_client.create_pump_station(f.pump_station_payload(course_id, **kwargs), headers)
    )


def get_pump_station(pump_station_id, headers=SUPER_HEADERS):
    return _ok(api_client.get_pump_station(pump_station_id, headers))


def list_pump_stations(headers=SUPER_HEADERS, **params):
    return validate_paginated(api_client.list_pump_stations(headers, params or None))


def set_pump_station_status(pump_station_id, status, headers=SUPER_HEADERS):
    return _ok(api_client.set_pump_station_status(pump_station_id, status, headers))


def create_irrigation_run(
    pump_station_id,
    turf_area_id,
    window_start,
    window_end,
    target_moisture_deficit_pct,
    expected_pump_station_version=None,
    headers=AGRO_HEADERS,
    **kwargs,
):
    """Schedule a run, pinning the pump version the caller last observed.

    When no version is supplied the station is re-read first, which is what a
    client that has just been told its pin was stale would do.
    """
    if expected_pump_station_version is None:
        expected_pump_station_version = get_pump_station(pump_station_id)["version"]
    return _created(
        api_client.create_irrigation_run(
            f.irrigation_run_payload(
                pump_station_id,
                turf_area_id,
                window_start,
                window_end,
                target_moisture_deficit_pct,
                expected_pump_station_version,
                **kwargs,
            ),
            headers,
        )
    )


def get_irrigation_run(run_id, headers=AGRO_HEADERS):
    return _ok(api_client.get_irrigation_run(run_id, headers))


def list_irrigation_runs(headers=AGRO_HEADERS, **params):
    return validate_paginated(api_client.list_irrigation_runs(headers, params or None))


def complete_irrigation_run(run_id, actual_minutes=None, headers=AGRO_HEADERS):
    return _ok(
        api_client.complete_irrigation_run(
            run_id, headers, f.complete_run_payload(actual_minutes)
        )
    )


def reverse_irrigation_run(run_id, reversal_note=None, headers=SUPER_HEADERS):
    return _ok(
        api_client.reverse_irrigation_run(
            run_id, headers, f.reverse_run_payload(reversal_note)
        )
    )


# --------------------------------------------------------------------------
# Crew windows (PRD §3.6)
# --------------------------------------------------------------------------
def create_maintenance_window(
    course_id,
    turf_area_id,
    task_type,
    window_start,
    window_end,
    crew_size=3,
    headers=AGRO_HEADERS,
    **kwargs,
):
    return _created(
        api_client.create_maintenance_window(
            f.maintenance_window_payload(
                course_id,
                turf_area_id,
                task_type,
                window_start,
                window_end,
                crew_size=crew_size,
                **kwargs,
            ),
            headers,
        )
    )


def get_maintenance_window(window_id, headers=AGRO_HEADERS):
    return _ok(api_client.get_maintenance_window(window_id, headers))


def list_maintenance_windows(headers=AGRO_HEADERS, **params):
    return validate_paginated(api_client.list_maintenance_windows(headers, params or None))


def start_maintenance_window(window_id, headers=AGRO_HEADERS):
    return _ok(api_client.start_maintenance_window(window_id, headers))


def complete_maintenance_window(window_id, headers=AGRO_HEADERS):
    return _ok(api_client.complete_maintenance_window(window_id, headers))


def reschedule_maintenance_window(
    window_id, window_start, window_end, crew_size=None, headers=AGRO_HEADERS
):
    return _ok(
        api_client.reschedule_maintenance_window(
            window_id,
            f.reschedule_window_payload(window_start, window_end, crew_size),
            headers,
        )
    )


# --------------------------------------------------------------------------
# Play events and readings (PRD §3.7)
# --------------------------------------------------------------------------
def create_play_event(course_id, headers=TOURN_HEADERS, **kwargs):
    return _created(
        api_client.create_play_event(f.play_event_payload(course_id, **kwargs), headers)
    )


def create_tournament_round(
    course_id,
    start_at="2026-08-05T14:00:00Z",
    end_at="2026-08-05T19:00:00Z",
    holes_in_play=18,
    field_size=120,
    headers=TOURN_HEADERS,
):
    return create_play_event(
        course_id,
        headers=headers,
        event_type=PlayEventType.TOURNAMENT_ROUND.value,
        start_at=start_at,
        end_at=end_at,
        holes_in_play=holes_in_play,
        field_size=field_size,
    )


def get_play_event(event_id, headers=TOURN_HEADERS):
    return _ok(api_client.get_play_event(event_id, headers))


def list_play_events(headers=TOURN_HEADERS, **params):
    return validate_paginated(api_client.list_play_events(headers, params or None))


def certify_conditions(event_id, headers=TOURN_HEADERS):
    return _ok(api_client.certify_conditions(event_id, headers))


def create_playability_reading(turf_area_id, measured_at, headers=AGRO_HEADERS, **kwargs):
    return _created(
        api_client.create_playability_reading(
            f.playability_reading_payload(turf_area_id, measured_at, **kwargs), headers
        )
    )


# --------------------------------------------------------------------------
# The fleet (PRD §3.8)
# --------------------------------------------------------------------------
def create_equipment_unit(course_id, headers=TECH_HEADERS, **kwargs):
    return _created(
        api_client.create_equipment_unit(
            f.equipment_unit_payload(course_id, **kwargs), headers
        )
    )


def get_equipment_unit(unit_id, headers=TECH_HEADERS):
    return _ok(api_client.get_equipment_unit(unit_id, headers))


def list_equipment_units(headers=TECH_HEADERS, **params):
    return validate_paginated(api_client.list_equipment_units(headers, params or None))


def log_equipment_hours(unit_id, hours_added, headers=TECH_HEADERS):
    return _ok(api_client.log_equipment_hours(unit_id, hours_added, headers))


def service_equipment_unit(unit_id, service_note=None, headers=TECH_HEADERS):
    return _ok(
        api_client.service_equipment_unit(unit_id, headers, f.service_payload(service_note))
    )


def retire_equipment_unit(unit_id, replacement_unit_id=None, headers=SUPER_HEADERS):
    return _ok(
        api_client.retire_equipment_unit(
            unit_id, headers, f.retire_payload(replacement_unit_id)
        )
    )


# --------------------------------------------------------------------------
# Weather (PRD §3.9)
# --------------------------------------------------------------------------
def declare_weather_event(
    course_id,
    event_type,
    expected_clear_at,
    expected_course_version=None,
    headers=SUPER_HEADERS,
    **kwargs,
):
    """Declare an event, pinning the course version the caller last observed."""
    if expected_course_version is None:
        expected_course_version = get_course(course_id)["version"]
    return _created(
        api_client.create_weather_event(
            f.weather_event_payload(
                course_id,
                event_type,
                expected_clear_at,
                expected_course_version,
                **kwargs,
            ),
            headers,
        )
    )


def clear_weather_event(event_id, headers=SUPER_HEADERS):
    return _ok(api_client.clear_weather_event(event_id, headers))


# ==========================================================================
# Composite environments
# ==========================================================================
def build_course_with_green(
    annual_water_allocation_gal=100000,
    area_sq_ft=5500,
    distance_to_water_ft=40,
    **course_kwargs,
):
    """One course and one green on hole 7."""
    course = create_course(
        annual_water_allocation_gal=annual_water_allocation_gal, **course_kwargs
    )
    green = create_green(
        course["id"],
        hole_number=7,
        area_sq_ft=area_sq_ft,
        distance_to_water_ft=distance_to_water_ft,
    )
    return SimpleNamespace(course=course, green=green, green7=green)


def build_course_with_greens(
    annual_water_allocation_gal=100000, third_green=False, **course_kwargs
):
    """A course with the greens of holes 7 and 12, optionally hole 3 as well.

    Hole 7 sits 40 ft from water and hole 12 sits 200 ft away, so the same
    product label can be made to fail a buffer check on one and pass on the other.
    """
    course = create_course(
        annual_water_allocation_gal=annual_water_allocation_gal, **course_kwargs
    )
    green7 = create_green(
        course["id"], hole_number=7, area_sq_ft=5500, distance_to_water_ft=40
    )
    green12 = create_green(
        course["id"], hole_number=12, area_sq_ft=4300, distance_to_water_ft=200
    )
    green3 = (
        create_green(
            course["id"], hole_number=3, area_sq_ft=5000, distance_to_water_ft=150
        )
        if third_green
        else None
    )
    return SimpleNamespace(
        course=course, green7=green7, green12=green12, green3=green3
    )


def build_application_environment(
    annual_water_allocation_gal=100000, second_applicator=False, **product_kwargs
):
    """A course, two greens, a licensed applicator and one product label.

    A second applicator is available on request because verification requires a
    different applicator from the one who recorded the application.
    """
    env = build_course_with_greens(
        annual_water_allocation_gal=annual_water_allocation_gal
    )
    env.applicator = create_applicator()
    env.applicator_headers = make_applicator_headers(env.applicator["id"])
    env.second_applicator = (
        create_applicator(
            full_name="Miguel Ortiz",
            license_number="OR-CAT37-22002",
            license_category="CAT_3_AND_7",
            license_expires_on="2028-03-31",
        )
        if second_applicator
        else None
    )
    env.product = create_product(**product_kwargs)
    return env


def build_irrigation_environment(
    annual_water_allocation_gal=100000,
    area_sq_ft=5500,
    max_flow_gpm=300,
    max_concurrent_zones=2,
    daily_withdrawal_cap_gal=10000,
    **station_kwargs,
):
    """A course, a green and a pump station whose version is captured for pinning."""
    env = build_course_with_green(
        annual_water_allocation_gal=annual_water_allocation_gal,
        area_sq_ft=area_sq_ft,
    )
    env.station = create_pump_station(
        env.course["id"],
        max_flow_gpm=max_flow_gpm,
        max_concurrent_zones=max_concurrent_zones,
        daily_withdrawal_cap_gal=daily_withdrawal_cap_gal,
        **station_kwargs,
    )
    env.station_version = env.station["version"]
    return env


def build_fleet_environment(**unit_kwargs):
    """A course and one triplex greens mower."""
    course = create_course()
    unit = create_equipment_unit(
        course["id"], unit_type=UnitType.TRIPLEX_GREENS_MOWER.value, **unit_kwargs
    )
    return SimpleNamespace(course=course, unit=unit)


def build_tournament_environment(
    start_at="2026-08-05T14:00:00Z",
    end_at="2026-08-05T19:00:00Z",
    field_size=120,
    holes_in_play=18,
):
    """A course with three greens and a tournament round posted over them."""
    env = build_course_with_greens(third_green=True)
    env.event = create_tournament_round(
        env.course["id"],
        start_at=start_at,
        end_at=end_at,
        holes_in_play=holes_in_play,
        field_size=field_size,
    )
    env.greens = [env.green7, env.green12, env.green3]
    return env


def build_two_task_plan_environment(
    nitrogen_budget_lb=8.00,
    first_nitrogen=0.85,
    second_nitrogen=0.75,
    schedule_first=False,
    schedule_second=False,
):
    """An active plan with two fertility tasks and a fertility window for each.

    The two commitments are the pair whose ledger has to be kept at the plan's own
    scale: 0.85 lb/1000 on a 5500 sq ft green and 0.75 lb/1000 on a 4300 sq ft one.
    """
    env = build_course_with_greens()
    plan_env = build_approved_plan(
        env.course["id"],
        tasks=(
            {"turf_area_id": env.green7["id"], "nitrogen_lb_per_1000": first_nitrogen},
            {"turf_area_id": env.green12["id"], "nitrogen_lb_per_1000": second_nitrogen},
        ),
        nitrogen_budget_lb=nitrogen_budget_lb,
    )
    env.plan = plan_env.plan
    env.tasks = plan_env.tasks
    env.task1, env.task2 = plan_env.tasks[0], plan_env.tasks[1]
    env.window1 = create_maintenance_window(
        env.course["id"],
        env.green7["id"],
        f.FERTILITY,
        "2026-08-12T05:00:00Z",
        "2026-08-12T07:00:00Z",
    )
    env.window2 = create_maintenance_window(
        env.course["id"],
        env.green12["id"],
        f.FERTILITY,
        "2026-08-13T05:00:00Z",
        "2026-08-13T07:00:00Z",
    )
    if schedule_first:
        env.task1 = schedule_plan_task(
            env.task1["id"], env.window1["id"], get_plan(env.plan["id"])["version"]
        )
    if schedule_second:
        env.task2 = schedule_plan_task(
            env.task2["id"], env.window2["id"], get_plan(env.plan["id"])["version"]
        )
    env.plan = get_plan(env.plan["id"])
    return env


# ==========================================================================
# Fixtures
# ==========================================================================
@pytest.fixture
def client():
    return api_client


@pytest.fixture
def clock():
    """Move the logical clock, returning the mover so a test can step time."""
    return set_clock


@pytest.fixture
def course():
    return create_course()


@pytest.fixture
def course_with_green():
    return build_course_with_green()


@pytest.fixture
def course_with_greens():
    return build_course_with_greens()


@pytest.fixture
def course_with_three_greens():
    return build_course_with_greens(third_green=True)


@pytest.fixture
def application_env():
    return build_application_environment()


@pytest.fixture
def irrigation_env():
    return build_irrigation_environment()


@pytest.fixture
def fleet_env():
    return build_fleet_environment()


@pytest.fixture
def tournament_env():
    return build_tournament_environment()


@pytest.fixture
def two_task_plan_env():
    return build_two_task_plan_environment()
