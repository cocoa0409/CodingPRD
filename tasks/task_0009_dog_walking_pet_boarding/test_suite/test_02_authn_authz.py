"""Authentication header presence, role authorization, and path-entity
existence — the three highest-priority validators (priorities 1, 2, 3).
These tests cover queue B corner instances from the 'validations' and 'rbac'
sections.
"""
import pytest
from test_helpers import (
    api_client,
    validate_error,
    create_pet_payload,
    create_meet_and_greet_payload,
    create_booking_payload,
    TEST_USERS,
    make_owner_headers,
    make_sitter_headers,
    setup_owner_sitter_pet,
    register_owner,
    register_sitter,
    create_pending_bg_check,
    flag_bg_check,
    create_pet,
    setup_approved_meet_and_greet,
)


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CLAIMS_ADJUSTER = TEST_USERS["claims_adjuster_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing or empty on an endpoint that
    requires authentication, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_headers
    """
    # POST /pets requires auth. Send empty headers (no X-User-Role, no X-User-ID).
    payload = {"owner_id": "00000000-0000-0000-0000-000000000000",
               "name": "Anon", "species": "DOG", "weight_kg": 10}
    res = api.create_pet(payload, {})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_forbidden_role_for_endpoint(api):
    """PRD §2.1: "If the role is present but is not permitted to invoke
    the requested endpoint, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/validations/forbidden_role_for_endpoint
    """
    owner = register_owner()
    sitter = register_sitter()
    bg = create_pending_bg_check(sitter["id"])
    flag_bg_check(bg["id"], reason="test")
    # Owner attempting to reinstate the SUSPENDED Sitter (PlatformAdmin-only).
    res = api.reinstate_sitter(sitter["id"], make_owner_headers(owner["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_not_found_on_path_parameter(api):
    """PRD §2.7: "The path `/bookings/{id}` first looks up the booking by
    its `id`; if no row exists, the response is `ERR_NOT_FOUND` (HTTP 404).
    The same principle applies to every other `{id}` segment across the API."

    Design: Corner/validations/not_found_on_path_param
    """
    existing = register_owner()
    bogus_id = "00000000-0000-0000-0000-000000000099"
    res = api.get_owner(bogus_id, make_owner_headers(existing["id"]))
    validate_error(res, "ERR_NOT_FOUND")


def test_claims_adjuster_cannot_create_booking(api):
    """PRD §4 table row: `POST /api/v1/bookings` is authorized for
    `Owner` only.
    PRD §2.1: "If the role is present but is not permitted to invoke
    the requested endpoint, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/claims_adjuster_cannot_create_booking
    """
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-07-04T08:00:00Z", mg_scheduled_at="2026-07-04T07:30:00Z",
    )
    payload = create_booking_payload(
        owner["id"], sitter["id"], pet["id"],
        "2026-07-04T09:00:00Z", "2026-07-04T10:00:00Z",
        service_type="WALK_60MIN",
    )
    res = api.create_booking(payload, CLAIMS_ADJUSTER)
    validate_error(res, "ERR_FORBIDDEN")


def test_sitter_cannot_create_meet_and_greet(api):
    """PRD §4 table row: `POST /api/v1/meet-and-greets` is authorized for
    `Owner` only.
    PRD §2.1: "If the role is present but is not permitted to invoke
    the requested endpoint, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/sitter_cannot_create_meet_and_greet
    """
    sitter = register_sitter()
    owner = register_owner()
    pet = create_pet(owner["id"])
    payload = create_meet_and_greet_payload(
        owner["id"], sitter["id"], pet["id"], "2026-07-04T10:00:00Z",
    )
    res = api.create_meet_and_greet(payload, make_sitter_headers(sitter["id"]))
    validate_error(res, "ERR_FORBIDDEN")
