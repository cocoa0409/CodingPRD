"""Role-based access control and authentication gates.

Covers queue B: rbac section instances (peer-role isolation, entity-backed owner
mismatch, missing-auth).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_client_headers,
    create_client_payload,
    create_project_payload,
    create_room_payload,
    create_moodboard_payload,
    create_client,
    create_project,
    create_room,
)

ADMIN = TEST_USERS["studio_admin_headers"]
DESIGNER = TEST_USERS["designer_headers"]
PC = TEST_USERS["procurement_coordinator_headers"]


def _moodboard_ready_room(project_id):
    """Build a room driven to MOODBOARD_READY with one PRESENTED board."""
    room = create_room(project_id, name="R1")
    mb = get_success_data(api_client.create_moodboard(room["id"], create_moodboard_payload(), DESIGNER))
    get_success_data(api_client.present_moodboard(mb["id"], DESIGNER))
    get_success_data(api_client.present_moodboard_room(room["id"], DESIGNER))
    return room


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — rbac / designer_cannot_create_project
# ─────────────────────────────────────────────────────────────────────────────
def test_designer_cannot_create_project(api):
    """PRD §2.1: "When the header is present and valid but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with ERR_FORBIDDEN."
    PRD §4: "POST | /projects | Create a Project from the client brief | StudioAdmin"

    Design: Corner/rbac/designer_cannot_create_project
    """
    client = create_client(email="wo.c1@x.com")
    res = api.create_project(
        create_project_payload(client["id"], client_name="Wo", brief_summary="x",
                               budget_cents=100000, fee_model="FLAT", flat_fee_cents=100), DESIGNER)
    validate_error(res, "ERR_FORBIDDEN")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — rbac / procurementcoordinator_cannot_approve_room
# ─────────────────────────────────────────────────────────────────────────────
def test_procurement_coordinator_cannot_approve_room(api):
    """PRD §2.1: "the role is not permitted to perform the requested operation ... the
    request is rejected with ERR_FORBIDDEN."
    PRD §4: "POST | /rooms/{room_id}/approve | Client approves room; pins mood board |
    Client"

    Design: Corner/rbac/procurementcoordinator_cannot_approve_room
    """
    client = create_client(email="xa.c1@x.com")
    project = create_project(client["id"], client_name="Xa", budget_cents=10000000)
    room = _moodboard_ready_room(project["id"])
    res = api.approve_room(room["id"], PC)
    validate_error(res, "ERR_FORBIDDEN")
    room_after = validate_success(api.get_room(room["id"], ADMIN), 200)
    assert room_after["status"] == "MOODBOARD_READY", room_after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — rbac / client_approve_other_clients_room_forbidden
# ─────────────────────────────────────────────────────────────────────────────
def test_client_cannot_approve_another_clients_room(api):
    """PRD §2.1: "a Client may only act on (and read) a Project whose client_user_id
    equals their X-User-ID, and may only act on artifacts that belong to such a
    project. An ownership mismatch surfaces as ERR_FORBIDDEN."

    Design: Corner/rbac/client_approve_other_clients_room_forbidden
    """
    owner = create_client(display_name="A", email="owner.a1@x.com")
    other = create_client(display_name="B", email="other.b1@x.com")
    project = create_project(owner["id"], client_name="A", budget_cents=10000000)
    room = _moodboard_ready_room(project["id"])
    # Client B (not the project's owner) attempts to approve.
    res = api.approve_room(room["id"], make_client_headers(other["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    room_after = validate_success(api.get_room(room["id"], ADMIN), 200)
    assert room_after["status"] == "MOODBOARD_READY", room_after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — rbac / missing_role_header_returns_401
# ─────────────────────────────────────────────────────────────────────────────
def test_missing_role_header_returns_401(api):
    """PRD §2.1: "If X-User-Role is missing or does not name one of the recognized
    roles, the request is rejected with ERR_UNAUTHENTICATED."
    PRD §2.6: "Authentication comes first: a missing or unrecognized X-User-Role
    yields ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_role_header_returns_401
    """
    res = api.create_client(create_client_payload(email="z.c1@x.com"), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")
