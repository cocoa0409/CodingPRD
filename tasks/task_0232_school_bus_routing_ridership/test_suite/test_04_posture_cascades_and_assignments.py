"""Route posture, the suspension cascade, optimistic concurrency, the substitute
chain, driver double-booking, the stop-time timeline, and validation-priority pairs.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_scheduled_trip,
    setup_boarding_trip,
    setup_route_with_driver,
    create_district_payload,
    create_route_payload,
    create_stop_payload,
    create_driver_payload,
    create_student_payload,
    make_admin_headers,
    make_driver_headers,
)

ADMIN = make_admin_headers()


# ===========================================================================
# Difficulty/transitive_cascade/route_suspend_cascades_trip_cancel_then_driver_free
# ===========================================================================
def test_suspend_cascades_scheduled_trip_to_cancelled(api):
    """PRD §3.8: "When suspension proceeds, it cascades as described in §2.5: every `SCHEDULED` trip on the route is driven to `CANCELLED`, and each such trip's driver is returned to `AVAILABLE` if it was `ON_DUTY` for that trip."

    Design: Difficulty/transitive_cascade/route_suspend_cascades_trip_cancel_then_driver_free
    """
    district, route, stops, driver, assignment, trip = setup_scheduled_trip(num_stops=1)
    route = get_success_data(api.get_route(route["id"], ADMIN))
    suspended = validate_success(
        api.change_posture(
            route["id"], {"action": "SUSPEND", "expected_route_version": route["version"]},
            ADMIN,
        ),
        200,
    )
    assert suspended["posture"] == "SUSPENDED"
    cancelled = validate_success(api.get_bus_trip(trip["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED", (
        "the SCHEDULED trip is cascaded to CANCELLED by SUSPEND"
    )


def test_suspend_cascade_leaves_driver_available(api):
    """PRD §3.8: "each such trip's driver is returned to `AVAILABLE` if it was `ON_DUTY` for that trip."
    PRD §3.5: "A driver's `status` starts at `AVAILABLE` and becomes `ON_DUTY` while a trip they drive is in `BOARDING` or `IN_TRANSIT`, returning to `AVAILABLE` when that trip completes, is cancelled, or is cancelled by a route-suspension cascade."

    Design: Difficulty/transitive_cascade/route_suspend_cascades_trip_cancel_then_driver_free
    """
    district, route, stops, driver, assignment, trip = setup_scheduled_trip(num_stops=1)
    # A SCHEDULED trip never set the driver ON_DUTY, so it remains AVAILABLE.
    route = get_success_data(api.get_route(route["id"], ADMIN))
    validate_success(
        api.change_posture(
            route["id"], {"action": "SUSPEND", "expected_route_version": route["version"]},
            ADMIN,
        ),
        200,
    )
    final_driver = validate_success(api.get_driver(driver["id"], ADMIN), 200)
    assert final_driver["status"] == "AVAILABLE", (
        "the driver of the cancelled SCHEDULED trip stays AVAILABLE"
    )


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/route_not_open_beats_route_full_on_approve
# ===========================================================================
def test_route_not_open_beats_route_full_on_approve(api):
    """PRD §3.4: "Second, the requested route must be fully open for new ridership: its posture must be `OPEN`. If the route is `RESTRICTED` or `SUSPENDED`, approval is rejected with `ERR_ROUTE_NOT_OPEN` — a `RESTRICTED` route continues to serve its existing riders but accepts no new assignment."
    PRD §3.4: "Third, the route must have a free seat: its `assigned_rider_count` must be strictly less than its `seat_capacity`; if the count has reached capacity, approval is rejected with `ERR_ROUTE_FULL`."

    Design: Difficulty/priority_pair_validation_conflict/route_not_open_beats_route_full_on_approve
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0,
                                walk_threshold_miles=1.5), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=1), ADMIN))
    stop = get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    # Rider A: approve -> route now full (count 1 == capacity 1).
    stu_a = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-A",
                               home_lat=40.05, home_lng=-75.0), ADMIN))
    app_a = get_success_data(api.create_application(
        {"district_id": district["id"], "student_id": stu_a["id"],
         "requested_route_id": route["id"], "requested_stop_id": stop["id"]}, ADMIN))
    get_success_data(api.start_review(app_a["id"], ADMIN))
    validate_success(api.approve_application(app_a["id"], ADMIN), 200)
    # Rider B: eligible, UNDER_REVIEW.
    stu_b = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-2", "RF-B",
                               home_lat=40.05, home_lng=-75.0, grade=6), ADMIN))
    app_b = get_success_data(api.create_application(
        {"district_id": district["id"], "student_id": stu_b["id"],
         "requested_route_id": route["id"], "requested_stop_id": stop["id"]}, ADMIN))
    get_success_data(api.start_review(app_b["id"], ADMIN))
    # RESTRICT the (already full) route.
    route = get_success_data(api.get_route(route["id"], ADMIN))
    get_success_data(api.change_posture(
        route["id"], {"action": "RESTRICT", "expected_route_version": route["version"]},
        ADMIN))
    # Approve B: ROUTE_NOT_OPEN (checked before ROUTE_FULL) wins.
    res = api.approve_application(app_b["id"], ADMIN)
    validate_error(res, "ERR_ROUTE_NOT_OPEN", 409)


def test_route_not_open_alone_blocks_approval_on_restricted_route(api):
    """PRD §3.4: "the requested route must be fully open for new ridership: its posture must be `OPEN`. If the route is `RESTRICTED` or `SUSPENDED`, approval is rejected with `ERR_ROUTE_NOT_OPEN` — a `RESTRICTED` route continues to serve its existing riders but accepts no new assignment."

    Design: Difficulty/priority_pair_validation_conflict/route_not_open_beats_route_full_on_approve
    """
    # Isolated single-failure scenario: a RESTRICTED route with free seats fails ONLY
    # the posture check, proving ERR_ROUTE_NOT_OPEN fires on its own (not entangled
    # with ROUTE_FULL).
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0,
                                walk_threshold_miles=1.5), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    stop = get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    student = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-1",
                               home_lat=40.05, home_lng=-75.0), ADMIN))
    app = get_success_data(api.create_application(
        {"district_id": district["id"], "student_id": student["id"],
         "requested_route_id": route["id"], "requested_stop_id": stop["id"]}, ADMIN))
    get_success_data(api.start_review(app["id"], ADMIN))
    # RESTRICT the route (seats are free; only posture is the problem).
    get_success_data(api.change_posture(
        route["id"], {"action": "RESTRICT", "expected_route_version": route["version"]},
        ADMIN))
    res = api.approve_application(app["id"], ADMIN)
    validate_error(res, "ERR_ROUTE_NOT_OPEN", 409)


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/stale_version_beats_trip_in_flight_on_suspend
# ===========================================================================
def test_stale_version_beats_trip_in_flight_on_suspend(api):
    """PRD §2.8: "because the version check outranks the state-legality check, a stale-version posture write surfaces `ERR_STALE_VERSION` rather than `ERR_INVALID_STATE`."
    PRD §2.10: "if another writer has advanced the route's `version` since then — for instance, an earlier posture write already flipped the posture and bumped the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_trip_in_flight_on_suspend
    """
    # r_v0 captured before the driver-assignment bumped the route version; a BOARDING
    # (in-flight) trip exists. SUSPEND with the stale r_v0 -> STALE_VERSION (412),
    # outranking the in-flight safety check.
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=20), ADMIN))
    stale_version = route["version"]  # captured before the assignment bump
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    driver = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Drv A"), ADMIN))
    asg = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": stale_version}, ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": asg["id"]}, ADMIN))
    validate_success(api.start_boarding(trip["id"], make_driver_headers(driver["id"])), 200)
    # SUSPEND with the now-stale version while the trip is in-flight.
    res = api.change_posture(
        route["id"], {"action": "SUSPEND", "expected_route_version": stale_version}, ADMIN
    )
    validate_error(res, "ERR_STALE_VERSION", 412)


def test_stale_version_alone_rejects_posture_change(api):
    """PRD §2.10: "A posture-change request must carry `expected_route_version` carrying the route version the client last observed; if another writer has advanced the route's `version` since then — for instance, an earlier posture write already flipped the posture and bumped the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_trip_in_flight_on_suspend
    """
    # Isolated single-failure scenario: an earlier RESTRICT bumps the version; a
    # second posture write replaying the pre-RESTRICT version fails ONLY the
    # stale-version check (no in-flight trip involved), proving ERR_STALE_VERSION
    # fires on its own.
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=20), ADMIN))
    stale_version = route["version"]
    get_success_data(api.change_posture(
        route["id"], {"action": "RESTRICT", "expected_route_version": stale_version},
        ADMIN))
    # Replay the stale pre-RESTRICT version on a SUSPEND.
    res = api.change_posture(
        route["id"], {"action": "SUSPEND", "expected_route_version": stale_version}, ADMIN
    )
    validate_error(res, "ERR_STALE_VERSION", 412)


# ===========================================================================
# Difficulty/cross_entity_state_dependency/start_boarding_requires_active_driver_assignment
# ===========================================================================
def test_start_boarding_requires_active_assignment(api):
    """PRD §3.6: "That assignment's `status` must be `ACTIVE`, or boarding is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE`."
    PRD §3.5: "When a valid substitute is created, the named primary assignment transitions from `ACTIVE` to `SUPERSEDED`, while the newly created substitute itself remains `ACTIVE`; this forms a self-referential substitute chain in which each substitute points back at the assignment it covers."

    Design: Difficulty/cross_entity_state_dependency/start_boarding_requires_active_driver_assignment
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=20), ADMIN))
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    drv_p = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Primary Drv"), ADMIN))
    drv_s = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Sub Drv", is_substitute=True),
        ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    asg_p = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": drv_p["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": asg_p["id"]}, ADMIN))
    # Substitute supersedes the primary.
    route = get_success_data(api.get_route(route["id"], ADMIN))
    get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": drv_s["id"], "role": "SUBSTITUTE",
         "replaces_assignment_id": asg_p["id"],
         "expected_route_version": route["version"]}, ADMIN))
    # Primary assignment is now SUPERSEDED.
    asg_p_after = validate_success(api.get_driver_assignment(asg_p["id"], ADMIN), 200)
    assert asg_p_after["status"] == "SUPERSEDED"
    # start-boarding on the trip pinned to the superseded primary is rejected.
    res = api.start_boarding(trip["id"], make_driver_headers(drv_p["id"]))
    validate_error(res, "ERR_ASSIGNMENT_NOT_ACTIVE", 409)


def test_start_boarding_succeeds_when_assignment_active(api):
    """PRD §3.6: "The acting driver must be the driver named by the trip's `driver_assignment_id`. That assignment's `status` must be `ACTIVE`, or boarding is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/start_boarding_requires_active_driver_assignment
    """
    # The positive cross-entity case: an ACTIVE PRIMARY assignment lets its driver
    # board, confirming the gate is on the assignment's status (not unconditional).
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=20), ADMIN))
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    driver = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Drv A"), ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    asg = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    assert asg["status"] == "ACTIVE"
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": asg["id"]}, ADMIN))
    boarded = validate_success(
        api.start_boarding(trip["id"], make_driver_headers(driver["id"])), 200
    )
    assert boarded["status"] == "BOARDING", (
        "boarding succeeds while the trip's DriverAssignment is ACTIVE"
    )


# ===========================================================================
# Difficulty/resource_temporal_overlap/driver_double_booked_in_flight_overlap
# ===========================================================================
def test_driver_double_booked_rejected(api):
    """PRD §3.6: "the driver must not already be running another in-flight trip — no other bus trip with the same driver may be in `BOARDING` or `IN_TRANSIT` — because a driver occupies at most one in-flight slot at a time; a second concurrent trip is rejected with `ERR_DRIVER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/driver_double_booked_in_flight_overlap
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    driver = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Busy Drv"), ADMIN))
    trips = []
    for name in ("RA", "RB"):
        route = get_success_data(api.create_route(
            create_route_payload(district["id"], name=name, seat_capacity=20), ADMIN))
        get_success_data(api.create_stop(
            create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
        route = get_success_data(api.get_route(route["id"], ADMIN))
        asg = get_success_data(api.create_driver_assignment(
            route["id"],
            {"driver_id": driver["id"], "role": "PRIMARY",
             "expected_route_version": route["version"]}, ADMIN))
        trip = get_success_data(api.create_bus_trip(
            {"route_id": route["id"], "driver_assignment_id": asg["id"]}, ADMIN))
        trips.append(trip)
    drv = make_driver_headers(driver["id"])
    # First trip BOARDING (driver in-flight).
    validate_success(api.start_boarding(trips[0]["id"], drv), 200)
    # Second concurrent trip for the same driver -> ERR_DRIVER_DOUBLE_BOOKED.
    res = api.start_boarding(trips[1]["id"], drv)
    validate_error(res, "ERR_DRIVER_DOUBLE_BOOKED", 409)


def test_driver_free_after_first_trip_can_board_second(api):
    """PRD §3.6: "no other bus trip with the same driver may be in `BOARDING` or `IN_TRANSIT` — because a driver occupies at most one in-flight slot at a time; a second concurrent trip is rejected with `ERR_DRIVER_DOUBLE_BOOKED`."
    PRD §3.6: "Completion moves the trip to `COMPLETED`, sets `eta_next_stop_minutes` to null, and returns the driver to `AVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/driver_double_booked_in_flight_overlap
    """
    # Once the first trip completes the driver leaves its in-flight slot, so the
    # same driver may board a second trip — the X+1 side of the point-capacity rule.
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    driver = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Busy Drv"), ADMIN))
    trips = []
    for name in ("RA", "RB"):
        route = get_success_data(api.create_route(
            create_route_payload(district["id"], name=name, seat_capacity=20), ADMIN))
        get_success_data(api.create_stop(
            create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
        get_success_data(api.create_stop(
            create_stop_payload(route["id"], 2, "2026-09-01T07:10:00Z",
                                lat=40.01, lng=-75.0), ADMIN))
        route = get_success_data(api.get_route(route["id"], ADMIN))
        asg = get_success_data(api.create_driver_assignment(
            route["id"],
            {"driver_id": driver["id"], "role": "PRIMARY",
             "expected_route_version": route["version"]}, ADMIN))
        trip = get_success_data(api.create_bus_trip(
            {"route_id": route["id"], "driver_assignment_id": asg["id"]}, ADMIN))
        trips.append(trip)
    drv = make_driver_headers(driver["id"])
    # Run the first trip all the way to COMPLETED (no taps -> onboard_count 0).
    validate_success(api.start_boarding(trips[0]["id"], drv), 200)
    validate_success(api.depart_stop(trips[0]["id"], {"stop_sequence": 1}, drv), 200)
    validate_success(api.complete_trip(trips[0]["id"], drv), 200)
    # The driver's slot is now free; the second trip boards without double-booking.
    boarded = validate_success(api.start_boarding(trips[1]["id"], drv), 200)
    assert boarded["status"] == "BOARDING", (
        "the freed driver may board a second trip once the first is no longer in-flight"
    )


# ===========================================================================
# Difficulty/resource_temporal_overlap/stop_time_order_timeline_inversion
# ===========================================================================
def test_stop_time_order_inversion_rejected(api):
    """PRD §3.1: "a new stop's `scheduled_departure` must be strictly later than the departure of every existing stop on the route with a lower `sequence`, and strictly earlier than the departure of every existing stop with a higher `sequence`. A departure that ties or inverts against an adjacent stop's time is rejected with `ERR_STOP_TIME_ORDER`."

    Design: Difficulty/resource_temporal_overlap/stop_time_order_timeline_inversion
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=20), ADMIN))
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    # seq2 @ 06:55Z precedes seq1 @ 07:00Z -> timeline inversion.
    res = api.create_stop(
        create_stop_payload(route["id"], 2, "2026-09-01T06:55:00Z",
                            lat=40.01, lng=-75.0),
        ADMIN,
    )
    validate_error(res, "ERR_STOP_TIME_ORDER", 422)


def test_stop_time_order_increasing_timeline_accepted(api):
    """PRD §3.1: "the stops of a route form a strictly increasing one-dimensional timeline: a new stop's `scheduled_departure` must be strictly later than the departure of every existing stop on the route with a lower `sequence`, and strictly earlier than the departure of every existing stop with a higher `sequence`."

    Design: Difficulty/resource_temporal_overlap/stop_time_order_timeline_inversion
    """
    # The complementary accepted case: a seq-2 time strictly after seq-1 respects
    # the strictly-increasing timeline and is created (201).
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=20), ADMIN))
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    stop2 = validate_success(
        api.create_stop(
            create_stop_payload(route["id"], 2, "2026-09-01T07:05:00Z",
                                lat=40.01, lng=-75.0),
            ADMIN,
        ),
        201,
    )
    assert stop2["sequence"] == 2, (
        "a stop whose time strictly increases over the lower-sequence stop is accepted"
    )


# ===========================================================================
# Corner/errors/substitute_without_replaces_returns_substitute_rule
# ===========================================================================
def test_substitute_without_replaces_returns_substitute_rule(api):
    """PRD §3.5: "Any violation of these conditions — a missing or invalid replaces target, a replaced assignment that is not an active primary on the same route, or a substitute-only driver assigned as primary — is rejected with `ERR_SUBSTITUTE_RULE`."

    Design: Corner/errors/substitute_without_replaces_returns_substitute_rule
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    drv_s = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Sub", is_substitute=True),
        ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    res = api.create_driver_assignment(
        route["id"],
        {"driver_id": drv_s["id"], "role": "SUBSTITUTE",
         "expected_route_version": route["version"]},
        ADMIN,
    )
    validate_error(res, "ERR_SUBSTITUTE_RULE", 409)


# ===========================================================================
# Corner/errors/substitute_driver_as_primary_returns_substitute_rule
# ===========================================================================
def test_substitute_driver_as_primary_returns_substitute_rule(api):
    """PRD §3.5: "a driver flagged `is_substitute` may never hold a `PRIMARY` assignment... a substitute-only driver assigned as primary — is rejected with `ERR_SUBSTITUTE_RULE`."

    Design: Corner/errors/substitute_driver_as_primary_returns_substitute_rule
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    drv_s = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Sub", is_substitute=True),
        ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    res = api.create_driver_assignment(
        route["id"],
        {"driver_id": drv_s["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]},
        ADMIN,
    )
    validate_error(res, "ERR_SUBSTITUTE_RULE", 409)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_correct_version_posture_succeeds_and_bumps_version
# ===========================================================================
def test_occ_correct_version_posture_succeeds_and_bumps_version(api):
    """PRD §3.8: "Every posture change is version-guarded and must carry `expected_route_version`; a mismatch is rejected with `ERR_STALE_VERSION` as described in §2.10, and every successful change increments the route's `version` by one."
    PRD §3.8: "Restricting takes a route from `OPEN` to `RESTRICTED`; this is legal only from `OPEN`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_posture_succeeds_and_bumps_version
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    assert route["version"] == 1
    res = api.change_posture(
        route["id"], {"action": "RESTRICT", "expected_route_version": route["version"]},
        ADMIN,
    )
    updated = validate_success(res, 200)
    assert updated["posture"] == "RESTRICTED"
    assert updated["version"] == 2, "a successful posture change increments version by 1"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/substitute_assign_stale_route_returns_stale_version
# ===========================================================================
def test_substitute_assign_stale_route_returns_stale_version(api):
    """PRD §2.10: "Because a substitute assignment legitimately supersedes the primary it covers, a writer holding a stale route version — one whose version was already advanced by an earlier assignment creation — is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently superseding a primary on a route it has not observed in its current form."

    Design: Corner/cross_cutting_complexity_layers/substitute_assign_stale_route_returns_stale_version
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    stale_version = route["version"]  # captured before the PRIMARY bumps the version
    drv_p = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Primary"), ADMIN))
    drv_s = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Sub", is_substitute=True),
        ADMIN))
    asg_p = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": drv_p["id"], "role": "PRIMARY",
         "expected_route_version": stale_version}, ADMIN))
    # Replay the stale pre-primary version on the substitute create.
    res = api.create_driver_assignment(
        route["id"],
        {"driver_id": drv_s["id"], "role": "SUBSTITUTE",
         "replaces_assignment_id": asg_p["id"],
         "expected_route_version": stale_version},
        ADMIN,
    )
    validate_error(res, "ERR_STALE_VERSION", 412)
