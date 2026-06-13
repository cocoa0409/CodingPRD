"""Redemption, the void compensation, and cash-drawer reconciliation / conservation."""
from test_helpers import (
    validate_success, validate_error,
    constants,
    fixtures as fx,
    make_officer_headers,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _drawer_balance(api, shop_id):
    res = api.get_shop_drawer(shop_id, MANAGER)
    return res.json()["data"][0]["balance_cents"]


# ── Corner: redeem reconciles the drawer balance ──

def test_redeem_reconciles_drawer_balance(api):
    """PRD §3.6: "On redemption the system appends a `FinanceTransaction` of kind
    `REDEMPTION_PAYOFF` with a positive `amount_cents` equal to the payoff (computed as
    in §3.4), increases the drawer's `balance_cents` by the payoff, and moves both the
    loan and its pawn item to `REDEEMED`."

    Design: Corner/cross_cutting_complexity_layers/redeem_reconciles_drawer_balance
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.DAY_30)  # payoff 22700 at day 30
    validate_success(api.redeem_loan(ctx["loan"]["id"], make_officer_headers("officer-1")), 200)
    # Disburse -20000 then redeem +22700 -> 2700.
    assert _drawer_balance(api, ctx["shop"]["id"]) == 2700


# ── Difficulty: void conserves the cash-drawer balance ──

def test_disbursement_drives_drawer_negative(api):
    """PRD §2.8: "it decreases when cash leaves the drawer (a loan disbursement, a
    layaway refund)".
    PRD §3.3: "a `FinanceTransaction` of kind `DISBURSEMENT` is appended to the loan's
    ledger with an `amount_cents` equal to the negative of the principal and a
    `periods_in_charge` of 0, and the drawer's `balance_cents` is decreased by the principal."

    Design: Difficulty/compensating_invariant/void_conserves_cash_drawer_balance
    """
    ctx = fx.setup_active_loan()  # principal 20000
    assert _drawer_balance(api, ctx["shop"]["id"]) == -20000


def test_void_returns_drawer_to_pre_origination_balance(api):
    """PRD §2.8: "for any single loan, the sum of its `FinanceTransaction` amounts across
    the disbursement entry (recorded as a negative equal to the disbursed principal) and
    any void-reversal entry (recorded as a positive equal to that same principal) is
    exactly zero — voiding a loan must return the drawer to its pre-origination balance
    with respect to that loan."
    PRD §3.6: "A void appends a `FinanceTransaction` of kind `VOID_REVERSAL` with a
    positive `amount_cents` equal to the loan's `principal_cents` (cash returns to the
    drawer), increases the drawer's `balance_cents` by that principal, moves the loan to
    `VOIDED`, and reverts the pawn item to `APPRAISED` so it can be re-pledged."

    Design: Difficulty/compensating_invariant/void_conserves_cash_drawer_balance
    """
    ctx = fx.setup_active_loan()
    assert _drawer_balance(api, ctx["shop"]["id"]) == -20000
    validate_success(api.void_loan(ctx["loan"]["id"], make_officer_headers("officer-1")), 200)
    assert _drawer_balance(api, ctx["shop"]["id"]) == 0
    item = validate_success(api.get_item(ctx["item"]["id"], OFFICER), 200)
    assert item["status"] == "APPRAISED"


# ── Corner: a second redeem on a terminal loan is an invalid transition ──

def test_redeem_from_redeemed_returns_invalid_state(api):
    """PRD §2.11: "that the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)".
    PRD §3.6: "A `LoanOfficer` may redeem a loan that is `ACTIVE` or `IN_GRACE` with
    `police_hold_flag` false, when the redemption payoff is paid in full."

    Design: Corner/state_machines/redeem_from_redeemed_returns_invalid_state
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.DAY_30)
    validate_success(api.redeem_loan(ctx["loan"]["id"], make_officer_headers("officer-1")), 200)
    res = api.redeem_loan(ctx["loan"]["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_INVALID_STATE", 409)
