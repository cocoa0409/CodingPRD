"""Authentication, role permission, ownership, suspension, and validation ordering."""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers, make_admin_headers,
    create_member, setup_confirmed_charge, setup_active_subscription,
    create_agent, create_negotiation_case_payload,
    ApiErrorId,
)


def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "If either header is missing on a protected endpoint, or the role is not one the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    member = create_member()
    resp = api.get_member(member["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_member_success_fee_pct_out_of_range(api):
    """PRD §3.1: "which when supplied must be strictly greater than zero and strictly less than one (a value at or below zero or at or above one is rejected with `ERR_VALUE_OUT_OF_RANGE`)."

    Design: Corner/errors/value_out_of_range_success_fee_pct
    """
    resp = api.create_member({"email": "e2@x.com", "full_name": "E2", "success_fee_pct": 1.5})
    validate_error(resp, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)


def test_member_cannot_suspend_member(api):
    """PRD §2.1: "When the headers are present and recognized but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/member_cannot_suspend_member
    """
    actor = create_member(email="r2@x.com")
    target = create_member(email="r2b@x.com")
    resp = api.suspend_member(target["id"], headers=make_member_headers(actor["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_suspended_member_cannot_open_case(api):
    """PRD §3.1: "A suspended member cannot initiate negotiations, request a cancellation, dispute a claim, or transfer savings — any such member-initiated attempt while suspended is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 403)."

    Design: Corner/validations/suspended_member_cannot_open_case
    """
    member, la, charge = setup_confirmed_charge(amount_cents=5000)
    agent = create_agent()
    api.suspend_member(member["id"], headers=make_admin_headers())
    resp = api.create_negotiation_case(
        create_negotiation_case_payload(member["id"], charge["id"], agent["id"]),
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value)


def test_ownership_beats_charge_in_use_on_dismiss(api):
    """PRD §2.9: "then resource ownership for member-owned mutations (`ERR_NOT_RESOURCE_OWNER`); then existence of path-referenced resources".
    PRD §2.1: "When a `Member` attempts to act on a resource whose owning `member_id` is not their own `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/ownership_vs_referential_on_dismiss_other_member_in_use
    """
    owner, charge, sub = setup_active_subscription(monthly_cost_cents=5000, charge_amount_cents=5000)
    other = create_member(email="other-dismiss@x.com")
    resp = api.dismiss_recurring_charge(charge["id"], headers=make_member_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    after = validate_success(api.get_recurring_charge(charge["id"],
                                                      headers=make_member_headers(owner["id"])))
    assert after["status"] == "CONFIRMED"


def test_non_owner_dismiss_does_not_change_charge(api):
    """PRD §2.1: "Member-owned resources — a member's subscriptions, negotiation cases, refund claims, savings ledger entries, savings accounts, linked accounts, and recurring charges — may be mutated only by their owner."
    PRD §2.1: "the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/ownership_vs_referential_on_dismiss_other_member_in_use
    """
    owner, charge, sub = setup_active_subscription(monthly_cost_cents=5000, charge_amount_cents=5000)
    other = create_member(email="other-dismiss2@x.com")
    resp = api.dismiss_recurring_charge(charge["id"], headers=make_member_headers(other["id"]))
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
