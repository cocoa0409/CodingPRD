"""Crew training thresholds, rolling duty windows, duty limits, and overlap."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_owner_and_aircraft, setup_dispatch_ready, setup_completed_trip,
    create_crew_member, qualify_crew_member, create_trip, assign_duty,
    set_logical_clock, create_assignment_payload,
    complete_trip, schedule_trip, file_accepted_insurance,
    DUTY_LIMIT_7D_HOURS, TEST_USERS,
)

FO = TEST_USERS["flight_ops_headers"]


def test_complete_training_below_minimum_rejected(api):
    """PRD §3.3: "Completing training requires the request to carry
    `training_hours` of at least 25 hours and `check_ride_passed` equal to
    true; a submission failing either condition is rejected with
    `ERR_INSUFFICIENT_TRAINING`. On success, the crew member moves from
    `IN_TRAINING` to `QUALIFIED` and the supplied `training_hours` are added to
    `training_hours_accumulated`."

    Design: Corner/validations/complete_training_below_minimum_rejected
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N460JX")
    crew = create_crew_member(aircraft["id"])
    validate_success(api.begin_training(crew["id"], FO), 200)

    too_few = api.complete_training(
        crew["id"], {"training_hours": 24.9, "check_ride_passed": True}, FO
    )
    validate_error(too_few, "ERR_INSUFFICIENT_TRAINING", expected_status=422)

    enough = validate_success(
        api.complete_training(
            crew["id"], {"training_hours": 25.0, "check_ride_passed": True}, FO
        ),
        200,
    )
    assert enough["status"] == "QUALIFIED"
    assert enough["training_hours_accumulated"] == pytest.approx(25.0)


def test_duty_window_lower_bound_exclusive(api):
    """PRD §3.3: "each crew member carries two computed accumulators,
    `duty_hours_7d` and `duty_hours_28d`, which sum `duty_hours` over the crew
    member's assignments in `ASSIGNED` or `COMPLETED` status whose
    `duty_end_at` falls inside the trailing seven-day or twenty-eight-day
    window ending at the logical clock's now — window bounds are
    lower-exclusive, upper-inclusive, and an assignment whose window membership
    straddles a bound counts in full."

    Design: Corner/calculations/duty_window_lower_bound_exclusive
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N350JX")
    captain = qualify_crew_member(aircraft["id"])
    set_logical_clock("2026-08-10T00:00:00Z")
    trip = create_trip(
        aircraft["id"], departure_at="2026-08-02T20:00:00Z", block_hours_est=4.0
    )

    # duty_end_at exactly at now-7d (2026-08-03T00:00:00Z): outside (now-7d, now].
    assignment = validate_success(
        api.create_assignment(
            create_assignment_payload(
                trip["id"], captain["id"], duty_role="PIC",
                duty_start_at="2026-08-02T20:00:00Z",
                duty_end_at="2026-08-03T00:00:00Z",
            ),
            FO,
        ),
        201,
    )
    assert assignment["duty_hours"] == pytest.approx(4.0)

    crew = validate_success(api.get_crew_member(captain["id"], FO), 200)
    assert crew["duty_hours_7d"] == pytest.approx(0.0), (
        f"duty ending exactly at the exclusive lower bound is outside the "
        f"7-day window, got {crew['duty_hours_7d']}"
    )
    assert crew["duty_hours_28d"] == pytest.approx(4.0)


def _setup_crew_at_duty_boundary(api):
    """Captain with 30.0h of 7-day duty at clock 2026-08-10T00:00:00Z.

    Returns (captain, trip_t3, trip_t4): trip_t3 carries the assignment that
    lands the projected total exactly on the 40h limit; trip_t4 is the vehicle
    for the 0.1h excess attempt.
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N130JX")
    captain = qualify_crew_member(aircraft["id"])
    set_logical_clock("2026-08-10T00:00:00Z")
    trips = {
        day: create_trip(aircraft["id"], departure_at=f"2026-08-{day:02d}T09:00:00Z",
                         block_hours_est=est)
        for day, est in ((3, 3.0), (5, 3.0), (8, 3.0), (9, 0.1))
    }
    assign_duty(trips[3]["id"], captain["id"], "PIC",
                "2026-08-03T08:00:00Z", "2026-08-04T04:00:00Z")  # 20.0h
    assign_duty(trips[5]["id"], captain["id"], "PIC",
                "2026-08-05T08:00:00Z", "2026-08-05T18:00:00Z")  # 10.0h
    return captain, trips


def test_duty_limit_exact_boundary_passes(api):
    """PRD §3.3: "The new assignment is rejected with `ERR_DUTY_LIMIT_EXCEEDED`
    when the projected seven-day total (the current `duty_hours_7d` plus the
    new `duty_hours`) is strictly greater than 40 hours, or when the projected
    twenty-eight-day total is strictly greater than 120 hours; landing exactly
    on either limit is allowed."

    Design: Difficulty/boundary_precision_check/duty_limit_exact_boundary_passes_and_excess_rejected
    """
    captain, trips = _setup_crew_at_duty_boundary(api)

    # Third assignment: 10.0h ending 2026-08-08T18:00 — projected 40.0 == limit.
    created = validate_success(
        api.create_assignment(
            create_assignment_payload(
                trips[8]["id"], captain["id"], duty_role="PIC",
                duty_start_at="2026-08-08T08:00:00Z",
                duty_end_at="2026-08-08T18:00:00Z",
            ),
            FO,
        ),
        201,
    )
    assert created["duty_hours"] == pytest.approx(10.0)
    assert created["status"] == "ASSIGNED"

    crew = validate_success(api.get_crew_member(captain["id"], FO), 200)
    assert crew["duty_hours_7d"] == pytest.approx(DUTY_LIMIT_7D_HOURS), (
        f"projected total lands exactly on the 40h limit and must be accepted, "
        f"got {crew['duty_hours_7d']}"
    )


def test_duty_limit_excess_rejected(api):
    """PRD §3.3: "The new assignment is rejected with `ERR_DUTY_LIMIT_EXCEEDED`
    when the projected seven-day total (the current `duty_hours_7d` plus the
    new `duty_hours`) is strictly greater than 40 hours, or when the projected
    twenty-eight-day total is strictly greater than 120 hours; landing exactly
    on either limit is allowed."

    Design: Difficulty/boundary_precision_check/duty_limit_exact_boundary_passes_and_excess_rejected
    """
    captain, trips = _setup_crew_at_duty_boundary(api)
    assign_duty(trips[8]["id"], captain["id"], "PIC",
                "2026-08-08T08:00:00Z", "2026-08-08T18:00:00Z")  # now at 40.0

    # 0.1h more: projected 40.1 > 40 → rejected.
    excess = api.create_assignment(
        create_assignment_payload(
            trips[9]["id"], captain["id"], duty_role="PIC",
            duty_start_at="2026-08-09T08:00:00Z",
            duty_end_at="2026-08-09T08:06:00Z",
        ),
        FO,
    )
    validate_error(excess, "ERR_DUTY_LIMIT_EXCEEDED", expected_status=422)

    crew = validate_success(api.get_crew_member(captain["id"], FO), 200)
    assert crew["duty_hours_7d"] == pytest.approx(DUTY_LIMIT_7D_HOURS), (
        "rejected assignment must not change the accumulator"
    )


def _setup_crew_overlap_scenario(api):
    """QUALIFIED captain + three auto-approved trips; returns (captain, trips)."""
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N170JX")
    captain = qualify_crew_member(aircraft["id"])
    trips = [
        create_trip(aircraft["id"], departure_at=f"2026-08-05T{hour:02d}:00:00Z",
                    block_hours_est=est)
        for hour, est in ((9, 3.0), (13, 3.0), (16, 2.0))
    ]
    assign_duty(trips[0]["id"], captain["id"], "PIC",
                "2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z")
    return captain, trips


def test_crew_duty_touching_windows_accepted(api):
    """PRD §3.3: "Second, duty-window overlap: the new half-open window from
    `duty_start_at` to `duty_end_at` must have a strictly empty intersection
    with every other `ASSIGNED` or `COMPLETED` duty window of the same crew
    member; two windows that merely touch — one's end equal to the other's
    start — do not conflict, but any strictly positive intersection is rejected
    with `ERR_CREW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/crew_duty_windows_half_open_adjacency
    """
    captain, trips = _setup_crew_overlap_scenario(api)

    # New window starts exactly when the existing one ends (12:00 == 12:00).
    touching = validate_success(
        api.create_assignment(
            create_assignment_payload(
                trips[1]["id"], captain["id"], duty_role="PIC",
                duty_start_at="2026-08-05T12:00:00Z",
                duty_end_at="2026-08-05T16:00:00Z",
            ),
            FO,
        ),
        201,
    )
    assert touching["status"] == "ASSIGNED"
    assert touching["duty_hours"] == pytest.approx(4.0)


def test_crew_duty_overlapping_window_rejected(api):
    """PRD §3.3: "Second, duty-window overlap: the new half-open window from
    `duty_start_at` to `duty_end_at` must have a strictly empty intersection
    with every other `ASSIGNED` or `COMPLETED` duty window of the same crew
    member; two windows that merely touch — one's end equal to the other's
    start — do not conflict, but any strictly positive intersection is rejected
    with `ERR_CREW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/crew_duty_windows_half_open_adjacency
    """
    captain, trips = _setup_crew_overlap_scenario(api)
    assign_duty(trips[1]["id"], captain["id"], "PIC",
                "2026-08-05T12:00:00Z", "2026-08-05T16:00:00Z")

    # 15:00-18:00 has a strictly positive intersection with 12:00-16:00.
    overlapping = api.create_assignment(
        create_assignment_payload(
            trips[2]["id"], captain["id"], duty_role="PIC",
            duty_start_at="2026-08-05T15:00:00Z",
            duty_end_at="2026-08-05T18:00:00Z",
        ),
        FO,
    )
    validate_error(overlapping, "ERR_CREW_OVERLAP", expected_status=409)

    data, meta = validate_paginated(
        api.list_assignments(FO, params={"crew_member_id": captain["id"]})
    )
    assert meta["total_count"] == 2, (
        f"only the two accepted assignments may exist, got {meta['total_count']}"
    )
    assert all(a["status"] == "ASSIGNED" for a in data)


def test_crew_duty_hours_rise_on_assignment(api):
    """PRD §3.3: "Releasing an assignment (performed by the `FlightOpsManager`,
    or by the system during trip cancellation or crew deactivation) moves it
    from `ASSIGNED` to `RELEASED`; the crew member's `duty_hours_7d` and
    `duty_hours_28d` decrease by the released assignment's `duty_hours` while
    window membership is otherwise unchanged."

    Design: Difficulty/compensating_invariant/crew_duty_hours_conserved_across_assign_and_release
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N200JB")
    captain = qualify_crew_member(aircraft["id"])
    set_logical_clock("2026-08-10T00:00:00Z")
    t0 = create_trip(aircraft["id"], departure_at="2026-08-05T09:00:00Z",
                     block_hours_est=3.0)
    t1 = create_trip(aircraft["id"], departure_at="2026-08-08T09:00:00Z",
                     block_hours_est=2.0, arrive_icao="KBOS")
    assign_duty(t0["id"], captain["id"], "PIC",
                "2026-08-05T08:00:00Z", "2026-08-05T18:00:00Z")  # 10.0h in window

    created = assign_duty(t1["id"], captain["id"], "PIC",
                          "2026-08-08T08:00:00Z", "2026-08-08T16:00:00Z")  # 8.0h
    assert created["duty_hours"] == pytest.approx(8.0)

    crew = validate_success(api.get_crew_member(captain["id"], FO), 200)
    assert crew["duty_hours_7d"] == pytest.approx(18.0), (
        f"10.0 + 8.0 in-window hours expected, got {crew['duty_hours_7d']}"
    )
    assert crew["duty_hours_28d"] == pytest.approx(18.0)


def test_crew_duty_hours_restore_on_release(api):
    """PRD §3.3: "Releasing an assignment (performed by the `FlightOpsManager`,
    or by the system during trip cancellation or crew deactivation) moves it
    from `ASSIGNED` to `RELEASED`; the crew member's `duty_hours_7d` and
    `duty_hours_28d` decrease by the released assignment's `duty_hours` while
    window membership is otherwise unchanged."

    Design: Difficulty/compensating_invariant/crew_duty_hours_conserved_across_assign_and_release
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N200JB")
    captain = qualify_crew_member(aircraft["id"])
    set_logical_clock("2026-08-10T00:00:00Z")
    t0 = create_trip(aircraft["id"], departure_at="2026-08-05T09:00:00Z",
                     block_hours_est=3.0)
    t1 = create_trip(aircraft["id"], departure_at="2026-08-08T09:00:00Z",
                     block_hours_est=2.0, arrive_icao="KBOS")
    assign_duty(t0["id"], captain["id"], "PIC",
                "2026-08-05T08:00:00Z", "2026-08-05T18:00:00Z")
    a1 = assign_duty(t1["id"], captain["id"], "PIC",
                     "2026-08-08T08:00:00Z", "2026-08-08T16:00:00Z")

    released = validate_success(api.delete_assignment(a1["id"], FO), 200)
    assert released["status"] == "RELEASED"

    crew = validate_success(api.get_crew_member(captain["id"], FO), 200)
    assert crew["duty_hours_7d"] == pytest.approx(10.0), (
        f"release must subtract the released duty_hours, got {crew['duty_hours_7d']}"
    )
    assert crew["duty_hours_28d"] == pytest.approx(10.0)


def _setup_inactive_captain_with_completed_duty(api):
    """Captain QUALIFIED → completed PIC duty 08:00-12:00 on trip T1 →
    deactivated (INACTIVE). A second auto-approved trip T2 awaits assignment.
    Returns (scenario, captain, t1, t2)."""
    scenario = setup_dispatch_ready(tail_number="N120JX")
    aircraft_id = scenario["aircraft"]["id"]
    captain = scenario["captain"]
    first_officer = scenario["first_officer"]
    t1 = setup_completed_trip(
        aircraft_id, scenario["owner"]["id"], captain, first_officer,
        trip_use="OWNER_USE", departure_at="2026-08-05T09:00:00Z",
        block_hours_est=3.0,
        pic_window=("2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z"),
        sic_window=("2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z"),
        block_hours_actual=3.0,
    )
    assert t1["status"] == "COMPLETED"
    validate_success(api.deactivate_crew(captain["id"], FO), 200)
    t2 = create_trip(aircraft_id, departure_at="2026-08-05T13:00:00Z",
                     block_hours_est=2.0, arrive_icao="KBOS")
    return scenario, captain, t1, t2


def test_unqualified_crew_rejected_before_overlap_check(api):
    """PRD §3.3: "The crew member must be `QUALIFIED`, else
    `ERR_CREW_NOT_QUALIFIED`."
    PRD §2.8: "Within the assignment gate stack, the crew-member-qualified
    check runs first, then the duty-limit check, then the duty-overlap check."

    Design: Difficulty/priority_pair_validation_conflict/crew_qualification_check_precedes_overlap_check
    """
    _scenario, captain, _t1, t2 = _setup_inactive_captain_with_completed_duty(api)

    # Window 11:00-15:00 also overlaps the captain's COMPLETED 08:00-12:00 duty,
    # but the qualification gate runs first.
    res = api.create_assignment(
        create_assignment_payload(
            t2["id"], captain["id"], duty_role="PIC",
            duty_start_at="2026-08-05T11:00:00Z",
            duty_end_at="2026-08-05T15:00:00Z",
        ),
        FO,
    )
    validate_error(res, "ERR_CREW_NOT_QUALIFIED", expected_status=409)


def test_unqualified_crew_rejection_leaves_no_assignment(api):
    """PRD §3.3: "The crew member must be `QUALIFIED`, else
    `ERR_CREW_NOT_QUALIFIED`."
    PRD §2.8: "Within the assignment gate stack, the crew-member-qualified
    check runs first, then the duty-limit check, then the duty-overlap check."

    Design: Difficulty/priority_pair_validation_conflict/crew_qualification_check_precedes_overlap_check
    """
    _scenario, captain, _t1, t2 = _setup_inactive_captain_with_completed_duty(api)

    res = api.create_assignment(
        create_assignment_payload(
            t2["id"], captain["id"], duty_role="PIC",
            duty_start_at="2026-08-05T11:00:00Z",
            duty_end_at="2026-08-05T15:00:00Z",
        ),
        FO,
    )
    validate_error(res, "ERR_CREW_NOT_QUALIFIED", expected_status=409)

    data, meta = validate_paginated(
        api.list_assignments(FO, params={"trip_id": t2["id"]})
    )
    assert meta["total_count"] == 0, (
        f"rejected assignment must not persist, got {meta['total_count']}"
    )
    crew = validate_success(api.get_crew_member(captain["id"], FO), 200)
    assert crew["status"] == "INACTIVE"
