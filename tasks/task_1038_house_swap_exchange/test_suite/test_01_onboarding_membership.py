"""Member onboarding, membership activation, and universal auth (RBAC).

Covers Corner instances from the entities, cross_cutting_complexity_layers, and
rbac sections that concern registration and membership lifecycle.
"""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    register_member_payload, create_membership_payload,
    make_member_headers, make_admin_headers, make_anonymous_headers,
    register_member, subscribe, subscribe_and_activate, set_clock,
    assert_member,
)

ADMIN = make_admin_headers()
ANON = make_anonymous_headers()


def test_register_member_defaults_trust_and_unverified(api):
    """PRD §3.1: "A freshly registered member starts `UNVERIFIED` in their
    `verification_status`, holds no membership so their `active_membership_tier`
    is null, carries a `settled_points_balance` and `available_points_balance` of
    0, and is seeded with a `trust_score` of 50."

    Design: Corner/entities/register_member_defaults_trust_and_unverified
    """
    res = api.register_member(register_member_payload(full_name="New Member", home_city="Reno"), ANON)
    member = validate_success(res, 201)
    assert_member(member)
    assert member["trust_score"] == 50
    assert member["verification_status"] == "UNVERIFIED"
    assert member["active_membership_tier"] is None
    assert member["settled_points_balance"] == 0
    assert member["available_points_balance"] == 0


def test_register_member_missing_full_name_returns_validation(api):
    """PRD §3.1: "A new member joins by self-registering with an `email` (unique
    across all members and non-empty), a `full_name`, and a `home_city`."
    PRD §2.9: "Body well-formedness comes fourth — required fields present, enum
    values legal, integers within their declared ranges — otherwise `ERR_VALIDATION`."

    Design: Corner/entities/register_member_missing_full_name_returns_validation
    """
    payload = register_member_payload(home_city="Reno")
    del payload["full_name"]
    res = api.register_member(payload, ANON)
    validate_error(res, "ERR_VALIDATION")


def test_get_member_nonexistent_returns_not_found(api):
    """PRD §2.9: "the first identifier that does not resolve produces its own
    not-found error: a missing member yields `ERR_MEMBER_NOT_FOUND`".

    Design: Corner/entities/get_member_nonexistent_returns_not_found
    """
    res = api.get_member(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_MEMBER_NOT_FOUND")


def test_create_membership_with_unknown_member_returns_not_found(api):
    """PRD §2.9: "Existence is validated left-to-right through the path and then
    through the body's foreign keys, and the first identifier that does not resolve
    produces its own not-found error: a missing member yields `ERR_MEMBER_NOT_FOUND`".

    Design: Corner/entities/create_membership_with_unknown_member_returns_not_found
    """
    res = api.create_membership(
        create_membership_payload(NON_EXISTENT_UUID, "BASIC"),
        make_member_headers(NON_EXISTENT_UUID))
    validate_error(res, "ERR_MEMBER_NOT_FOUND")


def test_activate_second_membership_returns_duplicate_active(api):
    """PRD §3.1: "it is refused with `ERR_DUPLICATE_ACTIVE_MEMBERSHIP` if the member
    already holds another membership in `ACTIVE` status — a member may have at most
    one active membership at a time."

    Design: Corner/cross_cutting_complexity_layers/activate_second_membership_returns_duplicate_active
    """
    set_clock("2026-07-01T00:00:00Z")
    m = register_member()
    subscribe_and_activate(m["id"], "BASIC")   # first membership ACTIVE
    second = subscribe(m["id"], "PLUS")         # second PENDING_ACTIVATION
    res = api.activate_membership(second["id"], ADMIN)
    validate_error(res, "ERR_DUPLICATE_ACTIVE_MEMBERSHIP")


def test_member_cannot_activate_membership_returns_unauthorized(api):
    """PRD §2.1: "If the headers are well-formed but the role — or the specific
    member behind it — is not permitted to perform the operation, the request is
    rejected with `ERR_UNAUTHORIZED`."
    PRD §3.1: "The membership is born in `PENDING_ACTIVATION` and remains inert
    until a `PlatformAdmin` activates it."

    Design: Corner/rbac/member_cannot_activate_membership_returns_unauthorized
    """
    m = register_member()
    membership = subscribe(m["id"], "BASIC")
    res = api.activate_membership(membership["id"], make_member_headers(m["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    these declared role names, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    m = register_member()
    res = api.get_member(m["id"], {})   # no X-User-ID / X-User-Role
    validate_error(res, "ERR_UNAUTHENTICATED")
