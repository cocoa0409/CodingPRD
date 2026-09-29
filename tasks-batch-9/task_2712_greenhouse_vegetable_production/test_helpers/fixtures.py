"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because each test runs against an empty database. Setup calls go through the lenient
validator so a broken precondition reports as a setup failure rather than as a
confusing assertion failure inside the test body.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH
from .factories import (
    create_bio_control_release_payload,
    create_climate_strategy_payload,
    create_commitment_week_payload,
    create_crop_cycle_payload,
    create_drainage_reading_payload,
    create_fertigation_batch_payload,
    create_harvest_lot_payload,
    create_labor_task_payload,
    create_posture_override_payload,
    create_retail_program_payload,
    create_scout_worker_payload,
    create_scouting_observation_payload,
    create_variety_payload,
    create_worker_payload,
    create_zone_payload,
    grade_harvest_lot_payload,
)
from .test_users import (
    TEST_USERS,
    make_harvest_supervisor_headers,
    make_ipm_coordinator_headers,
    make_ipm_scout_headers,
    make_quality_inspector_headers,
)

GM = TEST_USERS["grower_manager_headers"]
IT = TEST_USERS["irrigation_tech_headers"]
QI = TEST_USERS["quality_inspector_headers"]


# ==========================================================================
# Logical clock
# ==========================================================================


def set_clock(current_utc: str = CLOCK_EPOCH) -> dict:
    """Set the server's logical clock. Before any call it reads 2026-08-01T00:00:00Z."""
    return get_success_data(
        api_client.set_current_utc({"current_utc": current_utc}, GM)
    )


# ==========================================================================
# Single-resource primitives
# ==========================================================================


def create_zone(**overrides) -> dict:
    return get_success_data(
        api_client.create_zone(create_zone_payload(**overrides), GM), 201
    )


def create_variety(**overrides) -> dict:
    return get_success_data(
        api_client.create_variety(create_variety_payload(**overrides), GM), 201
    )


def create_crop_cycle(zone_id: str, variety_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_crop_cycle(
            create_crop_cycle_payload(zone_id, variety_id, **overrides), GM
        ),
        201,
    )


def transition_crop_cycle(cycle_id: str, to_status: str, **extra) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(
        api_client.transition_crop_cycle(cycle_id, payload, GM), 200
    )


def create_worker(**overrides) -> dict:
    return get_success_data(
        api_client.create_worker(create_worker_payload(**overrides), GM), 201
    )


def create_scout_worker(**overrides) -> dict:
    return get_success_data(
        api_client.create_worker(create_scout_worker_payload(**overrides), GM), 201
    )


def create_harvest_worker(**overrides) -> dict:
    """An ACTIVE worker whose skill is HARVEST, usable as a HarvestSupervisor actor."""
    return create_worker(**overrides)


def create_labor_task(zone_id: str, crop_cycle_id: str, worker_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_labor_task(
            create_labor_task_payload(zone_id, crop_cycle_id, worker_id, **overrides),
            GM,
        ),
        201,
    )


def transition_labor_task(task_id: str, to_status: str, headers: Optional[Dict] = None, **extra) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(
        api_client.transition_labor_task(task_id, payload, headers or GM), 200
    )


def create_climate_strategy(zone_id: str, expected_zone_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_climate_strategy(
            create_climate_strategy_payload(zone_id, expected_zone_version, **overrides),
            GM,
        ),
        201,
    )


def record_climate_actuals(strategy_id: str, payload: dict) -> dict:
    return get_success_data(
        api_client.record_climate_actuals(strategy_id, payload, GM), 200
    )


def create_fertigation_batch(zone_id: str, crop_cycle_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fertigation_batch(
            create_fertigation_batch_payload(zone_id, crop_cycle_id, **overrides), IT
        ),
        201,
    )


def transition_fertigation_batch(batch_id: str, to_status: str, **extra) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(
        api_client.transition_fertigation_batch(batch_id, payload, IT), 200
    )


def create_drainage_reading(batch_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_drainage_reading(
            batch_id, create_drainage_reading_payload(**overrides), IT
        ),
        200,
    )


def file_observation(zone_id: str, crop_cycle_id: str, scout_worker_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_scouting_observation(
            create_scouting_observation_payload(zone_id, crop_cycle_id, **overrides),
            make_ipm_scout_headers(scout_worker_id),
        ),
        201,
    )


def request_release(zone_id: str, observation_id: str, scout_worker_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_bio_control_release(
            create_bio_control_release_payload(zone_id, observation_id, **overrides),
            make_ipm_scout_headers(scout_worker_id),
        ),
        201,
    )


def approve_release(release_id: str, coordinator_worker_id: str, **payload) -> dict:
    return get_success_data(
        api_client.approve_bio_control_release(
            release_id, dict(payload), make_ipm_coordinator_headers(coordinator_worker_id)
        ),
        200,
    )


def transition_release_as_coordinator(
    release_id: str, to_status: str, coordinator_worker_id: str, **extra
) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(
        api_client.transition_bio_control_release(
            release_id, payload, make_ipm_coordinator_headers(coordinator_worker_id)
        ),
        200,
    )


def transition_release_as_scout(
    release_id: str, to_status: str, scout_worker_id: str, **extra
) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(
        api_client.transition_bio_control_release(
            release_id, payload, make_ipm_scout_headers(scout_worker_id)
        ),
        200,
    )


def execute_release(release_id: str, scout_worker_id: str, **payload) -> dict:
    return get_success_data(
        api_client.execute_bio_control_release(
            release_id, dict(payload), make_ipm_scout_headers(scout_worker_id)
        ),
        200,
    )


def register_lot(crop_cycle_id: str, harvest_worker_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_harvest_lot(
            create_harvest_lot_payload(crop_cycle_id, **overrides),
            make_harvest_supervisor_headers(harvest_worker_id),
        ),
        201,
    )


def grade_lot(lot_id: str, harvest_worker_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.grade_harvest_lot(
            lot_id,
            grade_harvest_lot_payload(**overrides),
            make_harvest_supervisor_headers(harvest_worker_id),
        ),
        200,
    )


def regrade_lot(lot_id: str, harvest_worker_id: str, expected_lot_version: int, **overrides) -> dict:
    payload = grade_harvest_lot_payload(**overrides)
    payload["expected_lot_version"] = expected_lot_version
    return get_success_data(
        api_client.regrade_harvest_lot(
            lot_id, payload, make_harvest_supervisor_headers(harvest_worker_id)
        ),
        200,
    )


def cold_chain_event(
    lot_id: str, to_status: str, pulp_temp_c: float, inspector_user_id: Optional[str] = None
) -> dict:
    headers = (
        make_quality_inspector_headers(inspector_user_id) if inspector_user_id else QI
    )
    return get_success_data(
        api_client.create_cold_chain_event(
            lot_id, {"to_status": to_status, "pulp_temp_c": pulp_temp_c}, headers
        ),
        200,
    )


def create_retail_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_retail_program(create_retail_program_payload(**overrides), GM),
        201,
    )


def create_commitment_week(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_commitment_week(
            create_commitment_week_payload(program_id, **overrides), GM
        ),
        201,
    )


def run_allocation(week_start_date: str) -> List[dict]:
    return get_success_data(
        api_client.create_allocation_run({"week_start_date": week_start_date}, GM), 200
    )


def create_posture_override(zone_id: str, expected_zone_version: int, **overrides) -> dict:
    payload = create_posture_override_payload(**overrides)
    payload["expected_zone_version"] = expected_zone_version
    return get_success_data(
        api_client.create_posture_override(zone_id, payload, GM), 200
    )


def create_hive_placement(cycle_id: str, hive_count: int, placed_at: str) -> dict:
    return get_success_data(
        api_client.create_hive_placement(
            cycle_id, {"hive_count": hive_count, "placed_at": placed_at}, GM
        ),
        200,
    )


def create_pollination_check(
    cycle_id: str, observed_at: str, flower_visit_pct: float, hive_activity_count: int
) -> dict:
    return get_success_data(
        api_client.create_pollination_check(
            cycle_id,
            {
                "observed_at": observed_at,
                "flower_visit_pct": flower_visit_pct,
                "hive_activity_count": hive_activity_count,
            },
            GM,
        ),
        200,
    )


# ==========================================================================
# Readers
# ==========================================================================


def read_zone(zone_id: str) -> dict:
    return get_success_data(api_client.get_zone(zone_id, GM), 200)


def read_crop_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_crop_cycle(cycle_id, GM), 200)


def read_worker(worker_id: str) -> dict:
    return get_success_data(api_client.get_worker(worker_id, GM), 200)


def read_labor_task(task_id: str) -> dict:
    return get_success_data(api_client.get_labor_task(task_id, GM), 200)


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_harvest_lot(lot_id, GM), 200)


def read_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_fertigation_batch(batch_id, GM), 200)


def read_release(release_id: str) -> dict:
    return get_success_data(api_client.get_bio_control_release(release_id, GM), 200)


def read_climate_strategy(strategy_id: str) -> dict:
    return get_success_data(api_client.get_climate_strategy(strategy_id, GM), 200)


def read_program(program_id: str) -> dict:
    return get_success_data(api_client.get_retail_program(program_id, GM), 200)


def read_week(week_id: str) -> dict:
    return get_success_data(api_client.get_commitment_week(week_id, GM), 200)


def read_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_lot_allocation(allocation_id, GM), 200)


def find_allocations(**filters) -> List[dict]:
    return get_success_data(
        api_client.list_lot_allocations(GM, params=filters or None), 200
    )


# ==========================================================================
# Composite setups
# ==========================================================================


def setup_zone_and_variety(zone_overrides=None, variety_overrides=None) -> dict:
    """One compartment plus one cultivar. Returns {"zone", "variety"}."""
    zone = create_zone(**(zone_overrides or {}))
    variety = create_variety(**(variety_overrides or {}))
    return {"zone": zone, "variety": variety}


def setup_planned_cycle(
    clock: str = CLOCK_EPOCH,
    zone_overrides=None,
    variety_overrides=None,
    cycle_overrides=None,
) -> dict:
    """A compartment, a cultivar and one PLANNED cycle. Returns {"zone","variety","cycle"}."""
    set_clock(clock)
    base = setup_zone_and_variety(zone_overrides, variety_overrides)
    cycle = create_crop_cycle(
        base["zone"]["id"], base["variety"]["id"], **(cycle_overrides or {})
    )
    return {"zone": base["zone"], "variety": base["variety"], "cycle": cycle}


def setup_transplanted_cycle(
    clock: str = "2026-08-06T00:00:00Z",
    zone_overrides=None,
    variety_overrides=None,
    cycle_overrides=None,
) -> dict:
    """A compartment, a cultivar and one cycle walked to TRANSPLANTED."""
    state = setup_planned_cycle(clock, zone_overrides, variety_overrides, cycle_overrides)
    state["cycle"] = transition_crop_cycle(state["cycle"]["id"], "TRANSPLANTED")
    return state


def setup_production_cycle(
    plan_clock: str = CLOCK_EPOCH,
    production_clock: str = "2026-08-24T06:00:00Z",
    zone_overrides=None,
    variety_overrides=None,
    cycle_overrides=None,
) -> dict:
    """A cycle walked to PRODUCTION, with the clock advanced past first harvest."""
    state = setup_transplanted_cycle(
        plan_clock, zone_overrides, variety_overrides, cycle_overrides
    )
    set_clock(production_clock)
    state["cycle"] = transition_crop_cycle(state["cycle"]["id"], "PRODUCTION")
    return state


def setup_scout_alert_zone(
    clock: str = "2026-08-06T00:00:00Z",
    observation_overrides=None,
    zone_overrides=None,
    variety_overrides=None,
    cycle_overrides=None,
) -> dict:
    """A TRANSPLANTED cycle plus one at-or-above-threshold observation.

    Leaves the compartment's ipm_posture at SCOUT_ALERT with one open pest alert.
    Returns the transplanted state plus {"scout", "observation"}.
    """
    state = setup_transplanted_cycle(
        clock, zone_overrides, variety_overrides, cycle_overrides
    )
    scout = create_scout_worker()
    observation = file_observation(
        state["zone"]["id"],
        state["cycle"]["id"],
        scout["id"],
        **(observation_overrides or {}),
    )
    state["scout"] = scout
    state["observation"] = observation
    return state


def setup_ipm_locked_zone(
    clock: str = "2026-08-06T00:00:00Z",
    first_observation=None,
    second_observation=None,
    zone_overrides=None,
    variety_overrides=None,
    cycle_overrides=None,
) -> dict:
    """A TRANSPLANTED cycle whose compartment has two open pest alerts and so reads LOCKED."""
    state = setup_scout_alert_zone(
        clock,
        first_observation or {"observed_at": "2026-08-06T07:00:00Z"},
        zone_overrides,
        variety_overrides,
        cycle_overrides,
    )
    state["second_observation"] = file_observation(
        state["zone"]["id"],
        state["cycle"]["id"],
        state["scout"]["id"],
        **(second_observation or {"observed_at": "2026-08-06T08:00:00Z", "pest_code": "THRIPS", "pest_count_per_plant": 1.100}),
    )
    return state


def setup_registered_lot(
    plan_clock: str = CLOCK_EPOCH,
    production_clock: str = "2026-08-24T06:00:00Z",
    lot_overrides=None,
    worker_overrides=None,
    zone_overrides=None,
    variety_overrides=None,
    cycle_overrides=None,
) -> dict:
    """A PRODUCTION cycle, a HARVEST worker and one UNGRADED, AMBIENT lot."""
    state = setup_production_cycle(
        plan_clock, production_clock, zone_overrides, variety_overrides, cycle_overrides
    )
    worker = create_harvest_worker(**(worker_overrides or {}))
    lot = register_lot(state["cycle"]["id"], worker["id"], **(lot_overrides or {}))
    state["harvest_worker"] = worker
    state["lot"] = lot
    return state


def setup_graded_lot(
    plan_clock: str = CLOCK_EPOCH,
    production_clock: str = "2026-08-24T06:00:00Z",
    lot_overrides=None,
    grade_overrides=None,
    worker_overrides=None,
    zone_overrides=None,
    variety_overrides=None,
    cycle_overrides=None,
) -> dict:
    """A lot walked to grading_status GRADED, cold_chain_status still AMBIENT."""
    state = setup_registered_lot(
        plan_clock,
        production_clock,
        lot_overrides,
        worker_overrides,
        zone_overrides,
        variety_overrides,
        cycle_overrides,
    )
    state["lot"] = grade_lot(
        state["lot"]["id"], state["harvest_worker"]["id"], **(grade_overrides or {})
    )
    return state


def setup_cold_held_lot(
    plan_clock: str = CLOCK_EPOCH,
    production_clock: str = "2026-08-24T06:00:00Z",
    lot_overrides=None,
    grade_overrides=None,
    inspector_user_id: Optional[str] = None,
    worker_overrides=None,
    zone_overrides=None,
    variety_overrides=None,
    cycle_overrides=None,
) -> dict:
    """A GRADED lot advanced through PRECOOLED to COLD_HELD."""
    state = setup_graded_lot(
        plan_clock,
        production_clock,
        lot_overrides,
        grade_overrides,
        worker_overrides,
        zone_overrides,
        variety_overrides,
        cycle_overrides,
    )
    cold_chain_event(state["lot"]["id"], "PRECOOLED", 10.0, inspector_user_id)
    state["lot"] = cold_chain_event(
        state["lot"]["id"], "COLD_HELD", 6.0, inspector_user_id
    )
    return state


def setup_precooled_lot(
    plan_clock: str = CLOCK_EPOCH,
    production_clock: str = "2026-08-24T06:00:00Z",
    lot_overrides=None,
    grade_overrides=None,
    inspector_user_id: Optional[str] = None,
) -> dict:
    """A GRADED lot advanced to PRECOOLED only, which the waterfall may still draw from."""
    state = setup_graded_lot(
        plan_clock, production_clock, lot_overrides, grade_overrides
    )
    state["lot"] = cold_chain_event(
        state["lot"]["id"], "PRECOOLED", 10.0, inspector_user_id
    )
    return state


def setup_delivered_batch(
    clock: str = "2026-08-06T00:00:00Z",
    batch_overrides=None,
    delivered_volume_liters: float = 12000.00,
    zone_overrides=None,
    variety_overrides=None,
    cycle_overrides=None,
) -> dict:
    """A TRANSPLANTED cycle with one fertigation batch walked to DELIVERED."""
    state = setup_transplanted_cycle(
        clock, zone_overrides, variety_overrides, cycle_overrides
    )
    batch = create_fertigation_batch(
        state["zone"]["id"], state["cycle"]["id"], **(batch_overrides or {})
    )
    state["batch"] = transition_fertigation_batch(
        batch["id"], "DELIVERED", delivered_volume_liters=delivered_volume_liters
    )
    return state


def setup_program_with_open_week(
    clock: str = "2026-08-24T06:00:00Z",
    program_overrides=None,
    week_overrides=None,
) -> dict:
    """One ACTIVE retail program and one OPEN commitment week on it."""
    set_clock(clock)
    program = create_retail_program(**(program_overrides or {}))
    week = create_commitment_week(program["id"], **(week_overrides or {}))
    return {"program": program, "week": week}
