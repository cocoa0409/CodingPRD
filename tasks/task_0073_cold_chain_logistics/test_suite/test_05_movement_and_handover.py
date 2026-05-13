"""Movement, multi-stop handover, and the depth-3 delivery cascade
(PRD §3.4).

Difficulty-design instances exercised:
- # difficulty: transitive_cascade/handover_to_task_to_vehicle_driver_release
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TaskParties,
    advance_clock_to,
    assert_handover_record,
    handover_payload,
    parse_iso,
    setup_at_stop_task,
    setup_delivered_task,
    setup_in_transit_task,
    setup_dispatched_task,
    validate_error,
    validate_success,
)


# ===========================================================================
# Depart (DISPATCHED -> IN_TRANSIT)
# ===========================================================================
def test_depart_origin_advances_first_stop_to_arrived(api):
    """PRD §3.4: 'As a side effect of departure, the first TaskStop
    (sequence equal to one) advances from PENDING to ARRIVED because
    the cargo is already at origin.'"""
    scenario = setup_in_transit_task()
    parties: TaskParties = scenario["parties"]
    task = validate_success(
        api.get_transport_task(scenario["task"]["id"], parties.driver_h())
    )
    assert task["status"] == "IN_TRANSIT"
    stop_1 = next(s for s in task["stops"] if s["sequence"] == 1)
    assert stop_1["status"] == "ARRIVED"


def test_depart_before_pre_window_rejected(api):
    """PRD §3.4: 'Departure is gated by the clock: the current logical
    clock must be at least planned_start_at minus 3600 seconds — that
    is, no earlier than one hour before the planned start.'

    We construct a task with planned_start_at far in the future, then
    immediately try to depart -> ERR_INVALID_STATE (the precondition
    failure surfaces via the state gate).
    """
    from test_helpers import get_clock_now
    far_start = parse_iso(get_clock_now()) + timedelta(seconds=7200)
    scenario = setup_dispatched_task(planned_start_at=far_start)
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    resp = api.depart_task(task["id"], parties.driver_h())
    # PRD names the depart precondition without naming a specific
    # error_id; the only consistent failure mode is a 4xx with
    # ERR_INVALID_STATE or a clock-related ERR. Assert it fails.
    assert resp.status_code >= 400, (
        "PRD §3.4 forbids depart earlier than planned_start_at minus "
        "3600 seconds"
    )


# ===========================================================================
# Arrive (IN_TRANSIT -> AT_STOP)
# ===========================================================================
def test_arrive_clock_stamps_actual_arrival(api):
    """PRD §3.4: 'As a side effect, the stop's actual_arrival_at is
    clock-stamped and the stop's status moves from PENDING to ARRIVED.'"""
    scenario = setup_at_stop_task(stop_index=2)
    parties: TaskParties = scenario["parties"]
    task = validate_success(
        api.get_transport_task(scenario["task"]["id"], parties.driver_h())
    )
    assert task["status"] == "AT_STOP"
    stop_2 = next(s for s in task["stops"] if s["sequence"] == 2)
    assert stop_2["status"] == "ARRIVED"
    assert stop_2["actual_arrival_at"] is not None


# ===========================================================================
# Handover and DELIVERED cascade — difficulty
# ===========================================================================
def test_handover_creates_record_and_advances_stop(api):
    """PRD §3.4: 'The stop advances from ARRIVED to HANDED_OVER.'"""
    scenario = setup_at_stop_task(stop_index=1)
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    # Depart origin already arrived stop 1; create a handover at stop 1.
    task = validate_success(
        api.get_transport_task(task["id"], parties.driver_h())
    )
    stop_1 = next(s for s in task["stops"] if s["sequence"] == 1)
    payload = handover_payload(
        from_party_id=parties.shipper_id,
        to_party_id=parties.carrier_id,
        quantity_attested=task["cargo_quantity"],
    )
    hr = validate_success(
        api.create_handover(task["id"], stop_1["id"], payload, parties.driver_h()),
        expected_status=201,
    )
    assert_handover_record(hr)
    # Stop 1 advances to HANDED_OVER.
    refreshed = validate_success(
        api.get_transport_task(task["id"], parties.driver_h())
    )
    stop_1_after = next(s for s in refreshed["stops"] if s["sequence"] == 1)
    assert stop_1_after["status"] == "HANDED_OVER"


def test_final_handover_cascade_delivers_releases_driver_and_vehicle(api):
    """PRD §3.4: 'When the handed-over stop is the final-sequence stop
    and every other stop on the task is in HANDED_OVER or SKIPPED, the
    parent task automatically advances AT_STOP to DELIVERED with
    cascade depth two; the driver is returned to OFF_DUTY and the
    vehicle to AVAILABLE.'

    # difficulty: transitive_cascade/handover_to_task_to_vehicle_driver_release
    """
    scenario = setup_delivered_task()
    parties: TaskParties = scenario["parties"]
    task = validate_success(
        api.get_transport_task(scenario["task"]["id"], parties.driver_h())
    )
    assert task["status"] == "DELIVERED", (
        "PRD §3.4: parent task auto-transitions to DELIVERED"
    )
    final_stop_id = scenario["final_stop_id"]
    final_stop = next(s for s in task["stops"] if s["id"] == final_stop_id)
    assert final_stop["status"] == "HANDED_OVER"
    vehicle = validate_success(
        api.get_vehicle(scenario["vehicle"]["id"], parties.carrier_h())
    )
    driver = validate_success(
        api.get_driver(scenario["driver"]["id"], parties.carrier_h())
    )
    assert vehicle["status"] == "AVAILABLE", (
        "PRD §3.4 final-handover cascade: 'the vehicle to AVAILABLE'"
    )
    assert driver["status"] == "OFF_DUTY", (
        "PRD §3.4 final-handover cascade: 'the driver is returned to "
        "OFF_DUTY'"
    )


def test_final_handover_status_chain_link_by_link(api):
    """PRD §3.4: 'When the handed-over stop is the final-sequence stop
    and every other stop on the task is in HANDED_OVER or SKIPPED, the
    parent task automatically advances AT_STOP to DELIVERED with
    cascade depth two; the driver is returned to OFF_DUTY and the
    vehicle to AVAILABLE.'

    This test asserts each link of the depth-3 cascade independently:
    (1) final TaskStop = HANDED_OVER, (2) parent TransportTask =
    DELIVERED, (3) Vehicle = AVAILABLE AND Driver = OFF_DUTY.

    # difficulty: transitive_cascade/handover_to_task_to_vehicle_driver_release
    """
    scenario = setup_delivered_task()
    parties: TaskParties = scenario["parties"]
    task = validate_success(
        api.get_transport_task(scenario["task"]["id"], parties.driver_h())
    )
    final_stop = next(
        s for s in task["stops"] if s["id"] == scenario["final_stop_id"]
    )
    # Link 1
    assert final_stop["status"] == "HANDED_OVER", (
        "PRD §3.4 link 1: 'The stop advances from ARRIVED to HANDED_OVER.'"
    )
    # Link 2
    assert task["status"] == "DELIVERED", (
        "PRD §3.4 link 2: 'the parent task automatically advances "
        "AT_STOP to DELIVERED'"
    )
    # Link 3
    vehicle = validate_success(
        api.get_vehicle(scenario["vehicle"]["id"], parties.carrier_h())
    )
    driver = validate_success(
        api.get_driver(scenario["driver"]["id"], parties.carrier_h())
    )
    assert vehicle["status"] == "AVAILABLE"
    assert driver["status"] == "OFF_DUTY"


def test_duplicate_handover_on_same_stop_rejected(api):
    """PRD §3.4: 'Because HandoverRecord is unique per stop, a second
    handover attempt against the same stop ... is rejected with
    ERR_HANDOVER_ALREADY_EXISTS.'"""
    scenario = setup_at_stop_task(stop_index=1)
    parties: TaskParties = scenario["parties"]
    task = validate_success(
        api.get_transport_task(scenario["task"]["id"], parties.driver_h())
    )
    stop_1 = next(s for s in task["stops"] if s["sequence"] == 1)
    payload = handover_payload(
        from_party_id=parties.shipper_id,
        to_party_id=parties.carrier_id,
        quantity_attested=task["cargo_quantity"],
    )
    validate_success(
        api.create_handover(task["id"], stop_1["id"], payload, parties.driver_h()),
        expected_status=201,
    )
    resp = api.create_handover(
        task["id"], stop_1["id"], payload, parties.driver_h(),
    )
    validate_error(resp, ApiErrorId.ERR_HANDOVER_ALREADY_EXISTS.value)


def test_skip_only_when_handover_not_required(api):
    """PRD §3.4: 'A DISPATCHER may mark a stop as SKIPPED directly from
    PENDING only when that stop's handover_required is false; the
    request is rejected otherwise.'"""
    from test_helpers import (
        create_transport_task, create_driver, create_vehicle, get_clock_now,
        iso_utc, make_dispatcher_headers,
    )
    parties = TaskParties()
    vehicle = create_vehicle(parties=parties)
    driver = create_driver(parties=parties)
    start = parse_iso(get_clock_now()) + timedelta(seconds=300)
    stops = [
        {"sequence": 1, "location_label": "A",
         "planned_arrival_at": iso_utc(start + timedelta(seconds=600)),
         "handover_required": True},
        {"sequence": 2, "location_label": "B",
         "planned_arrival_at": iso_utc(start + timedelta(seconds=1200)),
         "handover_required": True},
    ]
    task = create_transport_task(
        parties=parties, vehicle=vehicle, driver=driver,
        planned_start_at=start, stops_override=stops,
    )
    stop_with_required = task["stops"][0]
    resp = api.skip_stop(task["id"], stop_with_required["id"],
                         make_dispatcher_headers())
    # Either ERR_INVALID_STATE (state precondition for skip) or
    # business constraint failure — PRD says 'rejected otherwise'
    # without naming the error_id.
    assert resp.status_code >= 400
