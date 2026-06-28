"""Savings sweeps, compensating reversals, optimistic concurrency, immediate consistency."""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers, make_agent_headers,
    setup_pending_ledger_with_savings_account,
    setup_transferred_ledger_with_savings_account,
    setup_won_case, setup_cancel_failed_subscription, setup_proposed_case,
    get_ledger_entry_for_member,
    ApiErrorId,
)


def test_transfer_cascade_bumps_savings_balance(api):
    """PRD §3.10: "A successful transfer advances the entry's `transfer_status` to `TRANSFERRED`, stamps `transferred_utc` with the current clock value, and increments the savings account's `balance_cents` by the entry's `member_net_cents`."

    Design: Difficulty/transitive_cascade/ledger_transfer_cascade_savings_balance_depth2
    """
    member, agent, sa, entry = setup_pending_ledger_with_savings_account(offered_annual_cost_cents=48000)
    mh = make_member_headers(member["id"])
    transferred = validate_success(api.transfer_ledger_entry(entry["id"], headers=mh))
    assert transferred["transfer_status"] == "TRANSFERRED"
    acct = validate_success(api.get_savings_account(sa["id"], headers=mh))
    assert acct["balance_cents"] == 7800


def test_transfer_sets_transferred_status(api):
    """PRD §3.10: "The owning member may **transfer** it, sweeping their net share into their designated savings account."
    PRD §3.10: "A successful transfer advances the entry's `transfer_status` to `TRANSFERRED ... and increments the savings account's `balance_cents` by the entry's `member_net_cents`."

    Design: Difficulty/transitive_cascade/ledger_transfer_cascade_savings_balance_depth2
    """
    member, agent, sa, entry = setup_pending_ledger_with_savings_account(offered_annual_cost_cents=48000)
    mh = make_member_headers(member["id"])
    transferred = validate_success(api.transfer_ledger_entry(entry["id"], headers=mh))
    assert transferred["transfer_status"] == "TRANSFERRED"
    assert transferred["member_net_cents"] == 7800


def test_transfer_then_reverse_conserves_balance(api):
    """PRD §3.10: "reversal advances the entry's `transfer_status` to `REVERSED`, decrements the savings account's `balance_cents` by the same `member_net_cents` it previously added (restoring the balance to its pre-transfer value), and clears `transferred_utc`."

    Design: Difficulty/compensating_invariant/transfer_then_reverse_conserves_member_net_in_savings
    """
    member, agent, sa, entry = setup_transferred_ledger_with_savings_account(offered_annual_cost_cents=48000)
    resp = api.reverse_ledger_entry(entry["id"], headers=make_agent_headers(agent["id"]))
    data = validate_success(resp)
    assert data["transfer_status"] == "REVERSED"
    acct = validate_success(api.get_savings_account(sa["id"], headers=make_member_headers(member["id"])))
    assert acct["balance_cents"] == 0


def test_reverse_restores_pre_transfer_balance(api):
    """PRD §3.10: "This is the only path by which a balance grows."
    PRD §3.10: "decrements the savings account's `balance_cents` by the same `member_net_cents` it previously added (restoring the balance to its pre-transfer value)".

    Design: Difficulty/compensating_invariant/transfer_then_reverse_conserves_member_net_in_savings
    """
    member, agent, sa, entry = setup_transferred_ledger_with_savings_account(offered_annual_cost_cents=48000)
    mh = make_member_headers(member["id"])
    before = validate_success(api.get_savings_account(sa["id"], headers=mh))
    assert before["balance_cents"] == 7800
    api.reverse_ledger_entry(entry["id"], headers=make_agent_headers(agent["id"]))
    after = validate_success(api.get_savings_account(sa["id"], headers=mh))
    assert after["balance_cents"] == 0


def test_transfer_without_savings_destination(api):
    """PRD §3.10: "if there is no savings destination set or the destination account is not `OPEN`, the transfer is rejected with `ERR_NO_SAVINGS_DESTINATION`."

    Design: Corner/validations/transfer_without_savings_destination
    """
    # WON case produces a PENDING ledger entry; member has no savings_account_id set.
    member, agent, charge, case = setup_won_case(offered_annual_cost_cents=48000, charge_amount_cents=5000)
    entry = get_ledger_entry_for_member(member["id"])
    resp = api.transfer_ledger_entry(entry["id"], headers=make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_SAVINGS_DESTINATION.value)


def test_occ_stale_subscription_request_cancel(api):
    """PRD §2.7: "If that value does not equal the subscription's current `version ... the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the member must re-read the subscription before retrying."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_subscription_request_cancel
    """
    # PRD §2.7 example: a concierge agent flips the subscription to
    # CANCEL_REQUESTED and then to CANCEL_FAILED, each bumping the version.
    # CANCEL_FAILED is an allowed source state for request-cancel, so the
    # state-transition check passes and the optimistic-concurrency staleness
    # check is the one that fires when the member carries the stale version.
    member, agent, sub = setup_cancel_failed_subscription(monthly_cost_cents=1500)
    mh = make_member_headers(member["id"])
    # The member last observed the subscription at its original ACTIVE version
    # (0); the concierge round-trip has since advanced version to 2.
    stale_version = 0
    assert sub["version"] != stale_version
    resp = api.request_cancel_subscription(
        sub["id"], {"expected_subscription_version": stale_version}, headers=mh
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_won_savings_visible_immediately(api):
    """PRD §2.6: "The platform uses an immediate-consistency model: when an operation has side effects on more than one resource, all of those effects are applied together as part of the same request."
    PRD §3.6: "Acceptance advances the case to `WON ... member_net_savings_cents` is computed as the gross savings minus the success fee."

    Design: Corner/consistency_model/won_case_savings_visible_immediately
    """
    member, agent, charge, case = setup_proposed_case(48000, charge_amount_cents=5000)
    resp = api.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"]))
    data = validate_success(resp)
    assert data["status"] == "WON"
    assert data["member_net_savings_cents"] == 7800
