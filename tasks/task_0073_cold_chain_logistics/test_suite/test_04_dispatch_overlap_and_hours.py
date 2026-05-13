"""Dispatch preconditions: vehicle overlap, driver hours-of-service,
and state-vs-business-constraint priority pair (PRD §3.3, §2.6).

Difficulty-design instances exercised:
- # difficulty: boundary_precision_check/driver_rolling_24h_minutes_strict_gt
- # difficulty: resource_temporal_overlap/vehicle_half_open_interval_overlap
- # difficulty: resource_temporal_overlap/driver_rolling_24h_aggregate_capacity
- # difficulty: priority_pair_validation_conflict/state_vs_business_constraint_on_dispatch
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TaskParties,
    advance_clock_to,
    create_driver,
    create_transport_task,
    create_vehicle,
    get_clock_now,
    make_dispatcher_headers,
    parse_iso,
    setup_dispatched_task,
    setup_driver_at_minutes,
    setup_two_dispatch_overlap_pair,
    validate_error,
    validate_success,
)


# ===========================================================================
# Dispatch happy path + side effects (PRD §3.3)
# ===========================================================================
def test_dispatch_flips_vehicle_and_driver(api):
    """PRD §3.3: 'Successful dispatch produces three side effects in the
    same request: the vehicle moves to IN_USE, the driver moves to
    ON_DUTY, and the task's updated_at and version are refreshed.'"""
    scenario = setup_dispatched_task()
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    assert task["status"] == "DISPATCHED"
    vehicle = validate_success(
        api.get_vehicle(scenario["vehicle"]["id"], parties.carrier_h())
    )
    driver = validate_success(
        api.get_driver(scenario["driver"]["id"], parties.carrier_h())
    )
    assert vehicle["status"] == "IN_USE", (
        "PRD §3.3: 'the vehicle moves to IN_USE'"
    )
    assert driver["status"] == "ON_DUTY", (
        "PRD §3.3: 'the driver moves to ON_DUTY'"
    )


# ===========================================================================
# Vehicle overlap (half-open) — difficulty
# ===========================================================================
def test_vehicle_half_open_adjacency_allowed(api):
    """PRD §3.3: 'Exact equality at endpoints — the existing task's end
    timestamp equalling the new task's start timestamp — is allowed under
    half-open semantics and does not trigger the rejection.'

    # difficulty: resource_temporal_overlap/vehicle_half_open_interval_overlap
    """
    bundle = setup_two_dispatch_overlap_pair(gap_seconds=0)
    second = bundle["second"]
    resp = api.dispatch_task(second["id"], make_dispatcher_headers())
    data = validate_success(resp)
    assert data["status"] == "DISPATCHED"


def test_vehicle_strict_overlap_rejected(api):
    """PRD §3.3: 'no other task on this vehicle in DISPATCHED,
    IN_TRANSIT, or AT_STOP may have an interval that strictly intersects
    the new task's interval. ... A rejection here is reported as
    ERR_VEHICLE_OVERLAP.'

    # difficulty: resource_temporal_overlap/vehicle_half_open_interval_overlap
    """
    bundle = setup_two_dispatch_overlap_pair(gap_seconds=-1)
    second = bundle["second"]
    resp = api.dispatch_task(second["id"], make_dispatcher_headers())
    validate_error(resp, ApiErrorId.ERR_VEHICLE_OVERLAP.value)


# ===========================================================================
# Driver hours-of-service boundary — difficulty
# ===========================================================================
def test_driver_hours_equality_allowed(api):
    """PRD §3.3: 'The dispatch is rejected if there exists any such
    anchored window where the driver's accumulated minutes plus the new
    task's overlap into that window strictly exceeds max_daily_minutes;
    equality with max_daily_minutes is allowed.'

    # difficulty: boundary_precision_check/driver_rolling_24h_minutes_strict_gt
    """
    bundle = setup_driver_at_minutes(
        consumed_minutes=540, new_task_minutes=120, max_daily_minutes=660,
    )
    second = bundle["second"]
    resp = api.dispatch_task(second["id"], make_dispatcher_headers())
    data = validate_success(resp)
    assert data["status"] == "DISPATCHED"


def test_driver_hours_exceeded_by_one_minute_rejected(api):
    """PRD §3.3: 'The dispatch is rejected if there exists any such
    anchored window where the driver's accumulated minutes plus the new
    task's overlap into that window strictly exceeds max_daily_minutes.
    ... The rejection code is ERR_DRIVER_HOURS_EXCEEDED.'

    # difficulty: boundary_precision_check/driver_rolling_24h_minutes_strict_gt
    # difficulty: resource_temporal_overlap/driver_rolling_24h_aggregate_capacity
    """
    bundle = setup_driver_at_minutes(
        consumed_minutes=540, new_task_minutes=121, max_daily_minutes=660,
    )
    second = bundle["second"]
    resp = api.dispatch_task(second["id"], make_dispatcher_headers())
    validate_error(resp, ApiErrorId.ERR_DRIVER_HOURS_EXCEEDED.value)


def test_driver_hours_aggregate_capacity_non_overlapping_vehicles(api):
    """PRD §3.3: 'For any candidate 24-hour rolling window ... the
    driver's accumulated minutes within that window is the sum, over all
    assigned tasks, of the minute-count of the intersection of each
    task's interval with that window.'

    Two NON-overlapping vehicles, one driver, sum 540 + 121 > 660 within
    24h -> ERR_DRIVER_HOURS_EXCEEDED (not ERR_VEHICLE_OVERLAP).

    # difficulty: resource_temporal_overlap/driver_rolling_24h_aggregate_capacity
    """
    bundle = setup_driver_at_minutes(
        consumed_minutes=540, new_task_minutes=121, max_daily_minutes=660,
    )
    second = bundle["second"]
    resp = api.dispatch_task(second["id"], make_dispatcher_headers())
    validate_error(resp, ApiErrorId.ERR_DRIVER_HOURS_EXCEEDED.value)


# ===========================================================================
# State vs business_constraint priority — difficulty
# ===========================================================================
def test_state_error_wins_over_overlap_on_redispatch(api):
    """PRD §2.6: 'State eligibility — that the target resource is in the
    from-state the requested transition requires — is checked fifth and
    yields ERR_INVALID_STATE (status 409) when it fails. Beyond those
    five gates, business-safety, business-referential,
    business-constraint ... checks fire in scaffold-priority order.'

    A second /dispatch on the same task is both a state violation
    (already DISPATCHED) and a vehicle-overlap-with-self violation;
    state error (priority 5) wins.

    # difficulty: priority_pair_validation_conflict/state_vs_business_constraint_on_dispatch
    """
    scenario = setup_dispatched_task()
    task = scenario["task"]
    resp = api.dispatch_task(task["id"], make_dispatcher_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_check_fires_for_redispatch_on_in_transit_task(api):
    """PRD §2.6: 'State eligibility — that the target resource is in the
    from-state the requested transition requires — is checked fifth and
    yields ERR_INVALID_STATE (status 409) when it fails.'

    A task already in IN_TRANSIT cannot be re-dispatched: state check
    (priority 5) fires before any business_constraint check.

    # difficulty: priority_pair_validation_conflict/state_vs_business_constraint_on_dispatch
    """
    from test_helpers import setup_in_transit_task
    scenario = setup_in_transit_task()
    task = scenario["task"]
    resp = api.dispatch_task(task["id"], make_dispatcher_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Other dispatch preconditions
# ===========================================================================
def test_dispatch_without_vehicle_assignment_rejected(api):
    """PRD §3.3: 'The task must have a non-null vehicle_id pointing to a
    Vehicle whose status is AVAILABLE and a non-null driver_id pointing
    to a Driver whose status is OFF_DUTY.'"""
    parties = TaskParties()
    # Create a task with no vehicle / driver yet.
    task = create_transport_task(parties=parties)
    resp = api.dispatch_task(task["id"], make_dispatcher_headers())
    # vehicle_id null at dispatch — state/business precondition fails.
    body = resp.json()
    # PRD does not pin which exact error_id is returned for "null
    # vehicle_id at dispatch" beyond it being a precondition failure.
    # We accept either ERR_INVALID_STATE or ERR_REFERENCE_NOT_FOUND
    # or ERR_VALIDATION — but the call MUST fail with 4xx.
    assert resp.status_code >= 400, (
        f"PRD §3.3 says dispatch requires non-null vehicle_id; got "
        f"{resp.status_code} body={body}"
    )


def test_dispatch_route_with_one_stop_rejected(api):
    """PRD §3.3: 'Finally, the route must already have at least two
    stops (origin plus at least one destination); a route shorter than
    that cannot dispatch.'"""
    parties = TaskParties()
    vehicle = create_vehicle(parties=parties)
    driver = create_driver(parties=parties)
    task = create_transport_task(
        parties=parties, vehicle=vehicle, driver=driver, n_stops=1,
    )
    resp = api.dispatch_task(task["id"], make_dispatcher_headers())
    assert resp.status_code >= 400, (
        f"PRD §3.3 forbids dispatch with fewer than 2 stops; got "
        f"{resp.status_code}"
    )


# ===========================================================================
# Abort cascade
# ===========================================================================
def test_abort_dispatched_releases_vehicle_and_driver(api):
    """PRD §3.3: 'The same abort capability is available while the task
    is DISPATCHED or IN_TRANSIT, in which case the vehicle is restored
    to AVAILABLE and the driver to OFF_DUTY as a side effect of the
    abort.'"""
    scenario = setup_dispatched_task()
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    aborted = validate_success(
        api.abort_task(
            task["id"], {"reason": "test"}, make_dispatcher_headers(),
        )
    )
    assert aborted["status"] == "ABORTED"
    vehicle = validate_success(
        api.get_vehicle(scenario["vehicle"]["id"], parties.carrier_h())
    )
    driver = validate_success(
        api.get_driver(scenario["driver"]["id"], parties.carrier_h())
    )
    assert vehicle["status"] == "AVAILABLE"
    assert driver["status"] == "OFF_DUTY"
