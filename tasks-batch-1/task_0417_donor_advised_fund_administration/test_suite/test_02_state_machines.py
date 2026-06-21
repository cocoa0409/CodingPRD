"""State-machine lifecycle tests: charity vetting cycle, grant fork, contribution and
rebalance transitions, terminal-state lockdowns, and invalid transitions.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fixtures, factories,
)
from test_helpers.fixtures import (
    SPONSOR_ADMIN, COMPLIANCE, CONTRIB_ADMIN, advisor_headers, officer_headers,
)


# ===========================================================================
# Non-linear state machine: Charity VETTED<->WATCHLISTED revision cycle
# ===========================================================================
def test_charity_watchlist_then_reapprove_returns_to_vetted(api):
    """PRD 3.2: "A **WATCHLIST** decision moves a charity from `PENDING_VETTING` to `WATCHLISTED`, or from `VETTED` to `WATCHLISTED`, setting `status` to `WATCHLISTED` and recording the `vetting_note`."
    PRD 3.2: "An **APPROVE** decision moves a charity from `PENDING_VETTING` to `VETTED`, or from `WATCHLISTED` back to `VETTED`."

    Design: Difficulty/non_linear_state_machine/charity_vetted_watchlisted_revision_cycle
    """
    sponsor = fixtures.create_sponsor()
    charity = fixtures.create_charity(sponsor["id"], legal_name="Red Cross", is_private_foundation=False)
    get_success_data(api.vet_charity(
        charity["id"], factories.vet_decision_payload("APPROVE", vetting_note="initial approve"),
        COMPLIANCE))

    get_success_data(api.vet_charity(
        charity["id"], factories.vet_decision_payload("WATCHLIST", vetting_note="flagged"),
        COMPLIANCE))
    final = validate_success(api.vet_charity(
        charity["id"], factories.vet_decision_payload("APPROVE", vetting_note="cleared"),
        COMPLIANCE))
    assert final["status"] == "VETTED"
    assert final["vetting_note"] == "cleared"


def test_charity_watchlist_sets_status_and_note(api):
    """PRD 3.2: "A **WATCHLIST** decision moves a charity from `PENDING_VETTING` to `WATCHLISTED`, or from `VETTED` to `WATCHLISTED`, setting `status` to `WATCHLISTED` and recording the `vetting_note`."

    Design: Difficulty/non_linear_state_machine/charity_vetted_watchlisted_revision_cycle
    """
    sponsor = fixtures.create_sponsor()
    charity = fixtures.create_vetted_charity(sponsor["id"])
    watchlisted = validate_success(api.vet_charity(
        charity["id"], factories.vet_decision_payload("WATCHLIST", vetting_note="hold"),
        COMPLIANCE))
    assert watchlisted["status"] == "WATCHLISTED"
    assert watchlisted["vetting_note"] == "hold"


# ===========================================================================
# Non-linear state machine: Grant fork into divergent terminals
# ===========================================================================
def test_grant_fork_reject_and_cancel_diverge(api):
    """PRD 3.5: "On rejection the grant's `status` becomes `REJECTED` and the account's `committed_grants_cents` and `grantable_balance_cents` are recomputed to release the amount."
    PRD 3.5: "the account owner"
    PRD (cont.): "may cancel a grant that is still in `SUBMITTED`, `APPROVED`, or `SCHEDULED`, moving its `status` to `CANCELLED` and recomputing `committed_grants_cents` and `grantable_balance_cents`."

    Design: Difficulty/non_linear_state_machine/grant_branching_fork_divergent_terminals
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-5")
    grant_a = fixtures.submit_grant(account["id"], charity["id"], 100000, "adv-5")
    grant_b = fixtures.submit_grant(account["id"], charity["id"], 100000, "adv-5")

    rejected = validate_success(api.reject_grant(grant_a["id"], officer_headers("officer-1")))
    cancelled = validate_success(api.cancel_grant(grant_b["id"], advisor_headers("adv-5")))
    assert rejected["status"] == "REJECTED"
    assert cancelled["status"] == "CANCELLED"

    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["committed_grants_cents"] == 0


def test_grant_reject_releases_commitment(api):
    """PRD 3.5: "On rejection the grant's `status` becomes `REJECTED` and the account's `committed_grants_cents` and `grantable_balance_cents` are recomputed to release the amount."

    Design: Difficulty/non_linear_state_machine/grant_branching_fork_divergent_terminals
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-5b")
    grant = fixtures.submit_grant(account["id"], charity["id"], 100000, "adv-5b")
    committed_before = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))["committed_grants_cents"]
    assert committed_before == 100000
    rejected = validate_success(api.reject_grant(grant["id"], officer_headers("officer-1b")))
    assert rejected["status"] == "REJECTED"
    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["committed_grants_cents"] == 0


# ===========================================================================
# Corner: state machines
# ===========================================================================
def test_contribution_starts_in_pending(api):
    """PRD 3.3: "A new contribution starts with `status` `PENDING` and a null `fair_market_value_cents`."

    Design: Corner/state_machines/contribution_starts_in_pending
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-s1")
    contrib = validate_success(api.create_contribution(
        factories.create_cash_contribution_payload(account["id"], 100000),
        advisor_headers("adv-s1")), expected_status=201)
    assert contrib["status"] == "PENDING"
    assert contrib["fair_market_value_cents"] is None


def test_settle_already_settled_contribution_invalid_state(api):
    """PRD 3.3: "The contribution's `status` becomes `SETTLED`, which is terminal — attempting to settle an already-settled contribution is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/settle_already_settled_contribution_returns_invalid_state
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-s2")
    contrib = get_success_data(api.create_contribution(
        factories.create_cash_contribution_payload(account["id"], 300000),
        advisor_headers("adv-s2")))
    validate_success(api.settle_contribution(contrib["id"], CONTRIB_ADMIN))
    validate_error(api.settle_contribution(contrib["id"], CONTRIB_ADMIN),
                   ApiErrorId.ERR_INVALID_STATE.value)
    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["cash_balance_cents"] == 300000  # not double-credited


def test_vet_revoked_charity_is_terminal(api):
    """PRD 3.2: "REVOKED` is terminal — no decision moves a charity out of it."

    Design: Corner/state_machines/vet_revoked_charity_is_terminal_returns_invalid_state
    """
    sponsor = fixtures.create_sponsor()
    charity = fixtures.create_vetted_charity(sponsor["id"])
    get_success_data(api.vet_charity(
        charity["id"], factories.vet_decision_payload("REVOKE", vetting_note="revoked"), COMPLIANCE))
    validate_error(api.vet_charity(
        charity["id"], factories.vet_decision_payload("APPROVE"), COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = get_success_data(api.get_charity(charity["id"], COMPLIANCE))
    assert refreshed["status"] == "REVOKED"


def test_revet_into_current_state_invalid_state(api):
    """PRD 3.2: "Recording a decision that would re-enter the charity's current state (for example, approving a charity that is already `VETTED`) is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/revet_into_current_state_returns_invalid_state
    """
    sponsor = fixtures.create_sponsor()
    charity = fixtures.create_vetted_charity(sponsor["id"])
    validate_error(api.vet_charity(
        charity["id"], factories.vet_decision_payload("APPROVE"), COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE.value)


def test_contribution_reject_no_valuation_no_receipt(api):
    """PRD 3.3: "A `ContributionAdmin` may instead reject a `PENDING` contribution, moving its `status` to `REJECTED` with no valuation, no ledger entry, and no receipt; `REJECTED` is likewise terminal."

    Design: Corner/state_machines/contribution_reject_side_effects_no_valuation
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-s5")
    contrib = get_success_data(api.create_contribution(
        factories.create_cash_contribution_payload(account["id"], 400000),
        advisor_headers("adv-s5")))
    rejected = validate_success(api.reject_contribution(contrib["id"], CONTRIB_ADMIN))
    assert rejected["status"] == "REJECTED"
    assert rejected["fair_market_value_cents"] is None
    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["cash_balance_cents"] == 0
    receipts = get_success_data(api.list_receipts(
        CONTRIB_ADMIN, params={"contribution_id": contrib["id"]}))
    assert receipts == []


def test_pay_grant_from_submitted_invalid_state(api):
    """PRD 3.6: "A `GrantOfficer` pays a `SCHEDULED` grant, advancing its `status` to `PAID`."
    PRD 3.5: "a transition requested from a state that does not permit it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pay_grant_from_submitted_returns_invalid_state
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-s6")
    grant = fixtures.submit_grant(account["id"], charity["id"], 100000, "adv-s6")
    validate_error(api.pay_grant(grant["id"], officer_headers("officer-s6")),
                   ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = get_success_data(api.get_grant(grant["id"], SPONSOR_ADMIN))
    assert refreshed["status"] == "SUBMITTED"


def test_rebalance_redeem_to_cash_compensation_exact_divisor(api):
    """PRD 3.4: "Because the buy branch floors and the redeem branch ceils, the operation is not symmetric — buying then redeeming the same amount can leave residual units behind."
    PRD 3.4: "An allocation whose `units_micro` reaches 0 after a full redemption has its `status` set to `LIQUIDATED`."

    Design: Corner/state_machines/rebalance_execute_redeem_to_cash_compensation
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    account = fixtures.create_account(sponsor["id"], "adv-s7")
    fixtures.fund_account_with_cash(account["id"], 50000, "adv-s7")
    fixtures.buy_into_pool(account["id"], pool["id"], 50000, "adv-s7", target_pct_bps=5000)

    redeem = get_success_data(api.create_rebalance_order(
        factories.create_rebalance_order_payload(account["id"], 50000, source_pool_id=pool["id"]),
        advisor_headers("adv-s7")))
    executed = validate_success(api.execute_rebalance_order(redeem["id"], advisor_headers("adv-s7")))
    assert executed["status"] == "EXECUTED"

    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["cash_balance_cents"] == 50000
    assert acct["invested_value_cents"] == 0
    allocs = get_success_data(api.list_allocations(
        advisor_headers("adv-s7"), params={"donor_account_id": account["id"]}))
    assert allocs[0]["units_micro"] == 0
    assert allocs[0]["status"] == "LIQUIDATED"


# ===========================================================================
# Corner: endpoints — rebalance cancel
# ===========================================================================
def test_rebalance_cancel_draft_no_balance_change(api):
    """PRD 3.4: "An owner may also cancel a draft order, moving its `status` to `CANCELLED` with no balance change; cancellation is owner-scoped under the same `ERR_NOT_ACCOUNT_OWNER` check."

    Design: Corner/endpoints/rebalance_cancel_draft_no_balance_change
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    account = fixtures.create_account(sponsor["id"], "adv-e4")
    fixtures.fund_account_with_cash(account["id"], 100000, "adv-e4")
    order = get_success_data(api.create_rebalance_order(
        factories.create_rebalance_order_payload(account["id"], 50000, target_pool_id=pool["id"], target_pct_bps=5000),
        advisor_headers("adv-e4")))
    cancelled = validate_success(api.cancel_rebalance_order(order["id"], advisor_headers("adv-e4")))
    assert cancelled["status"] == "CANCELLED"
    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["cash_balance_cents"] == 100000
    assert acct["invested_value_cents"] == 0
