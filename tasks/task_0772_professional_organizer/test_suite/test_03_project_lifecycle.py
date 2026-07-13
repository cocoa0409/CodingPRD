"""Project activation preconditions, terminal lockdown, and the cross-entity
Session-start-requires-Project-ACTIVE dependency.
"""
from test_helpers import (
    validate_success, validate_error,
    create_project_payload,
    new_client, new_organizer, new_project, new_active_project, new_session,
    make_organizer_headers, TEST_USERS,
)

OM = TEST_USERS["operations_manager_headers"]


def _scoping_project(scope_rooms=None, billing_mode="HOURLY", **over):
    client = new_client()
    organizer = new_organizer()
    if scope_rooms is None:
        scope_rooms = ["Room"]
    project = new_project(client["id"], organizer["id"],
                          billing_mode=billing_mode, scope_rooms=scope_rooms, **over)
    return client, organizer, project


# ── Corner: state-machine invalid transitions & preconditions ─────────────────

def test_activate_already_active_project_returns_invalid(api):
    """PRD §3.2: "Activation is only valid from SCOPING; attempting it from any other
    state is rejected with ERR_PROJECT_NOT_IN_SCOPING."

    Design: Corner/state_machines/activate_already_active_project_returns_invalid
    """
    client, organizer, project = new_active_project(scope_rooms=["Room"])
    res = api.activate_project(project["id"], OM)
    validate_error(res, "ERR_PROJECT_NOT_IN_SCOPING")


def test_activate_empty_scope_returns_scope_empty(api):
    """PRD §3.2: "the scope_rooms array must be non-empty — at least one room must
    have been captured during the in-home assessment, otherwise the request fails
    with ERR_SCOPE_EMPTY."

    Design: Corner/state_machines/activate_empty_scope_returns_scope_empty
    """
    client, organizer, project = _scoping_project(scope_rooms=[])
    res = api.activate_project(project["id"], OM)
    validate_error(res, "ERR_SCOPE_EMPTY")


def test_activate_project_billed_zero_flat_price_returns_error(api):
    """PRD §3.2: "when billing_mode is PROJECT, flat_price_cents must be strictly
    greater than zero, otherwise the request fails with ERR_FLAT_PRICE_REQUIRED."

    Design: Corner/state_machines/activate_project_billed_zero_flat_price_returns_error
    """
    client, organizer, project = _scoping_project(scope_rooms=["Room"], billing_mode="PROJECT")
    assert project["flat_price_cents"] == 0
    res = api.activate_project(project["id"], OM)
    validate_error(res, "ERR_FLAT_PRICE_REQUIRED")


def test_cancel_already_cancelled_project_returns_terminal(api):
    """PRD §3.8: "a project already in a terminal state (CLOSED or CANCELLED) cannot
    be cancelled and the attempt is rejected with ERR_PROJECT_TERMINAL."

    Design: Corner/state_machines/cancel_already_cancelled_project_returns_terminal
    """
    client, organizer, project = _scoping_project(scope_rooms=["Room"])
    validate_success(api.cancel_project(project["id"], OM), 200)
    res = api.cancel_project(project["id"], OM)
    validate_error(res, "ERR_PROJECT_TERMINAL")


# ── Difficulty: cross-entity state dependency (Session start needs Project ACTIVE) ─

def test_scheduled_session_cannot_start_while_project_scoping(api):
    """PRD §3.4: "Starting a session advances it from SCHEDULED to IN_PROGRESS; this
    is done by an OperationsManager or an Organizer, and it requires the parent
    project to be in ACTIVE, failing otherwise with ERR_PROJECT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/session_start_requires_project_active
    """
    client, organizer, project = _scoping_project(scope_rooms=["Room"])
    session = new_session(project["id"], organizer["id"],
                          "2026-03-09T09:00:00Z", "2026-03-09T12:00:00Z")
    res = api.patch_session(session["id"], {"status": "IN_PROGRESS"},
                            make_organizer_headers(organizer["id"]))
    validate_error(res, "ERR_PROJECT_NOT_ACTIVE")


def test_session_starts_after_project_activated(api):
    """PRD §3.4: "Starting a session advances it from SCHEDULED to IN_PROGRESS; this
    is done by an OperationsManager or an Organizer, and it requires the parent
    project to be in ACTIVE, failing otherwise with ERR_PROJECT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/session_start_requires_project_active
    """
    client, organizer, project = _scoping_project(scope_rooms=["Room"])
    session = new_session(project["id"], organizer["id"],
                          "2026-03-09T09:00:00Z", "2026-03-09T12:00:00Z")
    validate_success(api.activate_project(project["id"], OM), 200)
    res = api.patch_session(session["id"], {"status": "IN_PROGRESS"},
                            make_organizer_headers(organizer["id"]))
    started = validate_success(res, 200)
    assert started["status"] == "IN_PROGRESS"
