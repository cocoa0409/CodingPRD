"""Cascades and lifecycle terminals: eligibility lapse, broker suspend, no-show
strike accrual and auto-suspend, termination dependency guard, terminal-state
lockdown, and the assign/cancel driver-availability invariant.

Difficulty queue A (transitive_cascade, compensating_invariant) plus corner
queue B (calculations no-show, state_machines terminate / cancel).
"""
import pytest
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    make_driver_headers,
    create_member_payload,
    create_eligibility_span_payload,
    create_trip_payload,
)
from test_helpers import fixtures

COORD = TEST_USERS["coordinator_headers"]
BROKER = TEST_USERS["broker_headers"]


def _active_assignment_status(api, trip_id):
    resp = api.list_trip_assignments(trip_id, COORD)
    data, _ = validate_paginated(resp)
    assert data, "expected at least one assignment"
    # Most recent assignment for this trip.
    return data[-1]["status"]


def test_eligibility_lapse_cascade_depth3(api):
    """PRD 3.1: "Every `TripRequest` for this member whose `trip_status` is
    `SCHEDULED` or `ASSIGNED` is moved to `CANCELLED`. For each such cascaded trip,
    every `OUTBOUND` or `RETURN` leg in `PENDING`, `READY`, or `EN_ROUTE` is moved
    to `CANCELLED`; the trip's `ACTIVE` assignment, if any, is moved to `RELEASED`,
    and the driver named by that assignment, if `ON_TRIP`, returns to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/eligibility_lapse_cascade_depth3
    """
    # Member span covers only [2026-01-01, 2026-03-03); recompute at 2026-03-04 -> lapse.
    world = fixtures.setup_world(
        modality="WHEELCHAIR", medicaid_id="M-EL1", broker_max_modality="STRETCHER",
        span_los="BARIATRIC", span_end="2026-03-03T00:00:00Z")
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, is_round_trip=True,
        return_is_will_call=False, appointment_at="2026-03-02T09:00:00Z")
    driver_id = world["driver"]["id"]
    fixtures.set_clock("2026-03-04T00:00:00Z")
    member = get_success_data(api.recompute_eligibility(world["member"]["id"], COORD))
    assert member["eligibility_status"] == "SUSPENDED"
    trip_after = get_success_data(api.get_trip(assigned["id"], COORD))
    assert trip_after["trip_status"] == "CANCELLED"
    assert _active_assignment_status(api, assigned["id"]) == "RELEASED"
    driver = fixtures.get_driver(driver_id)
    assert driver["status"] == "AVAILABLE"


def test_eligibility_lapse_cancels_legs(api):
    """PRD 3.1: "For each such cascaded trip, every `OUTBOUND` or `RETURN` leg in
    `PENDING`, `READY`, or `EN_ROUTE` is moved to `CANCELLED`".

    Design: Difficulty/transitive_cascade/eligibility_lapse_cascade_depth3
    """
    world = fixtures.setup_world(
        modality="WHEELCHAIR", medicaid_id="M-EL1b", broker_max_modality="STRETCHER",
        span_los="BARIATRIC", span_end="2026-03-03T00:00:00Z")
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, is_round_trip=True,
        return_is_will_call=False, appointment_at="2026-03-02T09:00:00Z")
    fixtures.set_clock("2026-03-04T00:00:00Z")
    get_success_data(api.recompute_eligibility(world["member"]["id"], COORD))
    leg_resp = api.list_trip_legs(assigned["id"], COORD)
    leg_data, _ = validate_paginated(leg_resp)
    assert leg_data, "trip should still have legs"
    assert all(leg["leg_status"] == "CANCELLED" for leg in leg_data)


def test_broker_suspend_cascade_depth2(api):
    """PRD 3.2: "Suspending a broker is itself a cascade: every `TripRequest` whose
    `assigned_broker_id` is this broker and whose `trip_status` is `ASSIGNED` is
    reverted to `SCHEDULED`; for each such trip the `ACTIVE` assignment is moved to
    `RELEASED`, its driver — if `ON_TRIP` — returns to `AVAILABLE`, and the trip's
    `assigned_broker_id` and `assigned_driver_id` are cleared."

    Design: Difficulty/transitive_cascade/broker_suspend_cascade_depth2
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-BS1")
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    driver_id = world["driver"]["id"]
    broker = get_success_data(api.suspend_broker(world["broker"]["id"], COORD))
    assert broker["status"] == "SUSPENDED"
    trip_after = get_success_data(api.get_trip(assigned["id"], COORD))
    assert trip_after["trip_status"] == "SCHEDULED"
    assert trip_after["assigned_driver_id"] is None
    driver = fixtures.get_driver(driver_id)
    assert driver["status"] == "AVAILABLE"


def test_broker_suspend_releases_assignment(api):
    """PRD 3.2: "for each such trip the `ACTIVE` assignment is moved to `RELEASED`,
    its driver — if `ON_TRIP` — returns to `AVAILABLE`, and the trip's
    `assigned_broker_id` and `assigned_driver_id` are cleared."

    Design: Difficulty/transitive_cascade/broker_suspend_cascade_depth2
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-BS1b")
    assigned, legs = fixtures.create_assigned_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    get_success_data(api.suspend_broker(world["broker"]["id"], COORD))
    trip_after = get_success_data(api.get_trip(assigned["id"], COORD))
    assert trip_after["assigned_broker_id"] is None
    assert _active_assignment_status(api, assigned["id"]) == "RELEASED"


def test_assign_then_cancel_conserves_driver_availability(api):
    """PRD 3.3: "Cancelling an `ASSIGNED` trip additionally moves the `ACTIVE`
    assignment to `RELEASED`, returns the `ON_TRIP` driver to `AVAILABLE`, and
    clears the trip's assigned broker and driver identifiers."

    Design: Difficulty/compensating_invariant/assign_then_cancel_conserves_driver_availability
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-CI1")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)
    driver_id = world["driver"]["id"]
    get_success_data(api.cancel_trip(assigned["id"], COORD))
    driver = fixtures.get_driver(driver_id)
    assert driver["status"] == "AVAILABLE", "driver availability conserved across assign+cancel"
    trip_after = get_success_data(api.get_trip(assigned["id"], COORD))
    assert trip_after["assigned_driver_id"] is None
    assert _active_assignment_status(api, assigned["id"]) == "RELEASED"


def test_cancel_assigned_trip_clears_broker(api):
    """PRD 3.3: "Cancelling an `ASSIGNED` trip additionally moves the `ACTIVE`
    assignment to `RELEASED`, returns the `ON_TRIP` driver to `AVAILABLE`, and
    clears the trip's assigned broker and driver identifiers."

    Design: Difficulty/compensating_invariant/assign_then_cancel_conserves_driver_availability
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-CI1b")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)
    cancelled = get_success_data(api.cancel_trip(assigned["id"], COORD))
    assert cancelled["trip_status"] == "CANCELLED"
    assert cancelled["assigned_broker_id"] is None


def test_noshow_strike_accrual_and_auto_suspend_at_threshold(api):
    """PRD 3.5: "The member's `noshow_strike_count` is incremented by one. When
    that incremented count reaches the suspension threshold of three or more
    strikes, the member is automatically moved to `SUSPENDED` and the full
    eligibility-lapse cascade of Section 3.1 fires exactly as if a recompute had
    found no coverage."

    Design: Corner/calculations/noshow_strike_accrual_and_auto_suspend_at_threshold
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-NS1")
    # Two prior no-shows -> strike count 2, still ELIGIBLE.
    fixtures.accrue_noshow_strikes(world, 2, modality="AMBULATORY", start_day=2)
    member_mid = fixtures.get_member(world["member"]["id"])
    assert member_mid["noshow_strike_count"] == 2
    assert member_mid["eligibility_status"] == "ELIGIBLE"
    # Third no-show -> count 3 >= threshold -> SUSPENDED.
    trip, ob, driver_id = fixtures.setup_arrived_outbound_for_noshow(
        world, appointment_at="2026-03-04T09:00:00Z", modality="AMBULATORY")
    get_success_data(api.leg_no_show(ob["id"], make_driver_headers(driver_id)))
    member = fixtures.get_member(world["member"]["id"])
    assert member["noshow_strike_count"] == 3
    assert member["eligibility_status"] == "SUSPENDED"
    trip_after = get_success_data(api.get_trip(trip["id"], COORD))
    assert trip_after["trip_status"] == "NO_SHOW"


def test_noshow_below_threshold_stays_eligible(api):
    """PRD 3.5: "The member's `noshow_strike_count` is incremented by one. When
    that incremented count reaches the suspension threshold of three or more
    strikes, the member is automatically moved to `SUSPENDED`".

    Design: Corner/calculations/noshow_strike_accrual_and_auto_suspend_at_threshold
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-NS2")
    fixtures.accrue_noshow_strikes(world, 1, modality="AMBULATORY", start_day=2)
    member = fixtures.get_member(world["member"]["id"])
    assert member["noshow_strike_count"] == 1
    assert member["eligibility_status"] == "ELIGIBLE"


def test_terminate_member_with_in_flight_trip_blocked(api):
    """PRD 3.1: "Termination is blocked, with `ERR_DEPENDENCY_EXISTS`, if the
    member has any `TripRequest` whose `trip_status` is `ASSIGNED` or
    `IN_PROGRESS` — in-flight work must be resolved first."

    Design: Corner/state_machines/terminate_member_with_in_flight_trip_blocked
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-TM1")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    fixtures.assign_trip(world, scheduled)  # ASSIGNED -> in-flight
    resp = api.terminate_member(world["member"]["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_DEPENDENCY_EXISTS.value)
    member = fixtures.get_member(world["member"]["id"])
    assert member["eligibility_status"] == "ELIGIBLE"


def test_cancel_trip_from_completed_returns_invalid_state(api):
    """PRD 3.3: "A coordinator may cancel a trip from `DRAFT`, `SCHEDULED`, or
    `ASSIGNED`."
    PRD 2.10: "then that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/cancel_trip_from_completed_returns_invalid_state
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-IT1")
    trip, legs, driver_id = fixtures.complete_oneway_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, odometer=8.0)
    completed = get_success_data(api.get_trip(trip["id"], COORD))
    assert completed["trip_status"] == "COMPLETED"
    resp = api.cancel_trip(trip["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_trip(trip["id"], COORD))
    assert after["trip_status"] == "COMPLETED"
