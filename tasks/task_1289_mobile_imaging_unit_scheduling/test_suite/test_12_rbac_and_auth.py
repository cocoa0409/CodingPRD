"""Authentication context and role-based access control probes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_appointment_payload,
    create_route_plan_payload,
    create_unit,
    setup_bookable_day,
    validate_error,
)

OPS = TEST_USERS["operations_director_headers"]
RADIOLOGIST = TEST_USERS["reading_radiologist_headers"]


def test_request_with_undeclared_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or declaring a role outside
    this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/request_with_undeclared_role_header_unauthenticated
    """
    headers = build_user_headers("anon-1", "Anonymous")
    resp = api.list_facilities(headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_facility_coordinator_cannot_create_route_plan(api):
    """PRD §2.1: "A request whose role is declared but not permitted for the
    targeted endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: the route-plan create row names OperationsDirector as the only
    authorized role.

    Design: Corner/rbac/facility_coordinator_cannot_create_route_plan
    """
    unit = create_unit()
    payload = create_route_plan_payload(unit["id"], "2026-08-03", unit["version"])
    coord = build_user_headers("test-coord-1", "FacilityCoordinator")
    resp = api.create_route_plan(payload, coord)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_reading_radiologist_cannot_book_appointment(api):
    """PRD §2.1: "A request whose role is declared but not permitted for the
    targeted endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: the appointment create row names FacilityCoordinator as the only
    authorized role.

    Design: Corner/rbac/reading_radiologist_cannot_book_appointment
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    payload = create_appointment_payload(bundle["site_day"]["id"], "P-900")
    resp = api.create_appointment(payload, RADIOLOGIST)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
