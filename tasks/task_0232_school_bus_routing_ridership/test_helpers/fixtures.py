"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so a setup failure produces a clear
"Setup step failed" error instead of a confusing assertion failure later.

Identity threading: Driver actions present make_driver_headers(driver["id"]);
Parent actions present make_parent_headers(parent_id) where parent_id is the opaque
guardian string used as the student's parent_id. TransportAdmin uses admin headers.

Every fixture builds its preconditions from an empty database using only
PRD-declared endpoints (the harness restarts the server before every test).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_district_payload,
    create_route_payload,
    create_stop_payload,
    create_student_payload,
    create_application_payload,
    create_driver_payload,
    create_driver_assignment_payload,
    create_bus_trip_payload,
    create_tap_payload,
)
from .test_users import make_admin_headers, make_driver_headers, make_parent_headers

ADMIN = make_admin_headers()

# Default stop departure timeline (strictly increasing, PRD §3.1).
DEP_S1 = "2026-09-01T07:00:00Z"
DEP_S2 = "2026-09-01T07:10:00Z"
DEP_S3 = "2026-09-01T07:20:00Z"


# ---------------------------------------------------------------------------
# Tier 1 / 2: District, Route, Stop skeletons
# ---------------------------------------------------------------------------
def create_district(**overrides) -> dict:
    """Create a District. Returns the District object."""
    return get_success_data(
        api_client.create_district(create_district_payload(**overrides), ADMIN)
    )


def create_route(district_id, **overrides) -> dict:
    """Create an OPEN Route under a District. Returns the Route object."""
    return get_success_data(
        api_client.create_route(create_route_payload(district_id, **overrides), ADMIN)
    )


def create_stop(route_id, sequence, scheduled_departure, **overrides) -> dict:
    """Add a Stop to a Route. Returns the Stop object."""
    return get_success_data(
        api_client.create_stop(
            create_stop_payload(route_id, sequence, scheduled_departure, **overrides),
            ADMIN,
        )
    )


def setup_district_route_stop(
    district_overrides=None, route_overrides=None, stop_overrides=None
):
    """District + OPEN Route + one Stop (seq 1 @ 07:00).
    Returns (district, route, stop).
    """
    district = create_district(**(district_overrides or {}))
    route = create_route(district["id"], **(route_overrides or {}))
    stop = create_stop(route["id"], 1, DEP_S1, **(stop_overrides or {}))
    return district, route, stop


def setup_two_stop_route(district_overrides=None, route_overrides=None):
    """District + OPEN Route + two stops (seq1 @ 07:00, seq2 @ 07:10).
    Returns (district, route, stop1, stop2).
    """
    district = create_district(**(district_overrides or {}))
    route = create_route(district["id"], **(route_overrides or {}))
    stop1 = create_stop(route["id"], 1, DEP_S1)
    stop2 = create_stop(route["id"], 2, DEP_S2)
    return district, route, stop1, stop2


# ---------------------------------------------------------------------------
# Drivers and assignments
# ---------------------------------------------------------------------------
def create_driver(district_id, **overrides) -> dict:
    """Create a Driver (AVAILABLE). Returns the Driver object."""
    return get_success_data(
        api_client.create_driver(create_driver_payload(district_id, **overrides), ADMIN)
    )


def create_primary_assignment(route, driver_id, **overrides) -> dict:
    """Create a PRIMARY DriverAssignment on `route` (OCC version threaded from the
    route's current version). Returns the assignment object.
    """
    return get_success_data(
        api_client.create_driver_assignment(
            route["id"],
            create_driver_assignment_payload(
                driver_id, route["version"], role="PRIMARY", **overrides
            ),
            ADMIN,
        )
    )


def current_route_version(route_id) -> int:
    """Fetch the route's live version (for OCC writes after side effects)."""
    return get_success_data(api_client.get_route(route_id, ADMIN))["version"]


def setup_route_with_driver(district_overrides=None, route_overrides=None, num_stops=1):
    """District + OPEN Route + N stops + Driver + PRIMARY ACTIVE assignment.
    Returns (district, route, stops, driver, assignment).
    """
    district = create_district(**(district_overrides or {}))
    route = create_route(district["id"], **(route_overrides or {}))
    deps = [DEP_S1, DEP_S2, DEP_S3]
    stops = [create_stop(route["id"], i + 1, deps[i]) for i in range(num_stops)]
    driver = create_driver(district["id"])
    # Re-read the route so the assignment carries the live version.
    route = get_success_data(api_client.get_route(route["id"], ADMIN))
    assignment = create_primary_assignment(route, driver["id"])
    route = get_success_data(api_client.get_route(route["id"], ADMIN))
    return district, route, stops, driver, assignment


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------
def create_scheduled_trip(route_id, assignment_id) -> dict:
    """Schedule a BusTrip (SCHEDULED). Returns the trip object."""
    return get_success_data(
        api_client.create_bus_trip(
            create_bus_trip_payload(route_id, assignment_id), ADMIN
        )
    )


def setup_scheduled_trip(num_stops=1, district_overrides=None, route_overrides=None):
    """Full skeleton through a SCHEDULED trip.
    Returns (district, route, stops, driver, assignment, trip).
    """
    district, route, stops, driver, assignment = setup_route_with_driver(
        district_overrides=district_overrides,
        route_overrides=route_overrides,
        num_stops=num_stops,
    )
    trip = create_scheduled_trip(route["id"], assignment["id"])
    return district, route, stops, driver, assignment, trip


def setup_boarding_trip(num_stops=1, district_overrides=None, route_overrides=None):
    """Full skeleton through a BOARDING trip (current_stop_sequence == 1).
    Returns (district, route, stops, driver, assignment, trip).
    """
    district, route, stops, driver, assignment, trip = setup_scheduled_trip(
        num_stops=num_stops,
        district_overrides=district_overrides,
        route_overrides=route_overrides,
    )
    drv_headers = make_driver_headers(driver["id"])
    trip = get_success_data(api_client.start_boarding(trip["id"], drv_headers))
    return district, route, stops, driver, assignment, trip


# ---------------------------------------------------------------------------
# Students and applications
# ---------------------------------------------------------------------------
def create_student(district_id, parent_id, rfid_uid, **overrides) -> dict:
    """Create a Student (admin actor by default). Returns the Student object."""
    return get_success_data(
        api_client.create_student(
            create_student_payload(district_id, parent_id, rfid_uid, **overrides), ADMIN
        )
    )


def create_application(district_id, student_id, route_id, stop_id, actor_headers=None) -> dict:
    """Submit a ridership application (SUBMITTED). Returns the application object."""
    return get_success_data(
        api_client.create_application(
            create_application_payload(district_id, student_id, route_id, stop_id),
            actor_headers or ADMIN,
        )
    )


def setup_application_under_review(
    student_overrides=None,
    district_overrides=None,
    route_overrides=None,
    parent_id="par-1",
    rfid_uid="RF-1",
):
    """District + OPEN Route + Stop + Student + application moved to UNDER_REVIEW
    (eligibility_basis recomputed by start-review).
    Returns (district, route, stop, student, application).
    """
    district = create_district(**(district_overrides or {}))
    route = create_route(district["id"], **(route_overrides or {}))
    stop = create_stop(route["id"], 1, DEP_S1)
    student = create_student(
        district["id"], parent_id, rfid_uid, **(student_overrides or {})
    )
    application = create_application(
        district["id"], student["id"], route["id"], stop["id"]
    )
    application = get_success_data(api_client.start_review(application["id"], ADMIN))
    return district, route, stop, student, application


def approve_application(application_id) -> dict:
    """Approve an UNDER_REVIEW application. Returns the approved application."""
    return get_success_data(api_client.approve_application(application_id, ADMIN))


def setup_approved_rider(
    student_overrides=None,
    district_overrides=None,
    route_overrides=None,
    parent_id="par-1",
    rfid_uid="RF-R",
):
    """District + OPEN Route + Stop + Student + APPROVED application on the route.
    Returns (district, route, stop, student, application).
    """
    district, route, stop, student, application = setup_application_under_review(
        student_overrides=student_overrides,
        district_overrides=district_overrides,
        route_overrides=route_overrides,
        parent_id=parent_id,
        rfid_uid=rfid_uid,
    )
    application = approve_application(application["id"])
    return district, route, stop, student, application


# ---------------------------------------------------------------------------
# Combined: a boarding trip with one approved rider already onboard
# ---------------------------------------------------------------------------
def setup_boarding_trip_with_approved_rider(
    num_stops=2, parent_id="par-1", rfid_uid="RF-R", route_overrides=None
):
    """District + OPEN Route + N stops + Driver PRIMARY ACTIVE + APPROVED rider +
    a BOARDING trip (no taps yet).
    Returns (district, route, stops, driver, assignment, trip, student, application).
    """
    district = create_district(walk_threshold_miles=1.5)
    route = create_route(district["id"], **(route_overrides or {}))
    deps = [DEP_S1, DEP_S2, DEP_S3]
    stops = [create_stop(route["id"], i + 1, deps[i]) for i in range(num_stops)]
    driver = create_driver(district["id"])
    route = get_success_data(api_client.get_route(route["id"], ADMIN))
    assignment = create_primary_assignment(route, driver["id"])

    student = create_student(district["id"], parent_id, rfid_uid)
    application = create_application(
        district["id"], student["id"], route["id"], stops[0]["id"]
    )
    application = get_success_data(api_client.start_review(application["id"], ADMIN))
    application = approve_application(application["id"])

    trip = create_scheduled_trip(route["id"], assignment["id"])
    drv_headers = make_driver_headers(driver["id"])
    trip = get_success_data(api_client.start_boarding(trip["id"], drv_headers))
    return district, route, stops, driver, assignment, trip, student, application


def tap(trip_id, driver_id, rfid_uid, direction, stop_sequence) -> dict:
    """Record an RFID tap as the trip's driver. Returns the TapEvent object."""
    return get_success_data(
        api_client.record_tap(
            trip_id,
            create_tap_payload(rfid_uid, direction, stop_sequence),
            make_driver_headers(driver_id),
        )
    )


def depart(trip_id, driver_id, stop_sequence) -> dict:
    """Depart the current stop as the trip's driver. Returns the trip object."""
    return get_success_data(
        api_client.depart_stop(
            trip_id, {"stop_sequence": stop_sequence}, make_driver_headers(driver_id)
        )
    )
