"""Leg execution and the will-call return cycle.

Difficulty queue A (non_linear_state_machine leg cycle, boundary_precision dwell,
resource_temporal_overlap leg sequence) plus corner queue B (state_machines
bubble-up completion).
"""
import pytest
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_driver_headers,
)
from test_helpers import fixtures

COORD = TEST_USERS["coordinator_headers"]


def test_leg_will_call_cycle_ready_to_pending(api):
    """PRD 3.5: "If the member turns out not to be ready, a coordinator retracts
    the readiness, moving the leg from `READY` back to `PENDING` and clearing
    `ready_called_at` to null; this is the cycle."

    Design: Difficulty/non_linear_state_machine/leg_will_call_cycle_ready_to_pending
    """
    world = fixtures.setup_world(modality="WHEELCHAIR", medicaid_id="M-WC1",
                                 broker_max_modality="STRETCHER", span_los="BARIATRIC")
    fixtures.set_clock("2026-03-02T09:00:00Z")
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, is_round_trip=True,
        return_is_will_call=True, appointment_at="2026-03-02T10:00:00Z")
    driver_id = world["driver"]["id"]
    dh = make_driver_headers(driver_id)
    ob, rt = legs[0], legs[1]
    fixtures._drive_leg_to_dropoff(ob["id"], driver_id, 10.0)
    # READY then retract.
    readied = get_success_data(api.leg_ready(rt["id"], COORD))
    assert readied["leg_status"] == "READY"
    assert readied["ready_called_at"] is not None
    resp = api.leg_cancel_ready(rt["id"], COORD)
    data = validate_success(resp, 200)
    assert data["leg_status"] == "PENDING"
    assert data["ready_called_at"] is None


def test_will_call_ready_stamps_then_cancel_clears(api):
    """PRD 3.5: "A coordinator marks it `READY`, which stamps `ready_called_at` to
    the current clock ... If the member turns out not to be ready, a coordinator
    retracts the readiness, moving the leg from `READY` back to `PENDING` and
    clearing `ready_called_at` to null".

    Design: Difficulty/non_linear_state_machine/leg_will_call_cycle_ready_to_pending
    """
    world = fixtures.setup_world(modality="WHEELCHAIR", medicaid_id="M-WC1b",
                                 broker_max_modality="STRETCHER", span_los="BARIATRIC")
    fixtures.set_clock("2026-03-02T09:00:00Z")
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, is_round_trip=True,
        return_is_will_call=True, appointment_at="2026-03-02T10:00:00Z")
    driver_id = world["driver"]["id"]
    ob, rt = legs[0], legs[1]
    fixtures._drive_leg_to_dropoff(ob["id"], driver_id, 10.0)
    get_success_data(api.leg_ready(rt["id"], COORD))
    get_success_data(api.leg_cancel_ready(rt["id"], COORD))
    refetched = get_success_data(api.get_leg(rt["id"], COORD))
    assert refetched["leg_status"] == "PENDING"
    assert refetched["ready_called_at"] is None


def test_will_call_dwell_free_minutes_strict_greater_than_boundary(api):
    """PRD 3.8: "Compare it to the rate row's `dwell_free_minutes`, with a strict
    boundary: if the raw dwell is strictly greater than the free allowance, the
    leg's `dwell_minutes` is the raw dwell minus the free allowance; if the raw
    dwell is less than or equal to the free allowance (including exactly equal),
    `dwell_minutes` is zero."

    Design: Difficulty/boundary_precision_check/will_call_dwell_free_minutes_strict_greater_than
    """
    # Rate dwell_free_minutes 10; pickup exactly 10 minutes after ready -> 0 billable.
    world = fixtures.setup_world(
        modality="WHEELCHAIR", medicaid_id="M-BD2", broker_max_modality="STRETCHER",
        span_los="BARIATRIC", clock="2026-03-02T08:00:00Z",
        rate_overrides={"base_fare_cents": 2000, "loaded_rate_cents_per_mile": 150,
                        "dwell_free_minutes": 10, "dwell_cents_per_minute": 50})
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, is_round_trip=True,
        return_is_will_call=True, appointment_at="2026-03-02T09:00:00Z")
    driver_id = world["driver"]["id"]
    dh = make_driver_headers(driver_id)
    ob, rt = legs[0], legs[1]
    fixtures._drive_leg_to_dropoff(ob["id"], driver_id, 10.0)
    fixtures.set_clock("2026-03-02T09:00:00Z")
    get_success_data(api.leg_ready(rt["id"], COORD))
    get_success_data(api.leg_depart(rt["id"], dh))
    get_success_data(api.leg_arrive(rt["id"], dh))
    fixtures.set_clock("2026-03-02T09:10:00Z")  # exactly 10 min after ready
    resp = api.leg_pickup(rt["id"], dh)
    data = validate_success(resp, 200)
    assert data["dwell_minutes"] == 0, "raw 10 == free 10, strict '>' not crossed"


def test_will_call_dwell_above_free_minutes(api):
    """PRD 3.8: "if the raw dwell is strictly greater than the free allowance, the
    leg's `dwell_minutes` is the raw dwell minus the free allowance".

    Design: Difficulty/boundary_precision_check/will_call_dwell_free_minutes_strict_greater_than
    """
    # Ready 09:00, pickup 09:25 -> raw 25, free 10 -> billable 15.
    world = fixtures.setup_world(
        modality="WHEELCHAIR", medicaid_id="M-BD2b", broker_max_modality="STRETCHER",
        span_los="BARIATRIC", clock="2026-03-02T08:00:00Z",
        rate_overrides={"base_fare_cents": 2000, "loaded_rate_cents_per_mile": 150,
                        "dwell_free_minutes": 10, "dwell_cents_per_minute": 50})
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, is_round_trip=True,
        return_is_will_call=True, appointment_at="2026-03-02T09:00:00Z")
    driver_id = world["driver"]["id"]
    dh = make_driver_headers(driver_id)
    ob, rt = legs[0], legs[1]
    fixtures._drive_leg_to_dropoff(ob["id"], driver_id, 10.0)
    fixtures.set_clock("2026-03-02T09:00:00Z")
    get_success_data(api.leg_ready(rt["id"], COORD))
    get_success_data(api.leg_depart(rt["id"], dh))
    get_success_data(api.leg_arrive(rt["id"], dh))
    fixtures.set_clock("2026-03-02T09:25:00Z")
    resp = api.leg_pickup(rt["id"], dh)
    data = validate_success(resp, 200)
    assert data["dwell_minutes"] == 15, "raw 25 - free 10 = 15"


def test_will_call_return_blocked_before_outbound_dropped_off(api):
    """PRD 3.5: "A coordinator marks it `READY`, which stamps `ready_called_at` to
    the current clock — but only if the parent trip is `IN_PROGRESS` and the
    `OUTBOUND` leg is already `DROPPED_OFF`; a will-call return readied or departed
    before its outbound leg has been dropped off, or while the trip is not
    `IN_PROGRESS`, is rejected with `ERR_LEG_SEQUENCE_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/will_call_return_blocked_before_outbound_dropped_off
    """
    world = fixtures.setup_world(modality="WHEELCHAIR", medicaid_id="M-RO1",
                                 broker_max_modality="STRETCHER", span_los="BARIATRIC",
                                 clock="2026-03-02T08:00:00Z")
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, is_round_trip=True,
        return_is_will_call=True, appointment_at="2026-03-02T09:00:00Z")
    driver_id = world["driver"]["id"]
    dh = make_driver_headers(driver_id)
    ob, rt = legs[0], legs[1]
    # OUTBOUND only departed (EN_ROUTE), not DROPPED_OFF.
    get_success_data(api.leg_depart(ob["id"], dh))
    resp = api.leg_ready(rt["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_LEG_SEQUENCE_VIOLATION.value)
    after = get_success_data(api.get_leg(rt["id"], COORD))
    assert after["leg_status"] == "PENDING"


def test_will_call_ready_blocked_while_trip_not_in_progress(api):
    """PRD 3.5: "a will-call return readied or departed before its outbound leg
    has been dropped off, or while the trip is not `IN_PROGRESS`, is rejected with
    `ERR_LEG_SEQUENCE_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/will_call_return_blocked_before_outbound_dropped_off
    """
    # Trip only ASSIGNED (outbound never departed) -> not IN_PROGRESS yet.
    world = fixtures.setup_world(modality="WHEELCHAIR", medicaid_id="M-RO1b",
                                 broker_max_modality="STRETCHER", span_los="BARIATRIC",
                                 clock="2026-03-02T08:00:00Z")
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, is_round_trip=True,
        return_is_will_call=True, appointment_at="2026-03-02T09:00:00Z")
    rt = legs[1]
    resp = api.leg_ready(rt["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_LEG_SEQUENCE_VIOLATION.value)
    after = get_success_data(api.get_leg(rt["id"], COORD))
    assert after["leg_status"] == "PENDING"


def test_outbound_first_departure_promotes_trip_in_progress(api):
    """PRD 3.5: "When the departing leg is the `OUTBOUND` leg of an `ASSIGNED`
    trip, that first departure also promotes the trip from `ASSIGNED` to
    `IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/trip_parallel_axes_lifecycle_and_billing
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-IP1")
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    driver_id = world["driver"]["id"]
    get_success_data(api.leg_depart(legs[0]["id"], make_driver_headers(driver_id)))
    after = get_success_data(api.get_trip(assigned["id"], COORD))
    assert after["trip_status"] == "IN_PROGRESS"


def test_trip_bubble_up_completes_on_all_legs_dropped(api):
    """PRD 3.5: "When the last non-cancelled leg of a trip reaches `DROPPED_OFF`,
    the server promotes the trip from `IN_PROGRESS` to `COMPLETED`, releases the
    `ACTIVE` assignment, and returns the driver from `ON_TRIP` to `AVAILABLE`."

    Design: Corner/state_machines/trip_bubble_up_completes_on_all_legs_dropped
    """
    world = fixtures.setup_world(modality="WHEELCHAIR", medicaid_id="M-BU1",
                                 broker_max_modality="STRETCHER", span_los="BARIATRIC",
                                 clock="2026-03-02T08:00:00Z")
    trip, legs, driver_id = fixtures.complete_roundtrip_non_will_call(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10,
        ob_odometer=10.0, rt_odometer=10.0)
    after = get_success_data(api.get_trip(trip["id"], COORD))
    assert after["trip_status"] == "COMPLETED"
    driver = fixtures.get_driver(driver_id)
    assert driver["status"] == "AVAILABLE"
