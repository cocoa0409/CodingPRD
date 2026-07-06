"""Optimistic concurrency on Event.version and role-based access control.

Design queues:
  B (Corner): cross_cutting OCC rules; rbac denials
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_draft_event, create_bartender,
    create_client_payload, create_package_payload, create_event_payload,
    TEST_USERS, make_client_headers, ApiErrorId, NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Queue B — cross_cutting / optimistic concurrency
# ---------------------------------------------------------------------------
def test_stale_expected_version_on_second_patch_rejected(api):
    """PRD §2.5: "Two strictly sequential edits that each carry the same
    expected version cannot both apply: the first advances the version, and the
    second is therefore stale."

    Design: Corner/cross_cutting/occ_stale_event_version_on_patch
    """
    bundle = create_draft_event(api)
    ev_id = bundle["event"]["id"]
    v1 = bundle["event"]["version"]
    validate_success(api.update_event(
        ev_id, {"expected_event_version": v1, "guest_count": 90}, bundle["client_headers"]))
    resp = api.update_event(
        ev_id, {"expected_event_version": v1, "guest_count": 100}, bundle["client_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION.value)


def test_stale_expected_version_on_second_assignment_create_rejected(api):
    """PRD §2.5: "The prior assignment-create advanced the event's version
    because the staffing view changed, so a subsequent create still carrying the
    old expected_event_version is refused as stale; the losing writer resolves
    deterministically through the version check rather than by timing."

    Design: Corner/cross_cutting/occ_stale_event_version_on_assignment_create
    """
    bundle = create_draft_event(api)
    ev_id = bundle["event"]["id"]
    v1 = bundle["event"]["version"]
    bartender = create_bartender(api)
    validate_success(api.create_assignment(ev_id, {
        "bartender_id": bartender["id"], "shift_start": "2026-06-01T13:00:00Z",
        "shift_end": "2026-06-01T15:00:00Z", "role_on_event": "BACK",
        "expected_event_version": v1,
    }, COORD), 201)
    resp = api.create_assignment(ev_id, {
        "bartender_id": bartender["id"], "shift_start": "2026-06-01T18:00:00Z",
        "shift_end": "2026-06-01T21:00:00Z", "role_on_event": "BACK",
        "expected_event_version": v1,
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION.value)


# ---------------------------------------------------------------------------
# Queue B — rbac
# ---------------------------------------------------------------------------
def test_coordinator_cannot_create_event(api):
    """PRD §2.1: "When the headers are well formed but the role is not permitted
    to perform the requested operation — or an ownership-scoped role acts on a
    resource it does not own — the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."

    Design: Corner/rbac/coordinator_cannot_create_event
    """
    client = get_success_data(api.create_client(create_client_payload(), ADMIN))
    package = get_success_data(api.create_package(create_package_payload(), ADMIN))
    resp = api.create_event(
        create_event_payload(client["id"], package["id"], guest_count=80), COORD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_client_cannot_patch_another_clients_event(api):
    """PRD §2.1: "Ownership checks on any event compare the event's client_id to
    X-User-ID; a client may only read, edit, pay, confirm, cancel, or add menu
    items to an event whose client_id equals its own X-User-ID."

    Design: Corner/rbac/client_cannot_patch_other_clients_event
    """
    client_a = get_success_data(api.create_client(create_client_payload(email="a@x.com"), ADMIN))
    client_b = get_success_data(api.create_client(create_client_payload(email="b@x.com"), ADMIN))
    package = get_success_data(api.create_package(create_package_payload(), ADMIN))
    event = get_success_data(api.create_event(
        create_event_payload(client_a["id"], package["id"], guest_count=80),
        make_client_headers(client_a["id"])))
    # Client B (not the owner) attempts an edit.
    resp = api.update_event(
        event["id"], {"expected_event_version": event["version"], "guest_count": 90},
        make_client_headers(client_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of
    the five recognized roles, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_headers
    """
    resp = api.get_event(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
