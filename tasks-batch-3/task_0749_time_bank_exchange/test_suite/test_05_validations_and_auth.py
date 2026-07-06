"""Validation priority ladder — auth, RBAC, ownership, insufficient balance."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_member_headers, unauthenticated_headers,
    ApiErrorId,
    skill_offer_payload, exchange_payload,
    create_member, seed_balance,
    setup_two_members_and_offer,
)


def test_missing_auth_headers_return_unauthenticated(api):
    """PRD §2.1: "If either header is missing or syntactically malformed, the
    request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/validations/err_unauthenticated_returns_401
    """
    resp = api.create_skill_offer(
        skill_offer_payload("00000000-0000-0000-0000-000000000000"),
        headers=unauthenticated_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_platform_admin_creating_exchange_returns_role_not_permitted(api):
    """PRD §2.1: "If the header is well-formed but the declared role is not
    authorized for the endpoint, the request is rejected with
    ERR_ROLE_NOT_PERMITTED (HTTP 403)."
    PRD §4: "POST | /exchanges | Create an exchange linking an offer and a
    request. | Member"

    Design: Corner/validations/err_role_not_permitted_platformadmin_creating_exchange
    """
    ctx = setup_two_members_and_offer(requester_seed=0)
    r = get_success_data(api.create_skill_request(
        {"member_id": ctx["requester"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T10:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    resp = api.create_exchange(
        exchange_payload(ctx["offer"]["id"], r["id"]),
        headers=TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)


def test_member_acting_on_others_offer_returns_ownership_violation(api):
    """PRD §2.1: "A missing owner-match (a Member acting on a resource whose
    owning member does not equal X-User-ID, or on an exchange in which the
    requester and provider would resolve to the same member) is rejected with
    ERR_OWNERSHIP_VIOLATION (HTTP 403)."

    Design: Corner/validations/err_ownership_violation_member_acts_on_others_offer
    """
    m1 = create_member(email_prefix="ov1")
    m2 = create_member(email_prefix="ov2")
    offer = get_success_data(api.create_skill_offer(
        skill_offer_payload(m2["id"]),
        headers=make_member_headers(m2["id"]),
    ))
    resp = api.pause_skill_offer(offer["id"], headers=make_member_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)


def test_insufficient_balance_blocks_exchange_creation(api):
    """PRD §3.3: "The requester's forward_looking_balance_minutes must be at
    least committed_minutes, so that the pending debit implied by the booking
    cannot overdraw the account beyond commitments already in flight; a
    shortfall is rejected with ERR_INSUFFICIENT_BALANCE."

    Design: Corner/validations/err_insufficient_balance_on_exchange_create
    """
    ctx = setup_two_members_and_offer(requester_seed=0)
    r = get_success_data(api.create_skill_request(
        {"member_id": ctx["requester"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T10:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    resp = api.create_exchange(
        exchange_payload(ctx["offer"]["id"], r["id"]),
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)


def test_member_role_cannot_fulfill_redemption(api):
    """PRD §4: "POST | /redemptions/{id}/fulfill | Fulfil a requested redemption;
    re-checks balance. | PlatformAdmin"
    PRD §2.1: "If the header is well-formed but the declared role is not
    authorized for the endpoint, the request is rejected with
    ERR_ROLE_NOT_PERMITTED (HTTP 403)."

    Design: Corner/rbac/rbac_member_cannot_fulfill_redemption
    """
    m = create_member(email_prefix="rb")
    seed_balance(m["id"], 300)
    me = get_success_data(api.get_member(m["id"], headers=make_member_headers(m["id"])))
    red = get_success_data(api.create_redemption(
        {"member_id": m["id"], "reward_code": "FARMERS_MARKET_15",
         "expected_member_version": me["version"]},
        headers=make_member_headers(m["id"]),
    ))
    resp = api.fulfill_redemption(red["id"], headers=make_member_headers(m["id"]))
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)


def test_organizer_role_cannot_create_skill_offer(api):
    """PRD §4: "POST | /skill-offers | Create a skill offer owned by the acting
    member. | Member"
    PRD §2.1: "If the header is well-formed but the declared role is not
    authorized for the endpoint, the request is rejected with
    ERR_ROLE_NOT_PERMITTED (HTTP 403)."

    Design: Corner/rbac/rbac_organizer_cannot_create_offer
    """
    from test_helpers import make_organizer_headers
    m = create_member(email_prefix="oc")
    resp = api.create_skill_offer(
        skill_offer_payload(m["id"]),
        headers=make_organizer_headers(m["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
