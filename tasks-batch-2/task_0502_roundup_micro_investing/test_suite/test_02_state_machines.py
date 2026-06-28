"""State-machine behaviour: invalid transitions, terminal lockdown, parallel
dimensions, the referral redemption cycle, and the order invest/withdraw branch.

Queue A (Difficulty) — non_linear_state_machine.
Queue B (Corner) — section: state_machines.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiClient, ApiErrorId,
    TEST_USERS, make_investor_headers,
    create_plan, create_portfolio, create_verified_account,
    register_account, open_bucket, create_draft_order,
    add_card, add_accrual, issue_referral, redeem_referral,
    setup_funded_invest_ready, create_settled_invest_order, submit_order,
    settle_withdraw, lot_for_order,
)
from test_helpers import api_client as _ac  # noqa

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue B: invalid transitions / terminal lockdown / precondition ──────
def test_cancel_already_cancelled_accrual_invalid_state(api: ApiClient):
    """PRD §3.4: "An `Investor` may cancel it — permitted only while it is
    `PENDING` — which moves it to the terminal `CANCELLED` state and decrements
    the account's `pending_roundup_cents` by that accrual's
    `effective_amount_cents` (a derived recompute)."

    Design: Corner/state_machines/cancel_already_cancelled_accrual_invalid_state
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    card = add_card(acct["id"], multiplier=1, last_four="1212")
    accrual = add_accrual(acct["id"], card["id"], 150)
    validate_success(api.cancel_roundup_accrual(accrual["id"], inv))
    res = api.cancel_roundup_accrual(accrual["id"], inv)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    refetch = validate_success(api.get_roundup_accrual(accrual["id"], inv))
    assert refetch["status"] == "CANCELLED"


def test_settle_draft_order_without_submit_invalid_state(api: ApiClient):
    """PRD §3.7: "Settlement is permitted only when the order is `SUBMITTED` and
    the target bucket is `OPEN`."

    Design: Corner/state_machines/settle_draft_order_without_submit_invalid_state
    """
    acct, _, _ = create_verified_account()
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    order = create_draft_order(acct["id"], bucket["id"], requested_amount_cents=100)
    res = api.settle_order(order["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    refetch = validate_success(api.get_order(order["id"], make_investor_headers(acct["id"])))
    assert refetch["status"] == "DRAFT"


def test_terminal_referral_revoked_cannot_redeem(api: ApiClient):
    """PRD §3.11: "The issuing `Investor` revokes an `ISSUED` referral — permitted
    only while `ISSUED` and the acting account is the referrer — moving it to the
    terminal `REVOKED` state."

    Design: Corner/state_machines/terminal_referral_revoked_cannot_redeem
    """
    plan = create_plan()
    portfolio = create_portfolio()
    referrer = register_account(plan["id"], portfolio["id"])
    redeemer = register_account(plan["id"], portfolio["id"])
    referral = issue_referral(referrer["id"], code="REVOK-T")
    validate_success(api.revoke_referral(referral["id"], make_investor_headers(referrer["id"])))
    res = api.redeem_referral(
        referral["id"], {"referred_account_id": redeemer["id"]},
        make_investor_headers(redeemer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    refetch = validate_success(api.get_referral(referral["id"], ADMIN))
    assert refetch["status"] == "REVOKED"


def test_bucket_close_with_open_lot_rejected(api: ApiClient):
    """PRD §3.6: "a close attempt while open lots or non-terminal orders remain
    is rejected with `ERR_BUCKET_NOT_EMPTY`."

    Design: Corner/state_machines/bucket_close_with_open_lot_rejected
    """
    acct, bucket = setup_funded_invest_ready(cash_cents=5000, management_fee_bps=0)
    create_settled_invest_order(acct["id"], bucket["id"], 5000)  # opens one OPEN lot
    inv = make_investor_headers(acct["id"])
    res = api.close_bucket(bucket["id"], inv)
    validate_error(res, ApiErrorId.ERR_BUCKET_NOT_EMPTY.value)
    refetch = validate_success(api.get_bucket(bucket["id"], inv))
    assert refetch["status"] == "OPEN"


def test_parallel_dims_billing_advances_without_kyc(api: ApiClient):
    """PRD §3.2: "Charging the monthly subscription fee is a `PlatformAdmin`
    action permitted when the account is `TRIAL` or `ACTIVE`; it advances
    `billing_status` to `ACTIVE` (a `TRIAL` account becomes `ACTIVE`..."
    PRD §3.2: "An account evolves along two independent dimensions."

    Design: Corner/state_machines/parallel_dims_billing_advances_without_kyc
    """
    plan = create_plan()
    portfolio = create_portfolio()
    acct = register_account(plan["id"], portfolio["id"])  # PENDING_KYC / TRIAL
    res = api.charge_subscription(acct["id"], ADMIN)
    data = validate_success(res)
    assert data["billing_status"] == "ACTIVE", "billing dimension advanced"
    assert data["kyc_status"] == "PENDING_KYC", "kyc dimension unaffected"
    assert data["months_billed"] == 1


# ─── Queue A: non_linear_state_machine ────────────────────────────────────
def test_referral_cycle_redeemed_back_to_issued(api: ApiClient):
    """PRD §3.11: "A redeemer who has not yet qualified may release the
    redemption — permitted only while `REDEEMED` — which returns the referral to
    `ISSUED` and clears `referred_account_id` to null, freeing the code for another
    account to redeem."

    Design: Difficulty/non_linear_state_machine/referral_cycle_redeemed_back_to_issued
    """
    plan = create_plan()
    portfolio = create_portfolio()
    referrer = register_account(plan["id"], portfolio["id"])
    b1 = register_account(plan["id"], portfolio["id"])
    referral = issue_referral(referrer["id"], code="CYCLE-A")
    redeem_referral(referral["id"], b1["id"])
    res = api.release_redemption(referral["id"], make_investor_headers(b1["id"]))
    data = validate_success(res)
    assert data["status"] == "ISSUED", "cycle returns to ISSUED"
    assert data.get("referred_account_id") is None, "referred_account_id cleared to null"


def test_referral_cycle_release_allows_reredemption_by_new_account(api: ApiClient):
    """PRD §3.11: "A redeemer who has not yet qualified may release the
    redemption — permitted only while `REDEEMED` — which returns the referral to
    `ISSUED` and clears `referred_account_id` to null, freeing the code for another
    account to redeem."

    Design: Difficulty/non_linear_state_machine/referral_cycle_redeemed_back_to_issued
    """
    plan = create_plan()
    portfolio = create_portfolio()
    referrer = register_account(plan["id"], portfolio["id"])
    b1 = register_account(plan["id"], portfolio["id"])
    b2 = register_account(plan["id"], portfolio["id"])
    referral = issue_referral(referrer["id"], code="CYCLE-B")
    redeem_referral(referral["id"], b1["id"])
    validate_success(api.release_redemption(referral["id"], make_investor_headers(b1["id"])))
    # A different account may now redeem the freed code (A -> B -> A loop, then re-redeem).
    res = api.redeem_referral(
        referral["id"], {"referred_account_id": b2["id"]}, make_investor_headers(b2["id"])
    )
    data = validate_success(res)
    assert data["status"] == "REDEEMED"
    assert data["referred_account_id"] == b2["id"]


def test_order_branching_invest_then_withdraw_distinct_side_effects(api: ApiClient):
    """PRD §3.7: "The system then opens a new tax lot whose `cost_basis_cents` and
    `remaining_basis_cents` are both the net principal, debits the account's
    `cash_balance_cents` by the full gross ... and increases the account's
    `lifetime_invested_cents` by the net principal."
    PRD §3.7: "When the walk completes, the order's `settled_amount_cents` is the
    total proceeds realized and `realized_gain_cents` is the summed realized gain;
    the proceeds are credited to the account's `cash_balance_cents` through a
    `WITHDRAW_PROCEEDS` cash transaction."

    Design: Difficulty/non_linear_state_machine/order_branching_invest_vs_withdraw_distinct_side_effects
    """
    acct, bucket = setup_funded_invest_ready(cash_cents=5000, management_fee_bps=0)
    inv = make_investor_headers(acct["id"])
    invest = create_settled_invest_order(acct["id"], bucket["id"], 5000)
    assert invest["management_fee_cents"] == 0
    lot = lot_for_order(invest["id"])
    assert lot["cost_basis_cents"] == 5000
    # WITHDRAW branch on the same SUBMITTED->SETTLED edge: consumes the lot.
    withdraw = settle_withdraw(acct["id"], bucket["id"], 5000, lot_selection_method="FIFO")
    assert withdraw["realized_gain_cents"] == 0, "lot at +0bps: mv == basis"
    assert withdraw["settled_amount_cents"] == 5000
    refetched_lot = validate_success(api.get_tax_lot(lot["id"], inv))
    assert refetched_lot["status"] == "DEPLETED", "consumed lot is DEPLETED after withdraw"


def test_order_invest_settle_debits_cash_and_increments_lifetime(api: ApiClient):
    """PRD §3.7: "debits the account's `cash_balance_cents` by the full gross (the
    entire gross leaves cash; the fee is withheld to the platform), and
    increases the account's `lifetime_invested_cents` by the net principal."

    Design: Difficulty/non_linear_state_machine/order_branching_invest_vs_withdraw_distinct_side_effects
    """
    acct, bucket = setup_funded_invest_ready(cash_cents=5000, management_fee_bps=0)
    inv = make_investor_headers(acct["id"])
    create_settled_invest_order(acct["id"], bucket["id"], 5000)
    after_invest = validate_success(api.get_account(acct["id"], inv))
    # INVEST branch side effects: cash fully debited, lifetime principal recorded.
    assert after_invest["cash_balance_cents"] == 0, "full gross debited on INVEST settle"
    assert after_invest["lifetime_invested_cents"] == 5000, "net principal added (mgmt 0bps)"
