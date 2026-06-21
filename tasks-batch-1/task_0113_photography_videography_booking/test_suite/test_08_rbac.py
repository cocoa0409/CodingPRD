"""Role-based access control: endpoint authorization, entity-backed ownership, and
authentication header enforcement.

Queue B (corner) instances exercised here:
  rbac / photographer_cannot_create_session_package_returns_forbidden
  rbac / client_cannot_sign_other_clients_contract_returns_not_owner
  rbac / unauthenticated_confirm_returns_unauthenticated
"""
from test_helpers import (
    validate_error, get_success_data, TEST_USERS,
    ApiErrorId, ANONYMOUS_HEADERS, NO_AUTH_HEADERS,
    make_client_headers, make_photographer_headers,
    # fixtures
    setup_draft_booking, create_sent_contract,
    # factories
    create_session_package_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# rbac / photographer_cannot_create_session_package_returns_forbidden
# ===========================================================================
def test_photographer_cannot_create_session_package(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted to invoke the
    targeted operation (per the authorization column of the endpoint table in §4) is
    rejected with ERR_FORBIDDEN_ROLE."

    POST /studio/session-packages is StudioAdmin-only (PRD §4); a Photographer caller ->
    ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/photographer_cannot_create_session_package_returns_forbidden
    """
    photographer = get_success_data(api.create_photographer(
        {"email": "rogue-p@studio.test", "full_name": "Rogue", "skills": ["PHOTO"],
         "hourly_rate_cents": 7000}, ADMIN))
    validate_error(
        api.create_session_package(
            create_session_package_payload(name="Rogue"),
            make_photographer_headers(photographer["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )


# ===========================================================================
# rbac / client_cannot_sign_other_clients_contract_returns_not_owner
# ===========================================================================
def test_client_cannot_sign_another_clients_contract(api):
    """PRD §2.1: "When an entity-backed actor targets a resource it does not own, the
    request is rejected with ERR_NOT_RESOURCE_OWNER." PRD §3.3: "signing is permitted only
    when the contract is SENT and only by the client who owns the contract's booking."

    Client B (not the booking owner) signing client A's SENT contract ->
    ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/client_cannot_sign_other_clients_contract_returns_not_owner
    """
    owner = get_success_data(api.create_client(
        {"email": "owner@studio.test", "full_name": "Owner", "phone": "221"}, ADMIN))
    other = get_success_data(api.create_client(
        {"email": "other@studio.test", "full_name": "Other", "phone": "222"}, ADMIN))
    photographer = get_success_data(api.create_photographer(
        {"email": "owner-p@studio.test", "full_name": "P", "skills": ["PHOTO"],
         "hourly_rate_cents": 7000}, ADMIN))
    package = get_success_data(api.create_session_package(
        create_session_package_payload(name="PB Owner"), ADMIN))
    booking = get_success_data(api.create_booking(
        {"client_id": owner["id"], "package_id": package["id"],
         "lead_photographer_id": photographer["id"], "requested_shoot_hours": 2},
        make_client_headers(owner["id"])))
    contract = create_sent_contract(booking["id"])
    validate_error(
        api.sign_contract(contract["id"], make_client_headers(other["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )


# ===========================================================================
# rbac / unauthenticated_confirm_returns_unauthenticated
# ===========================================================================
def test_confirm_without_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or supplies one that is malformed, is
    rejected with ERR_UNAUTHENTICATED."

    POST /studio/bookings/{id}/confirm with no X-User-ID / X-User-Role ->
    ERR_UNAUTHENTICATED.

    Design: Corner/rbac/unauthenticated_confirm_returns_unauthenticated
    """
    base = setup_draft_booking()
    booking = base["booking"]
    resp = api._request("POST", f"/studio/bookings/{booking['id']}/confirm", {}, NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
