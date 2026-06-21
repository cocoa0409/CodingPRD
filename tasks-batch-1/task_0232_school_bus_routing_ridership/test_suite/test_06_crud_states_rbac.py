"""CRUD defaults, input validation, simple state guards, referential integrity,
and role-based access control corners.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    NON_EXISTENT_UUID,
    setup_approved_rider,
    setup_boarding_trip,
    create_district_payload,
    create_route_payload,
    create_stop_payload,
    create_student_payload,
    create_driver_payload,
    create_application_payload,
    make_admin_headers,
    make_driver_headers,
    make_parent_headers,
)

ADMIN = make_admin_headers()


# ===========================================================================
# Corner/entities/create_district_returns_201_with_defaults
# ===========================================================================
def test_create_district_returns_201_with_defaults(api):
    """PRD §3.1: "The `walk_threshold_miles` value, defaulting to 1.5... The `hazard_override_enabled` flag, defaulting to true... The `missed_bus_grace_minutes` value, defaulting to 10... At creation, `service_day_index` is 0 and `active_route_count` computes as 0."
    PRD §2.4: "a system-managed integer that begins at its initial value and increments by one with every modification. It is the basis for optimistic concurrency control."

    Design: Corner/entities/create_district_returns_201_with_defaults
    """
    res = api.create_district(
        {"name": "D1", "school_lat": 40.0, "school_lng": -75.0}, ADMIN
    )
    district = validate_success(res, 201)
    assert district["walk_threshold_miles"] == 1.5
    assert district["hazard_override_enabled"] is True
    assert district["missed_bus_grace_minutes"] == 10
    assert district["service_day_index"] == 0
    assert district["version"] == 1


# ===========================================================================
# Corner/entities/get_route_not_found_returns_404
# ===========================================================================
def test_get_route_not_found_returns_404(api):
    """PRD §2.7: "if any identifier named in the path does not correspond to an existing resource, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any body-level work begins."

    Design: Corner/entities/get_route_not_found_returns_404
    """
    res = api.get_route(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", 404)


# ===========================================================================
# Corner/entities/create_route_missing_seat_capacity_returns_invalid_request
# ===========================================================================
def test_create_route_missing_seat_capacity_returns_invalid_request(api):
    """PRD §2.8: "then well-formedness of the request body — required fields present, enum values valid, and numbers within range (`ERR_INVALID_REQUEST`, HTTP 422)"
    PRD §3.1: "Its `seat_capacity` sets the maximum number of seated riders and must be greater than zero, while its `wheelchair_capacity` sets the number of securement positions for special-needs riders, defaults to 0, and must be at least zero."

    Design: Corner/entities/create_route_missing_seat_capacity_returns_invalid_request
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    res = api.create_route({"district_id": district["id"], "name": "R1"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", 422)


# ===========================================================================
# Corner/entities/create_route_seat_capacity_zero_returns_invalid_request
# ===========================================================================
def test_create_route_seat_capacity_zero_returns_invalid_request(api):
    """PRD §2.8: "a route's `seat_capacity` must be greater than zero... Any violation of these yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_route_seat_capacity_zero_returns_invalid_request
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    res = api.create_route(
        {"district_id": district["id"], "name": "R1", "seat_capacity": 0}, ADMIN
    )
    validate_error(res, "ERR_INVALID_REQUEST", 422)


# ===========================================================================
# Corner/entities/duplicate_rfid_uid_returns_duplicate
# ===========================================================================
def test_duplicate_rfid_uid_returns_duplicate(api):
    """PRD §3.2: "The `rfid_uid` must be unique across all students in the district; a reused value is rejected with `ERR_DUPLICATE`."

    Design: Corner/entities/duplicate_rfid_uid_returns_duplicate
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-DUP",
                               full_name="First", home_lat=40.05, home_lng=-75.0), ADMIN))
    res = api.create_student(
        create_student_payload(district["id"], "par-2", "RF-DUP",
                               full_name="Second", grade=5, home_lat=40.06, home_lng=-75.0),
        ADMIN)
    validate_error(res, "ERR_DUPLICATE", 409)


# ===========================================================================
# Corner/entities/duplicate_stop_sequence_returns_duplicate
# ===========================================================================
def test_duplicate_stop_sequence_returns_duplicate(api):
    """PRD §3.1: "First, `sequence` must be unique within its route; a collision is rejected with `ERR_DUPLICATE`."

    Design: Corner/entities/duplicate_stop_sequence_returns_duplicate
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    res = api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:30:00Z",
                            label="S1b", lat=40.01, lng=-75.0),
        ADMIN)
    validate_error(res, "ERR_DUPLICATE", 409)


# ===========================================================================
# Corner/state_machines/route_initial_posture_is_open
# ===========================================================================
def test_route_initial_posture_is_open(api):
    """PRD §3.1: "A route begins life in `OPEN` posture, with `assigned_rider_count`, `assigned_wheelchair_count` both at 0 and `open_incident` false."

    Design: Corner/state_machines/route_initial_posture_is_open
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = validate_success(
        api.create_route(create_route_payload(district["id"], seat_capacity=10), ADMIN), 201
    )
    assert route["posture"] == "OPEN"


# ===========================================================================
# Corner/state_machines/start_boarding_on_suspended_route_returns_route_not_open
# ===========================================================================
def test_start_boarding_after_suspend_cascade_returns_invalid_state(api):
    """PRD §3.8: "every `SCHEDULED` trip on the route is driven to `CANCELLED`, and each such trip's driver is returned to `AVAILABLE` if it was `ON_DUTY` for that trip."
    PRD §3.6: "The acting `Driver` starts boarding a `SCHEDULED` trip to begin the run. This is legal only from `SCHEDULED`, and it carries several safety preconditions."

    Design: Corner/state_machines/start_boarding_on_suspended_route_returns_route_not_open
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    driver = get_success_data(api.create_driver(
        create_driver_payload(district["id"], full_name="Drv A"), ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    asg = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": asg["id"]}, ADMIN))
    # Suspend while the trip is still SCHEDULED -> trip cascaded to CANCELLED.
    route = get_success_data(api.get_route(route["id"], ADMIN))
    get_success_data(api.change_posture(
        route["id"], {"action": "SUSPEND", "expected_route_version": route["version"]},
        ADMIN))
    # Boarding the now-CANCELLED trip is no longer legal from SCHEDULED.
    res = api.start_boarding(trip["id"], make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INVALID_STATE", 409)


# ===========================================================================
# Corner/state_machines/complete_with_riders_onboard_returns_riders_still_onboard
# ===========================================================================
def test_complete_with_riders_onboard_returns_riders_still_onboard(api):
    """PRD §3.6: "only when `onboard_count` is exactly 0 — a trip with riders still aboard is rejected with `ERR_RIDERS_STILL_ONBOARD`."

    Design: Corner/state_machines/complete_with_riders_onboard_returns_riders_still_onboard
    """
    from test_helpers import setup_boarding_trip_with_approved_rider
    district, route, stops, driver, assignment, trip, student, application = (
        setup_boarding_trip_with_approved_rider(num_stops=2, rfid_uid="RF-R")
    )
    drv = make_driver_headers(driver["id"])
    validate_success(api.record_tap(
        trip["id"], {"rfid_uid": "RF-R", "direction": "TAP_ON", "stop_sequence": 1}, drv), 201)
    # Advance to the final stop (seq 2) but leave the rider onboard.
    validate_success(api.depart_stop(trip["id"], {"stop_sequence": 1}, drv), 200)
    res = api.complete_trip(trip["id"], drv)
    validate_error(res, "ERR_RIDERS_STILL_ONBOARD", 409)


# ===========================================================================
# Corner/state_machines/cancel_in_flight_trip_returns_invalid_state
# ===========================================================================
def test_cancel_in_flight_trip_returns_invalid_state(api):
    """PRD §3.6: "A `TransportAdmin` may instead cancel a still-`SCHEDULED` trip; this is legal only from `SCHEDULED`, moves it to `CANCELLED`, and frees its driver back to `AVAILABLE` if the driver was `ON_DUTY` for that trip."

    Design: Corner/state_machines/cancel_in_flight_trip_returns_invalid_state
    """
    district, route, stops, driver, assignment, trip = setup_boarding_trip(num_stops=1)
    res = api.cancel_trip(trip["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", 409)


# ===========================================================================
# Corner/validations/stop_not_on_requested_route_returns_invalid_reference
# ===========================================================================
def test_stop_not_on_requested_route_returns_invalid_reference(api):
    """PRD §3.3: "the requested `requested_stop_id`, which must belong to the requested route."
    PRD §2.8: "then resolution and parentage of body foreign-key references (`ERR_INVALID_REFERENCE`, HTTP 422)"

    Design: Corner/validations/stop_not_on_requested_route_returns_invalid_reference
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN))
    route_a = get_success_data(api.create_route(
        create_route_payload(district["id"], name="RA", seat_capacity=10), ADMIN))
    route_b = get_success_data(api.create_route(
        create_route_payload(district["id"], name="RB", seat_capacity=10), ADMIN))
    stop_b = get_success_data(api.create_stop(
        create_stop_payload(route_b["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    student = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-1",
                               home_lat=40.05, home_lng=-75.0), ADMIN))
    # Application requests route A but route B's stop.
    res = api.create_application(
        create_application_payload(district["id"], student["id"],
                                   route_a["id"], stop_b["id"]), ADMIN)
    validate_error(res, "ERR_INVALID_REFERENCE", 422)


# ===========================================================================
# Corner/rbac/parent_cannot_approve_application_returns_forbidden
# ===========================================================================
def test_parent_cannot_approve_application_returns_forbidden(api):
    """PRD §3.4: "Approval is the most heavily guarded transition in the application lifecycle and is reserved for a `TransportAdmin`."
    PRD §2.1: "When the headers are well-formed but the acting role is not permitted
    to perform the requested operation... the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/parent_cannot_approve_application_returns_forbidden
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0,
                                walk_threshold_miles=1.5), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    stop = get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    par = make_parent_headers("par-1")
    student = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-1",
                               home_lat=40.05, home_lng=-75.0), par))
    app = get_success_data(api.create_application(
        create_application_payload(district["id"], student["id"],
                                   route["id"], stop["id"]), par))
    get_success_data(api.start_review(app["id"], ADMIN))
    res = api.approve_application(app["id"], par)
    validate_error(res, "ERR_FORBIDDEN", 403)


# ===========================================================================
# Corner/rbac/parent_cannot_withdraw_other_parents_application_returns_forbidden
# ===========================================================================
def test_parent_cannot_withdraw_other_parents_application_returns_forbidden(api):
    """PRD §2.1: "or a parent attempts to act on a student or application they do not own — the request is rejected with `ERR_FORBIDDEN`."
    PRD §3.3: "A parent may also `WITHDRAW` their own application: withdrawal is legal from `SUBMITTED` and from `CHANGES_REQUESTED`, requires the acting parent to own the student, and moves the application to `WITHDRAWN` with no further effect."

    Design: Corner/rbac/parent_cannot_withdraw_other_parents_application_returns_forbidden
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0,
                                walk_threshold_miles=1.5), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    stop = get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    par1 = make_parent_headers("par-1")
    student = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-1",
                               home_lat=40.05, home_lng=-75.0), par1))
    app = get_success_data(api.create_application(
        create_application_payload(district["id"], student["id"],
                                   route["id"], stop["id"]), par1))
    # par-2 attempts to withdraw par-1's student's application.
    par2 = make_parent_headers("par-2")
    res = api.withdraw_application(app["id"], par2)
    validate_error(res, "ERR_FORBIDDEN", 403)


# ===========================================================================
# Corner/rbac/missing_auth_headers_returns_unauthenticated
# ===========================================================================
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "When either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.get_district(NON_EXISTENT_UUID, headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", 401)
