"""Role-based access control and authentication (PRD §2.1)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_authorization_payload, complete_appointment_payload,
    build_user_headers, TEST_USERS, make_evaluator_headers,
    set_clock, create_child, create_therapist, setup_active_care,
    book_appointment, book_appointment_ok,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
COORDINATOR = TEST_USERS["scheduling_coordinator_headers"]


def test_therapist_cannot_create_authorization(api):
    """PRD §2.1: "A `ClinicAdmin` runs front-office and operations: registering
    children, creating therapists and authorizations". PRD §2.1: "When the headers
    are valid but the named role is not permitted to perform the requested
    operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/therapist_cannot_create_authorization
    """
    th = create_therapist()
    child = create_child()
    res = api.create_authorization(
        create_authorization_payload(child["id"], discipline="SLP", authorized_visits=3),
        build_user_headers(th["id"], "Therapist"))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_scheduling_coordinator_cannot_complete_session(api):
    """PRD §2.1: "A `Therapist` is the treating clinician who completes sessions
    and their notes". PRD §2.1: "When the headers are valid but the named role is
    not permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/scheduling_coordinator_cannot_complete_session
    """
    ctx = setup_active_care(clock="2026-06-20T12:00:00Z")
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    res = api.complete_appointment(
        appt["id"],
        complete_appointment_payload(narrative="Coordinator should not do this.",
                                     minutes_delivered=45, goal_progress_entries=[]),
        COORDINATOR)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_unknown_role_returns_missing_or_invalid_auth(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a
    known role, the request is rejected with `ERR_MISSING_OR_INVALID_AUTH`."

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    res = api.list_children(build_user_headers("nobody-1", "Nobody"))
    validate_error(res, "ERR_MISSING_OR_INVALID_AUTH")


def test_scheduling_coordinator_can_book(api):
    """PRD §2.1: "A `SchedulingCoordinator` works the scheduling desk only —
    booking, cancelling, and managing the waitlist — and shares those scheduling
    operations with `ClinicAdmin`."

    Design: Corner/rbac/scheduling_coordinator_can_book_shared_op
    """
    ctx = setup_active_care()
    res = book_appointment(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z",
                           headers=COORDINATOR)
    appt = validate_success(res, 201)
    assert appt["status"] == "SCHEDULED", appt
