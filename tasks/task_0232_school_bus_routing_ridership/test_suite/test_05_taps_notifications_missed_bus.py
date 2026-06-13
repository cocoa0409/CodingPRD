"""RFID taps, onboard accounting, parent notifications, the incident cascade, and
the missed-bus protocol (window + lifecycle).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_boarding_trip_with_approved_rider,
    setup_two_stop_route,
    create_district_payload,
    create_route_payload,
    create_stop_payload,
    create_driver_payload,
    create_student_payload,
    make_admin_headers,
    make_driver_headers,
    make_parent_headers,
)

ADMIN = make_admin_headers()


# ===========================================================================
# Difficulty/cross_entity_state_dependency/tap_requires_approved_application_on_route
# ===========================================================================
def test_tap_requires_approved_application_on_route(api):
    """PRD §3.7: "The tapped student must have an `APPROVED` ridership application whose `assigned_route_id` is this trip's route; a student with no such assignment is rejected with `ERR_NOT_ASSIGNED_RIDER`."

    Design: Difficulty/cross_entity_state_dependency/tap_requires_approved_application_on_route
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=20), ADMIN))
    stop = get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    driver = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Drv A"), ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    asg = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    student = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-X",
                               home_lat=40.05, home_lng=-75.0), ADMIN))
    # Application is only SUBMITTED (never approved).
    get_success_data(api.create_application(
        {"district_id": district["id"], "student_id": student["id"],
         "requested_route_id": route["id"], "requested_stop_id": stop["id"]}, ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": asg["id"]}, ADMIN))
    drv = make_driver_headers(driver["id"])
    validate_success(api.start_boarding(trip["id"], drv), 200)
    res = api.record_tap(
        trip["id"], {"rfid_uid": "RF-X", "direction": "TAP_ON", "stop_sequence": 1}, drv
    )
    validate_error(res, "ERR_NOT_ASSIGNED_RIDER", 409)


def test_tap_succeeds_for_approved_rider(api):
    """PRD §3.7: "Each accepted tap recomputes the trip's `onboard_count` and appends a parent notification of kind `TAP_ON` or `TAP_OFF` for the tapped student's parent."

    Design: Difficulty/cross_entity_state_dependency/tap_requires_approved_application_on_route
    """
    district, route, stops, driver, assignment, trip, student, application = (
        setup_boarding_trip_with_approved_rider(num_stops=1, rfid_uid="RF-R")
    )
    drv = make_driver_headers(driver["id"])
    tap = validate_success(
        api.record_tap(trip["id"], {"rfid_uid": "RF-R", "direction": "TAP_ON",
                                    "stop_sequence": 1}, drv), 201)
    assert tap["direction"] == "TAP_ON"
    refreshed = validate_success(api.get_bus_trip(trip["id"], drv), 200)
    assert refreshed["onboard_count"] == 1, "an accepted TAP_ON raises onboard_count"


# ===========================================================================
# Corner/calculations/onboard_count_two_riders_projection
# ===========================================================================
def test_onboard_count_two_riders_projection(api):
    """PRD §3.6: "To compute `onboard_count`, the system replays every tap event for the trip in ascending `created_at` order, breaking ties by ascending `stop_sequence` (never by id): each `TAP_ON` adds the student to the onboard set and each `TAP_OFF` removes them, and the resulting set size is the count."

    Design: Corner/calculations/onboard_count_two_riders_projection
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0,
                                walk_threshold_miles=1.5), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    stop = get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    driver = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Drv A"), ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    asg = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    # Two approved riders.
    for pid, rfid, lat in (("par-1", "RF-A", 40.05), ("par-2", "RF-B", 40.06)):
        stu = get_success_data(api.create_student(
            create_student_payload(district["id"], pid, rfid,
                                   home_lat=lat, home_lng=-75.0), ADMIN))
        app = get_success_data(api.create_application(
            {"district_id": district["id"], "student_id": stu["id"],
             "requested_route_id": route["id"], "requested_stop_id": stop["id"]}, ADMIN))
        get_success_data(api.start_review(app["id"], ADMIN))
        get_success_data(api.approve_application(app["id"], ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": asg["id"]}, ADMIN))
    drv = make_driver_headers(driver["id"])
    validate_success(api.start_boarding(trip["id"], drv), 200)
    validate_success(api.record_tap(
        trip["id"], {"rfid_uid": "RF-A", "direction": "TAP_ON", "stop_sequence": 1}, drv), 201)
    validate_success(api.record_tap(
        trip["id"], {"rfid_uid": "RF-B", "direction": "TAP_ON", "stop_sequence": 1}, drv), 201)
    refreshed = validate_success(api.get_bus_trip(trip["id"], drv), 200)
    assert refreshed["onboard_count"] == 2, "two unmatched TAP_ON events => onboard_count 2"


# ===========================================================================
# Corner/validations/tap_off_without_prior_tap_on_returns_tap_sequence
# ===========================================================================
def test_tap_off_without_prior_tap_on_returns_tap_sequence(api):
    """PRD §3.7: "a `TAP_OFF` requires a prior unmatched `TAP_ON` for that student on this trip, and a `TAP_ON` requires that the student is not already onboard; either violation is rejected with `ERR_TAP_SEQUENCE`."

    Design: Corner/validations/tap_off_without_prior_tap_on_returns_tap_sequence
    """
    district, route, stops, driver, assignment, trip, student, application = (
        setup_boarding_trip_with_approved_rider(num_stops=1, rfid_uid="RF-R")
    )
    drv = make_driver_headers(driver["id"])
    # Rider never tapped on; a TAP_OFF is rejected.
    res = api.record_tap(
        trip["id"], {"rfid_uid": "RF-R", "direction": "TAP_OFF", "stop_sequence": 1}, drv
    )
    validate_error(res, "ERR_TAP_SEQUENCE", 409)


# ===========================================================================
# Corner/endpoints/tap_appends_parent_notification
# ===========================================================================
def test_tap_appends_parent_notification(api):
    """PRD §3.10: "a tap emits `TAP_ON` or `TAP_OFF` to the tapped student's parent"

    Design: Corner/endpoints/tap_appends_parent_notification
    """
    district, route, stops, driver, assignment, trip, student, application = (
        setup_boarding_trip_with_approved_rider(num_stops=1, parent_id="par-1",
                                                rfid_uid="RF-R")
    )
    drv = make_driver_headers(driver["id"])
    validate_success(api.record_tap(
        trip["id"], {"rfid_uid": "RF-R", "direction": "TAP_ON", "stop_sequence": 1}, drv), 201)
    par = make_parent_headers("par-1")
    data, meta = validate_paginated(
        api.list_parent_notifications(par, params={"parent_id": "par-1", "kind": "TAP_ON"})
    )
    assert len(data) >= 1, "a TAP_ON notification must be appended for the rider's parent"
    notice = data[0]
    assert notice["kind"] == "TAP_ON"
    assert notice["parent_id"] == "par-1"
    assert notice["student_id"] == student["id"]


# ===========================================================================
# Corner/cross_cutting_complexity_layers/incident_raise_cascades_notifications_to_onboard
# ===========================================================================
def test_incident_raise_cascades_notifications_to_onboard(api):
    """PRD §3.7: "Raising an incident increments the trip's `incident_count` by one, recomputes the route's `open_incident` flag to true, and appends a parent notification of kind `INCIDENT` for every student currently onboard the bus."

    Design: Corner/cross_cutting_complexity_layers/incident_raise_cascades_notifications_to_onboard
    """
    district, route, stops, driver, assignment, trip, student, application = (
        setup_boarding_trip_with_approved_rider(num_stops=2, parent_id="par-1",
                                                rfid_uid="RF-R")
    )
    drv = make_driver_headers(driver["id"])
    validate_success(api.record_tap(
        trip["id"], {"rfid_uid": "RF-R", "direction": "TAP_ON", "stop_sequence": 1}, drv), 201)
    validate_success(api.depart_stop(trip["id"], {"stop_sequence": 1}, drv), 200)
    held = validate_success(api.raise_incident(trip["id"], drv), 200)
    assert held["status"] == "INCIDENT_HOLD"
    data, meta = validate_paginated(
        api.list_parent_notifications(
            ADMIN, params={"bus_trip_id": trip["id"], "kind": "INCIDENT"})
    )
    assert len(data) == 1, "exactly one INCIDENT notice for the single onboard rider"
    assert data[0]["student_id"] == student["id"]
    assert data[0]["kind"] == "INCIDENT"


# ===========================================================================
# Corner/endpoints/missed_bus_protocol_acknowledge_then_resolve
# ===========================================================================
def _setup_missed_bus_report_open(api):
    """District grace 10; 2-stop route; trip departed both stops; clock 07:15Z;
    OPEN missed-bus report filed for stop 2. Returns (report_id, district_id, student)."""
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0,
                                missed_bus_grace_minutes=10), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=20), ADMIN))
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 2, "2026-09-01T07:10:00Z", lat=40.01, lng=-75.0),
        ADMIN))
    driver = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Drv A"), ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    asg = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    student = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-M",
                               full_name="Misser", grade=4,
                               home_lat=40.05, home_lng=-75.0), ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": asg["id"]}, ADMIN))
    drv = make_driver_headers(driver["id"])
    validate_success(api.start_boarding(trip["id"], drv), 200)
    validate_success(api.depart_stop(trip["id"], {"stop_sequence": 1}, drv), 200)
    # Departing stop 1 advances current_stop_sequence to the final stop (2). The bus
    # cannot "depart" its final stop (PRD §3.6: departure is permitted only while the
    # current stop is not the route's final stop); the trip instead COMPLETES, which
    # satisfies the window test's "the trip must be COMPLETED" branch for stop 2.
    validate_success(api.complete_trip(trip["id"], drv), 200)
    get_success_data(api.set_clock("2026-09-01T07:15:00Z", ADMIN))
    report = get_success_data(api.create_missed_bus_report(
        {"district_id": district["id"], "student_id": student["id"],
         "bus_trip_id": trip["id"], "reported_stop_sequence": 2},
        make_parent_headers("par-1")))
    return report, district, student


def test_missed_bus_protocol_acknowledge_then_resolve(api):
    """PRD §3.9: "Acknowledging an `OPEN` report moves it to `ACKNOWLEDGED` (legal only from `OPEN`). Resolving an `ACKNOWLEDGED` report moves it to `RESOLVED` (legal only from `ACKNOWLEDGED`) and sets its `resolution` from the body to either `PARENT_PICKUP` or `REBOARDED_NEXT_TRIP`."

    Design: Corner/endpoints/missed_bus_protocol_acknowledge_then_resolve
    """
    report, district, student = _setup_missed_bus_report_open(api)
    assert report["status"] == "OPEN"
    acked = validate_success(api.acknowledge_report(report["id"], ADMIN), 200)
    assert acked["status"] == "ACKNOWLEDGED"
    resolved = validate_success(
        api.resolve_report(report["id"], {"resolution": "PARENT_PICKUP"}, ADMIN), 200
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "PARENT_PICKUP"


# ===========================================================================
# Difficulty/boundary_precision_check/missed_bus_window_inclusive_deadline
# ===========================================================================
def test_missed_bus_window_inclusive_deadline_at_exactly_deadline(api):
    """PRD §3.9: "the deadline is that stop's `scheduled_departure` plus the district's `missed_bus_grace_minutes`, and the current server clock must be at or before that deadline — a clock reading exactly equal to the deadline is still inside the window."

    Design: Difficulty/boundary_precision_check/missed_bus_window_inclusive_deadline
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0,
                                missed_bus_grace_minutes=10), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=20), ADMIN))
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 2, "2026-09-01T07:10:00Z", lat=40.01, lng=-75.0),
        ADMIN))
    driver = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Drv A"), ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    asg = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    student = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-M",
                               home_lat=40.05, home_lng=-75.0), ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": asg["id"]}, ADMIN))
    drv = make_driver_headers(driver["id"])
    validate_success(api.start_boarding(trip["id"], drv), 200)
    validate_success(api.depart_stop(trip["id"], {"stop_sequence": 1}, drv), 200)
    # Stop 2 is the final stop and cannot be "departed" (PRD §3.6); completing the trip
    # instead satisfies the window test's "the trip must be COMPLETED" branch for stop 2.
    validate_success(api.complete_trip(trip["id"], drv), 200)
    # Deadline = 07:10 + 10 = 07:20:00Z exactly; filing AT the deadline is timely.
    get_success_data(api.set_clock("2026-09-01T07:20:00Z", ADMIN))
    res = api.create_missed_bus_report(
        {"district_id": district["id"], "student_id": student["id"],
         "bus_trip_id": trip["id"], "reported_stop_sequence": 2},
        make_parent_headers("par-1"))
    report = validate_success(res, 201)
    assert report["status"] == "OPEN", (
        "filing exactly at the inclusive deadline (07:20:00Z) is accepted"
    )


def test_missed_bus_report_filed_within_window_is_open(api):
    """PRD §3.9: "When accepted, the report is created in `OPEN` status and a parent notification of kind `MISSED_BUS` is appended."

    Design: Difficulty/boundary_precision_check/missed_bus_window_inclusive_deadline
    """
    # Clock at 07:15Z (strictly inside the 07:20 deadline) is the X-1 side.
    report, district, student = _setup_missed_bus_report_open(api)
    assert report["status"] == "OPEN", "a report filed inside the window is OPEN"


# ===========================================================================
# Corner/endpoints/advance_service_day_increments_index
# ===========================================================================
def test_advance_service_day_increments_index(api):
    """PRD §3.1: "The district also maintains a monotonic operations-epoch counter, `service_day_index`, which starts at 0 and is advanced one at a time by an admin-only advance-service-day capability; that same advance operation returns the updated district."

    Design: Corner/endpoints/advance_service_day_increments_index
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    assert district["service_day_index"] == 0
    advanced = validate_success(api.advance_service_day(district["id"], ADMIN), 200)
    assert advanced["service_day_index"] == 1, (
        "advance-service-day increments service_day_index from 0 to 1"
    )


# ===========================================================================
# Corner/endpoints/list_routes_filter_by_posture_paginated
# ===========================================================================
def test_list_routes_filter_by_posture(api):
    """PRD §3.1: "Routes can be listed with optional filters on `district_id` and `posture`."
    PRD §2.3: "Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_routes_filter_by_posture_paginated
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route_a = get_success_data(api.create_route(
        create_route_payload(district["id"], name="RA", seat_capacity=10), ADMIN))
    get_success_data(api.create_route(
        create_route_payload(district["id"], name="RB", seat_capacity=10), ADMIN))
    # Suspend RA.
    get_success_data(api.change_posture(
        route_a["id"], {"action": "SUSPEND", "expected_route_version": route_a["version"]},
        ADMIN))
    data, meta = validate_paginated(
        api.list_routes(ADMIN, params={"district_id": district["id"],
                                       "posture": "SUSPENDED"})
    )
    assert meta["total_count"] == 1, "only the SUSPENDED route is returned"
    assert meta["has_more"] is False
    assert len(data) == 1
    assert data[0]["id"] == route_a["id"]
    assert data[0]["posture"] == "SUSPENDED"
