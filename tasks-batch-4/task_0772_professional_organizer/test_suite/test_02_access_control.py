"""Authentication and role-based authorization (breadth / corner instances)."""
from test_helpers import (
    validate_error,
    create_client_payload, create_project_payload,
    new_client, new_organizer, new_active_project, new_session, start_session,
    make_organizer_headers, make_client_headers, TEST_USERS,
)

OM = TEST_USERS["operations_manager_headers"]


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role does not name a role
    the system recognizes, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    res = api.create_client(create_client_payload(), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_organizer_cannot_create_client_returns_403(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation — or an ownership check fails — the request is
    rejected with ERR_FORBIDDEN."
    PRD §2.1: "An OperationsManager owns client and organizer setup plus the entire
    project lifecycle (creating, activating, and cancelling projects, and authoring
    maintenance plans)."

    Design: Corner/validations/organizer_cannot_create_client_returns_403
    """
    organizer = new_organizer()
    res = api.create_client(create_client_payload(), make_organizer_headers(organizer["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_organizer_complete_session_owner_mismatch_returns_403(api):
    """PRD §2.1: "In particular, completing a session is restricted to the organizer
    assigned to that session — the session's organizer_id must equal X-User-ID."

    Design: Corner/validations/organizer_complete_session_owner_mismatch_returns_403
    """
    client, organizer1, project = new_active_project(scope_rooms=["Room"])
    session = new_session(project["id"], organizer1["id"],
                          "2026-03-02T09:00:00Z", "2026-03-02T12:00:00Z")
    start_session(session["id"], organizer1["id"])
    organizer2 = new_organizer()
    res = api.complete_session(session["id"], {"logged_hours": 3},
                               make_organizer_headers(organizer2["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_client_cannot_create_project_returns_403(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation — or an ownership check fails — the request is
    rejected with ERR_FORBIDDEN."
    PRD §2.1: "An OperationsManager owns client and organizer setup plus the entire
    project lifecycle (creating, activating, and cancelling projects, and authoring
    maintenance plans)."

    Design: Corner/validations/client_cannot_create_project_returns_403
    """
    client = new_client()
    organizer = new_organizer()
    payload = create_project_payload(client["id"], organizer["id"],
                                     billing_mode="HOURLY", scope_rooms=["Room"])
    res = api.create_project(payload, make_client_headers(client["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
