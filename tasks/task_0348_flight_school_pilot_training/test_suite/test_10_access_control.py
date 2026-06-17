"""Access-control claims: peer-role isolation (one role cannot perform another's
exclusive operation) and the mandatory user-context headers.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    build_user_headers,
    setup_active_enrollment, create_aircraft, create_booking,
    get_booking,
    create_student_payload, create_aircraft_payload,
    make_student_headers,
    TEST_USERS,
)

MECHANIC = TEST_USERS["mechanic_headers"]


def test_student_cannot_confirm_booking(api):
    """PRD §2.1: "When the headers are present and valid but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: confirm is authorized for "Dispatcher".

    Design: Corner/rbac/student_cannot_confirm_booking
    """
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    student_headers = make_student_headers(base["student"]["id"])
    # The student requests their own booking (a shared Student/Dispatcher operation).
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"], headers=student_headers,
    )
    # Confirm is Dispatcher-exclusive; the Student is forbidden.
    validate_error(api.confirm_booking(booking["id"], student_headers),
                   ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
    assert get_booking(booking["id"])["status"] == "REQUESTED"


def test_mechanic_cannot_create_aircraft(api):
    """PRD §2.1: "When the headers are present and valid but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: onboard aircraft is authorized for "SchoolAdmin".

    Design: Corner/rbac/mechanic_cannot_create_aircraft
    """
    validate_error(api.create_aircraft(create_aircraft_payload(), MECHANIC),
                   ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_invalid_role_header_rejected(api):
    """PRD §2.1: "If either header is missing or invalid, the request is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."
    PRD §2.1: "The system recognizes exactly five roles, spelled precisely as
    follows: `SchoolAdmin`, `Dispatcher`, `Student`, `Instructor`, and `Mechanic`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    bad_headers = build_user_headers("ghost-1", "Nobody")
    validate_error(api.create_student(create_student_payload(), bad_headers),
                   ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value)
