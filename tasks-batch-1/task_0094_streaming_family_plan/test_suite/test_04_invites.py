"""Family invites: the PENDING fork (ACCEPTED vs DECLINED), the seat-hold
money invariant, idempotency, insufficient-credit, and sweep-expiry.

Translates Difficulty/non_linear_state_machine (invite fork),
Difficulty/compensating_invariant (hold release), and
Corner/state_machines + Corner/validations instances.
"""
from test_helpers import (
    make_owner_headers,
    make_anonymous_headers,
    validate_success,
    validate_error,
    ApiErrorId,
)
import test_helpers as h


def test_invite_pending_fork_accept_vs_decline(api):
    """PRD §3.8: "A successful accept mints a brand-new profile on the account
    with kind ADULT and ACTIVE status, records that profile's id in the invite's
    created_profile_id field, and — unlike the other three endings — commits the
    seat hold". PRD §3.8: "Declining is the other anonymous, token-bearing action:
    allowed only while the invite is PENDING and only when the supplied token
    matches, it releases the hold and drives the invite to DECLINED." PRD §3.8:
    "The other three endings all release the hold back to wallet_credit_cents and
    create no profile."

    Design: Difficulty/non_linear_state_machine/invite_pending_fork_divergent_branches
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="owner6@x.com", initial_credit_cents=10000)
    inv_a = h.api_client.create_invite(
        {"account_id": account["id"], "invitee_email": "a@x.com"},
        make_owner_headers(account["id"]),
    ).json()["data"]
    inv_b = h.api_client.create_invite(
        {"account_id": account["id"], "invitee_email": "b@x.com"},
        make_owner_headers(account["id"]),
    ).json()["data"]

    accept = api.accept_invite(inv_a["id"], {"token": inv_a["token"]}, make_anonymous_headers())
    a_data = validate_success(accept, 200)
    assert a_data["status"] == "ACCEPTED"
    assert a_data["created_profile_id"] is not None
    assert h.is_valid_uuid(a_data["created_profile_id"])

    decline = api.decline_invite(inv_b["id"], {"token": inv_b["token"]}, make_anonymous_headers())
    b_data = validate_success(decline, 200)
    assert b_data["status"] == "DECLINED"
    assert b_data.get("created_profile_id") is None


def test_invite_decline_releases_hold_conserving_wallet(api):
    """PRD §3.8: "An owner sends an invite ... and debits a per-seat
    hold_amount_cents as a hold against the account's wallet_credit_cents." PRD
    §3.8: "Declining ... releases the hold and drives the invite to DECLINED."

    Send debit + decline release => wallet returns to its pre-send balance (10000).

    Design: Difficulty/compensating_invariant/invite_hold_release_conserves_wallet_money
    """
    s = h.create_account_with_pending_invite(invitee_email="c@x.com", initial_credit_cents=10000)
    invite = s["invite"]
    decline = api.decline_invite(invite["id"], {"token": invite["token"]}, make_anonymous_headers())
    validate_success(decline, 200)
    acct = h.fetch_account(s["account"]["id"])
    assert acct["wallet_credit_cents"] == 10000


def test_accept_already_accepted_invite_returns_invalid_state(api):
    """PRD §3.8: "All four terminal endings — ACCEPTED, DECLINED, EXPIRED,
    REVOKED — are reached only from PENDING, and a request to act on an invite
    that is no longer pending is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/accept_invite_twice_idempotency_rejected
    """
    s = h.create_account_with_pending_invite(invitee_email="x@x.com", initial_credit_cents=10000)
    invite = s["invite"]
    h.accept_invite(invite["id"], invite["token"])
    resp = api.accept_invite(invite["id"], {"token": invite["token"]}, make_anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_insufficient_credit_on_invite_send_rejected(api):
    """PRD §3.8: "Sending requires the wallet to hold at least the per-seat amount;
    insufficient credit is rejected with ERR_INSUFFICIENT_CREDIT."

    Design: Corner/validations/insufficient_credit_on_invite_send
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="nocred@x.com", initial_credit_cents=0)
    resp = api.create_invite(
        {"account_id": account["id"], "invitee_email": "y@x.com"},
        make_owner_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT.value, 402)


def test_accept_invite_expired_by_sweep_returns_invalid_state(api):
    """PRD §2.9: "every PENDING Invite whose expires_at the clock has now reached
    or passed transitions to EXPIRED and releases its seat hold". PRD §3.8: "a
    request to act on an invite that is no longer pending is rejected with
    ERR_INVALID_STATE."

    Design: Corner/validations/expired_invite_accept_rejected
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    h.set_clock("2026-06-27T00:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="exp@x.com", billing_anchor_day=27,
                               initial_credit_cents=10000)
    invite = h.api_client.create_invite(
        {"account_id": account["id"], "invitee_email": "z@x.com"},
        make_owner_headers(account["id"]),
    ).json()["data"]
    # Advance well past expires_at with sweeps to mark the invite EXPIRED.
    h.set_clock("2026-07-05T00:00:00Z", run_sweeps=True)
    resp = api.accept_invite(invite["id"], {"token": invite["token"]}, make_anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
