"""Dispatch scheduling guards: window well-formedness, truck capacity, crew
sizing, half-open truck overlap, buffered crew turnaround overlap, the
capacity-beats-overlap priority pair, and the truck-filtered listing.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_booked_job, register_truck, register_crew, schedule_dispatch,
    create_dispatch_payload,
    register_customer, create_job, create_survey_with_items, generate_estimate,
    accept_estimate, make_customer_headers, TEST_USERS,
    ITEMS_120CF, ITEMS_370CF,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _booked_local_job(items=ITEMS_120CF, move_date="2026-07-01T09:00:00Z"):
    """A BOOKED LOCAL job (estimate accepted, no deposit needed for scheduling)."""
    cust_id, job, survey, estimate = setup_booked_job(
        service_type="LOCAL", items=items,
        job_overrides={"requested_move_date": move_date})
    return cust_id, job, survey


def test_crew_turnaround_exact_90_minutes_apart_allowed(api):
    """PRD §3.6: "two crew windows separated by less than ninety minutes are
    rejected while windows exactly ninety minutes apart (the later start at or
    after the earlier end plus ninety minutes) are allowed; a violation is rejected
    with `ERR_CREW_DOUBLE_BOOKED`."

    Crew C holds 09:00-12:00; a second window 13:30-15:00 (exactly 90 min after
    12:00) on a different truck is accepted.

    Design: Difficulty/boundary_precision_check/crew_turnaround_buffer_exact_90_minutes_apart_allowed
    """
    crew = register_crew(head_count=3)
    truck1 = register_truck(capacity_cubic_feet=2000)
    truck2 = register_truck(capacity_cubic_feet=2000)

    _, jobA, _ = _booked_local_job(move_date="2026-07-01T09:00:00Z")
    schedule_dispatch(jobA["id"], truck_id=truck1["id"], crew_id=crew["id"],
                      window_start="2026-07-01T09:00:00Z", window_end="2026-07-01T12:00:00Z")

    _, jobB, _ = _booked_local_job(move_date="2026-07-01T13:30:00Z")
    res = api.create_dispatch(
        create_dispatch_payload(jobB["id"], truck2["id"], crew["id"],
                                window_start="2026-07-01T13:30:00Z",
                                window_end="2026-07-01T15:00:00Z", required_crew_size=3),
        DISPATCHER)
    dispB = validate_success(res, 201)
    assert dispB["status"] == "SCHEDULED"


def test_crew_turnaround_within_buffer_rejected(api):
    """PRD §3.6: "the requested window expanded by a ninety-minute turnaround buffer
    on each side must not overlap any non-terminal dispatch already on that crew, so
    two crew windows separated by less than ninety minutes are rejected ... a
    violation is rejected with `ERR_CREW_DOUBLE_BOOKED`."

    Second assertion (the negative side) on the crew-turnaround boundary instance:
    a crew window starting at 12:00 — touching the prior 09:00-12:00 raw boundary
    but well inside the 90-min buffer — is rejected.

    Design: Difficulty/boundary_precision_check/crew_turnaround_buffer_exact_90_minutes_apart_allowed
    """
    crew = register_crew(head_count=3)
    truck1 = register_truck(capacity_cubic_feet=2000)
    truck2 = register_truck(capacity_cubic_feet=2000)

    _, jobA, _ = _booked_local_job(move_date="2026-07-01T09:00:00Z")
    schedule_dispatch(jobA["id"], truck_id=truck1["id"], crew_id=crew["id"],
                      window_start="2026-07-01T09:00:00Z", window_end="2026-07-01T12:00:00Z")

    _, jobB, _ = _booked_local_job(move_date="2026-07-01T12:00:00Z")
    res = api.create_dispatch(
        create_dispatch_payload(jobB["id"], truck2["id"], crew["id"],
                                window_start="2026-07-01T12:00:00Z",
                                window_end="2026-07-01T14:00:00Z", required_crew_size=3),
        DISPATCHER)
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED", 409)


def test_truck_half_open_boundary_touch_allowed(api):
    """PRD §3.6: "two windows that merely touch at a boundary, where the earlier
    window's `window_end` equals the later window's `window_start`, do not overlap
    and are allowed; a true overlap is rejected with `ERR_TRUCK_DOUBLE_BOOKED`."

    Truck T holds 09:00-12:00; a second dispatch 12:00-14:00 (touching at 12:00) on
    the same truck (different crew) is accepted.

    Design: Difficulty/resource_temporal_overlap/truck_half_open_boundary_touch_allowed
    """
    truck = register_truck(capacity_cubic_feet=2000)
    crew1 = register_crew(name="Crew A", head_count=3)
    crew2 = register_crew(name="Crew B", head_count=3)

    _, jobA, _ = _booked_local_job(move_date="2026-07-01T09:00:00Z")
    schedule_dispatch(jobA["id"], truck_id=truck["id"], crew_id=crew1["id"],
                      window_start="2026-07-01T09:00:00Z", window_end="2026-07-01T12:00:00Z")

    _, jobB, _ = _booked_local_job(move_date="2026-07-01T12:00:00Z")
    res = api.create_dispatch(
        create_dispatch_payload(jobB["id"], truck["id"], crew2["id"],
                                window_start="2026-07-01T12:00:00Z",
                                window_end="2026-07-01T14:00:00Z", required_crew_size=3),
        DISPATCHER)
    dispB = validate_success(res, 201)
    assert dispB["status"] == "SCHEDULED"


def test_truck_true_overlap_rejected(api):
    """PRD §3.6: "The truck must be free for the window: the requested half-open
    interval must not overlap any non-terminal dispatch already on that truck ... a
    true overlap is rejected with `ERR_TRUCK_DOUBLE_BOOKED`."

    Second assertion (the negative side) on the truck half-open instance: a second
    dispatch 11:00-13:00 genuinely overlapping the prior 09:00-12:00 on the same
    truck is rejected.

    Design: Difficulty/resource_temporal_overlap/truck_half_open_boundary_touch_allowed
    """
    truck = register_truck(capacity_cubic_feet=2000)
    crew1 = register_crew(name="Crew A", head_count=3)
    crew2 = register_crew(name="Crew B", head_count=3)

    _, jobA, _ = _booked_local_job(move_date="2026-07-01T09:00:00Z")
    schedule_dispatch(jobA["id"], truck_id=truck["id"], crew_id=crew1["id"],
                      window_start="2026-07-01T09:00:00Z", window_end="2026-07-01T12:00:00Z")

    _, jobB, _ = _booked_local_job(move_date="2026-07-01T11:00:00Z")
    res = api.create_dispatch(
        create_dispatch_payload(jobB["id"], truck["id"], crew2["id"],
                                window_start="2026-07-01T11:00:00Z",
                                window_end="2026-07-01T13:00:00Z", required_crew_size=3),
        DISPATCHER)
    validate_error(res, "ERR_TRUCK_DOUBLE_BOOKED", 409)


def test_crew_buffered_overlap_within_turnaround_rejected(api):
    """PRD §3.6: "the requested window expanded by a ninety-minute turnaround buffer
    on each side must not overlap any non-terminal dispatch already on that crew, so
    two crew windows separated by less than ninety minutes are rejected ... a
    violation is rejected with `ERR_CREW_DOUBLE_BOOKED`."

    Crew C holds 09:00-12:00 on truck T1; a second window 12:00-14:00 on a different
    truck T2 — touching the raw boundary but inside the buffer — is rejected,
    whereas the same touch is allowed for trucks.

    Design: Difficulty/resource_temporal_overlap/crew_buffered_overlap_within_turnaround_rejected
    """
    crew = register_crew(head_count=3)
    truck1 = register_truck(capacity_cubic_feet=2000)
    truck2 = register_truck(capacity_cubic_feet=2000)

    _, jobA, _ = _booked_local_job(move_date="2026-07-01T09:00:00Z")
    schedule_dispatch(jobA["id"], truck_id=truck1["id"], crew_id=crew["id"],
                      window_start="2026-07-01T09:00:00Z", window_end="2026-07-01T12:00:00Z")

    _, jobB, _ = _booked_local_job(move_date="2026-07-01T12:00:00Z")
    res = api.create_dispatch(
        create_dispatch_payload(jobB["id"], truck2["id"], crew["id"],
                                window_start="2026-07-01T12:00:00Z",
                                window_end="2026-07-01T14:00:00Z", required_crew_size=3),
        DISPATCHER)
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED", 409)


def test_crew_separated_by_more_than_buffer_allowed(api):
    """PRD §3.6: "windows exactly ninety minutes apart (the later start at or after
    the earlier end plus ninety minutes) are allowed."

    Second assertion on the buffered-crew-overlap instance (the positive twin): a
    crew window starting 13:30 — 90 minutes after the prior 12:00 end — on a
    different truck is accepted.

    Design: Difficulty/resource_temporal_overlap/crew_buffered_overlap_within_turnaround_rejected
    """
    crew = register_crew(head_count=3)
    truck1 = register_truck(capacity_cubic_feet=2000)
    truck2 = register_truck(capacity_cubic_feet=2000)

    _, jobA, _ = _booked_local_job(move_date="2026-07-01T09:00:00Z")
    schedule_dispatch(jobA["id"], truck_id=truck1["id"], crew_id=crew["id"],
                      window_start="2026-07-01T09:00:00Z", window_end="2026-07-01T12:00:00Z")

    _, jobB, _ = _booked_local_job(move_date="2026-07-01T13:30:00Z")
    res = api.create_dispatch(
        create_dispatch_payload(jobB["id"], truck2["id"], crew["id"],
                                window_start="2026-07-01T13:30:00Z",
                                window_end="2026-07-01T15:00:00Z", required_crew_size=3),
        DISPATCHER)
    dispB = validate_success(res, 201)
    assert dispB["status"] == "SCHEDULED"


def test_capacity_beats_truck_overlap_when_both_violated(api):
    """PRD §3.12: "then ... the dispatch window, capacity, crew-size, and overlap
    checks" — capacity precedes the overlap checks in the fixed evaluation order.
    PRD §3.6: "The truck must be big enough: the linked survey's `total_cubic_feet`
    must not exceed the truck's `capacity_cubic_feet`, or the request is rejected
    with `ERR_TRUCK_CAPACITY_EXCEEDED`."

    A new dispatch that BOTH exceeds a 100cf truck's capacity (370cf survey) AND
    overlaps that truck's existing 09:00-12:00 window returns the higher-priority
    ERR_TRUCK_CAPACITY_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_capacity_beats_truck_overlap
    """
    truck = register_truck(capacity_cubic_feet=100)
    crew = register_crew(head_count=3)

    # Existing small job (60cf <= 100) occupies 09:00-12:00.
    cust_id, jobA, surveyA, estimateA = setup_booked_job(
        service_type="LOCAL", items=[{"label": "box", "quantity": 20, "cubic_feet_each": 3}],
        job_overrides={"requested_move_date": "2026-07-01T09:00:00Z"})
    schedule_dispatch(jobA["id"], truck_id=truck["id"], crew_id=crew["id"],
                      window_start="2026-07-01T09:00:00Z", window_end="2026-07-01T12:00:00Z")

    # New big 370cf job overlapping 11:00-13:00 on the same too-small truck.
    _, jobB, surveyB = _booked_local_job(items=ITEMS_370CF, move_date="2026-07-01T11:00:00Z")
    res = api.create_dispatch(
        create_dispatch_payload(jobB["id"], truck["id"], crew["id"],
                                window_start="2026-07-01T11:00:00Z",
                                window_end="2026-07-01T13:00:00Z", required_crew_size=3),
        DISPATCHER)
    validate_error(res, "ERR_TRUCK_CAPACITY_EXCEEDED", 409)


def test_capacity_exceeded_alone_rejected(api):
    """PRD §3.6: "The truck must be big enough: the linked survey's
    `total_cubic_feet` must not exceed the truck's `capacity_cubic_feet`, or the
    request is rejected with `ERR_TRUCK_CAPACITY_EXCEEDED`."

    Second assertion on the capacity-beats-overlap priority instance, isolating the
    capacity check alone (370cf survey vs 100cf truck, no overlap present) so the
    same ERR_TRUCK_CAPACITY_EXCEEDED outcome is confirmed without the overlap.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_capacity_beats_truck_overlap
    """
    truck = register_truck(capacity_cubic_feet=100)
    crew = register_crew(head_count=3)
    _, job, survey = _booked_local_job(items=ITEMS_370CF, move_date="2026-07-01T09:00:00Z")
    res = api.create_dispatch(
        create_dispatch_payload(job["id"], truck["id"], crew["id"],
                                window_start="2026-07-01T09:00:00Z",
                                window_end="2026-07-01T12:00:00Z", required_crew_size=3),
        DISPATCHER)
    validate_error(res, "ERR_TRUCK_CAPACITY_EXCEEDED", 409)


def test_dispatch_invalid_window_rejected(api):
    """PRD §3.6: "The window itself must be well-formed: `window_end` must be
    strictly after `window_start`, or the request is rejected with
    `ERR_INVALID_WINDOW`."

    A dispatch with window_end == window_start returns ERR_INVALID_WINDOW.

    Design: Corner/validations/dispatch_invalid_window_returns_422
    """
    truck = register_truck(capacity_cubic_feet=2000)
    crew = register_crew(head_count=3)
    _, job, survey = _booked_local_job()
    res = api.create_dispatch(
        create_dispatch_payload(job["id"], truck["id"], crew["id"],
                                window_start="2026-07-01T12:00:00Z",
                                window_end="2026-07-01T12:00:00Z", required_crew_size=3),
        DISPATCHER)
    validate_error(res, "ERR_INVALID_WINDOW", 422)


def test_dispatch_crew_too_small_rejected(api):
    """PRD §3.6: "The crew must be big enough: the crew's `head_count` must be at
    least the dispatch's `required_crew_size`, or the request is rejected with
    `ERR_CREW_TOO_SMALL`."

    A crew of 2 against required_crew_size 4 returns ERR_CREW_TOO_SMALL.

    Design: Corner/validations/dispatch_crew_too_small_returns_409
    """
    truck = register_truck(capacity_cubic_feet=2000)
    crew = register_crew(head_count=2)
    _, job, survey = _booked_local_job()
    res = api.create_dispatch(
        create_dispatch_payload(job["id"], truck["id"], crew["id"],
                                window_start="2026-07-01T09:00:00Z",
                                window_end="2026-07-01T12:00:00Z", required_crew_size=4),
        DISPATCHER)
    validate_error(res, "ERR_CREW_TOO_SMALL", 409)


def test_list_dispatches_filtered_by_truck_id(api):
    """PRD §4: "GET | `/dispatches` | List dispatches (filter by move_job_id,
    truck_id, crew_id, status) | Dispatcher, PlatformAdmin, Customer"
    PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Filtering by truck_id returns that truck's scheduled dispatch.

    Design: Corner/endpoints/list_dispatches_filtered_by_truck_id
    """
    truck = register_truck(capacity_cubic_feet=2000)
    crew = register_crew(head_count=3)
    _, job, survey = _booked_local_job()
    disp = schedule_dispatch(job["id"], truck_id=truck["id"], crew_id=crew["id"])

    data, meta = validate_paginated(api.list_dispatches(DISPATCHER, params={"truck_id": truck["id"]}))
    assert any(d["id"] == disp["id"] for d in data)
    assert all(d["truck_id"] == truck["id"] for d in data)
