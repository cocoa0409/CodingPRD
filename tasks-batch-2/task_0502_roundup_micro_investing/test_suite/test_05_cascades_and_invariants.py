"""Transitive cascades, boundary-precision thresholds, conservation invariants,
and derived-field reconciliation.

Queue A (Difficulty) — transitive_cascade, boundary_precision_check,
compensating_invariant.
Queue B (Corner) — section: cross_cutting_complexity_layers
(derived_pending_roundup_reconciles_on_cancel).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiClient, ApiErrorId,
    TEST_USERS, make_investor_headers,
    create_plan, create_portfolio, create_verified_account, register_account,
    open_bucket, create_draft_order,
    add_card, add_accrual,
    create_offer, fund_account_via_found_money, create_found_money_reward_payload,
    setup_account_with_pending_accruals, run_sweep,
    setup_referred_invested_redeemed,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue A: transitive_cascade ──────────────────────────────────────────
def test_sweep_threshold_cascade_cash_to_invest_to_lot(api: ApiClient):
    """PRD §3.5: "If the post-sweep cash is at or above the threshold ... the
    system auto-creates and immediately settles an invest order, with `source` of
    `SWEEP`, into the account's primary taxable bucket for an amount equal to the
    entire post-sweep cash balance, running it through the invest-settlement
    described in §3.7."

    Design: Difficulty/transitive_cascade/sweep_threshold_cascade_cash_to_invest_to_lot_to_drift
    """
    # mgmt 25bps, threshold 500, five accruals each effective 100 (1850@x2) -> 500.
    acct, _ = setup_account_with_pending_accruals(
        purchases=[(2, 1850)] * 5, sweep_threshold_cents=500,
        management_fee_bps=25, target_allocation={"EQUITY": 100}, open_taxable=True,
    )
    inv = make_investor_headers(acct["id"])
    swept = run_sweep(acct["id"], expected_account_version=acct["version"])
    assert swept["cash_balance_cents"] == 0, "swept 500 then auto-invested the whole 500"
    assert swept["lifetime_invested_cents"] == 499, "gross 500, fee floor(500*25/10000)=1, net 499"
    orders = validate_success(api.list_orders(inv, params={"account_id": acct["id"], "source": "SWEEP"}))
    sweep_orders = [o for o in orders if o["source"] == "SWEEP" and o["status"] == "SETTLED"]
    assert sweep_orders, "an auto SWEEP INVEST order settled"
    lots = validate_success(api.list_tax_lots(ADMIN, params={"open_order_id": sweep_orders[0]["id"]}))
    assert any(l["cost_basis_cents"] == 499 for l in lots)


def test_sweep_cascade_single_asset_drift_recompute(api: ApiClient):
    """PRD §3.8: "When that total is zero — an empty bucket with no open lots —
    the `total_drift_bps` is 0 and `needs_rebalance` is false by definition.
    Otherwise, for each asset class in the model's `target_allocation`, the actual
    weight in basis points is the market value of the bucket's open lots tagged
    to that class, multiplied by 10000, divided by the total market value,
    floored ... The bucket `needs_rebalance` exactly when its `total_drift_bps` is
    strictly greater than the model portfolio's `drift_band_bps`."

    Design: Difficulty/transitive_cascade/sweep_threshold_cascade_cash_to_invest_to_lot_to_drift
    """
    acct, _ = setup_account_with_pending_accruals(
        purchases=[(2, 1850)] * 5, sweep_threshold_cents=500,
        management_fee_bps=25, target_allocation={"EQUITY": 100}, open_taxable=True,
    )
    inv = make_investor_headers(acct["id"])
    run_sweep(acct["id"], expected_account_version=acct["version"])
    buckets = validate_success(api.list_buckets(inv, params={"account_id": acct["id"]}))
    taxable = [b for b in buckets if b["bucket_type"] == "TAXABLE"][0]
    bucket = validate_success(api.get_bucket(taxable["id"], inv))
    # Single-asset EQUITY 100% portfolio: actual weight == target => drift 0.
    assert bucket["total_drift_bps"] == 0
    assert bucket["needs_rebalance"] is False


def test_account_restrict_cascade_freezes_bucket(api: ApiClient):
    """PRD §3.2: "Restricting an account cascades downward: every bucket of that
    account whose `status` is `OPEN` is set to `FROZEN`, and the account version is
    bumped."

    Design: Difficulty/transitive_cascade/account_restrict_cascade_freezes_buckets_blocks_orders
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    restricted = validate_success(api.restrict_account(acct["id"], ADMIN))
    assert restricted["kyc_status"] == "RESTRICTED"
    refetch = validate_success(api.get_bucket(bucket["id"], inv))
    assert refetch["status"] == "FROZEN", "OPEN bucket cascade-frozen by restrict"


def test_account_restrict_cascade_blocks_subsequent_submit(api: ApiClient):
    """PRD §3.6: "a `FROZEN` bucket blocks new invest and withdraw orders."
    PRD §3.7: "It is permitted only when the order is `DRAFT`, the target bucket
    is `OPEN`, and the owning account is `VERIFIED`; a non-verified account here
    yields `ERR_KYC_NOT_VERIFIED`."

    Design: Difficulty/transitive_cascade/account_restrict_cascade_freezes_buckets_blocks_orders
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    order = create_draft_order(acct["id"], bucket["id"], requested_amount_cents=100)
    fresh = validate_success(api.get_bucket(bucket["id"], inv))
    validate_success(api.restrict_account(acct["id"], ADMIN))
    res = api.submit_order(order["id"], {"expected_bucket_version": fresh["version"]}, inv)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Queue A: boundary_precision_check ────────────────────────────────────
def test_sweep_threshold_inclusive_at_exactly_threshold(api: ApiClient):
    """PRD §3.5: "If the post-sweep cash is at or above the threshold — the
    comparison is inclusive at the threshold — the system auto-creates and
    immediately settles an invest order, with `source` of `SWEEP`, into the
    account's primary taxable bucket for an amount equal to the entire
    post-sweep cash balance, running it through the invest-settlement described
    in §3.7."

    Design: Difficulty/boundary_precision_check/sweep_threshold_inclusive_at_exactly_threshold
    """
    # threshold 500, mgmt 0bps, five accruals each effective 100 -> exactly 500.
    acct, _ = setup_account_with_pending_accruals(
        purchases=[(2, 1850)] * 5, sweep_threshold_cents=500,
        management_fee_bps=0, target_allocation={"EQUITY": 100}, open_taxable=True,
    )
    inv = make_investor_headers(acct["id"])
    swept = run_sweep(acct["id"], expected_account_version=acct["version"])
    assert swept["lifetime_invested_cents"] == 500, "threshold 500 inclusive => auto-invest fired"
    assert swept["cash_balance_cents"] == 0, "entire 500 invested"
    orders = validate_success(api.list_orders(inv, params={"account_id": acct["id"], "source": "SWEEP"}))
    assert any(o["source"] == "SWEEP" and o["status"] == "SETTLED" for o in orders)


def test_sweep_just_below_threshold_does_not_auto_invest(api: ApiClient):
    """PRD §3.5: "If the post-sweep cash is below the threshold, the cash is
    swept but no invest order is created, and the cash simply sits in the
    buffer."

    Design: Difficulty/boundary_precision_check/sweep_threshold_inclusive_at_exactly_threshold
    """
    # threshold 600 with swept total exactly 500 (X-100): below threshold => no auto-invest.
    acct, _ = setup_account_with_pending_accruals(
        purchases=[(2, 1850)] * 5, sweep_threshold_cents=600,
        management_fee_bps=0, target_allocation={"EQUITY": 100}, open_taxable=True,
    )
    swept = run_sweep(acct["id"], expected_account_version=acct["version"])
    assert swept["cash_balance_cents"] == 500, "cash below threshold sits in the buffer"
    assert swept["lifetime_invested_cents"] == 0, "no auto-invest below threshold"


def test_empty_bucket_drift_zero_and_no_rebalance(api: ApiClient):
    """PRD §3.8: "When that total is zero — an empty bucket with no open lots —
    the `total_drift_bps` is 0 and `needs_rebalance` is false by definition."

    Design: Difficulty/boundary_precision_check/empty_bucket_drift_zero_and_no_rebalance
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    fresh = validate_success(api.get_bucket(bucket["id"], inv))
    assert fresh["total_drift_bps"] == 0
    assert fresh["needs_rebalance"] is False
    assert fresh["market_value_cents"] == 0


def test_empty_bucket_has_zero_invested_principal(api: ApiClient):
    """PRD §3.6: "`invested_principal_cents` is the sum of remaining cost basis
    across the bucket's `OPEN` tax lots; `market_value_cents` is the sum of those
    open lots' `market_value_cents`"
    PRD §3.8: "When that total is zero — an empty bucket with no open lots — the
    `total_drift_bps` is 0 and `needs_rebalance` is false by definition."

    Design: Difficulty/boundary_precision_check/empty_bucket_drift_zero_and_no_rebalance
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    fresh = validate_success(api.get_bucket(bucket["id"], inv))
    # Empty-set edge: no OPEN lots, so the basis-sum derived field is 0.
    assert fresh["invested_principal_cents"] == 0
    assert fresh["total_drift_bps"] == 0


# ─── Queue A: compensating_invariant ──────────────────────────────────────
def test_found_money_confirm_conserves_cash_equals_transaction(api: ApiClient):
    """PRD §3.10: "Confirmation moves the reward to the terminal `CONFIRMED`
    state, credits the account's `cash_balance_cents` by the reward's
    `rebate_amount_cents`, and writes a `FOUND_MONEY` cash transaction whose
    positive `amount_cents` equals that rebate — the credit to cash, the ledger
    amount, and the captured rebate are conserved and equal."

    Design: Difficulty/compensating_invariant/found_money_confirm_conserves_cash_equals_transaction
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    offer = create_offer(rebate_mode="PERCENT", rebate_percent_bps=500,
                         max_rebate_cents=1000, min_spend_cents=0, hold_days=0)
    reward = validate_success(api.create_found_money_reward(
        create_found_money_reward_payload(acct["id"], offer["id"], qualifying_spend_cents=10000),
        inv,
    ), expected_status=201)
    assert reward["rebate_amount_cents"] == 500, "floor(10000*500/10000)=500 <= cap 1000"
    validate_success(api.confirm_found_money_reward(reward["id"], ADMIN))
    after = validate_success(api.get_account(acct["id"], inv))
    assert after["cash_balance_cents"] == 500, "cash credited by exactly the rebate"
    txns = validate_success(api.list_cash_transactions(acct["id"], inv, params={"tx_type": "FOUND_MONEY"}))
    fm = [t for t in txns if t["tx_type"] == "FOUND_MONEY"]
    assert len(fm) == 1 and fm[0]["amount_cents"] == 500, "ledger amount equals cash delta (no drift)"


def test_found_money_confirm_flat_reward_conserved(api: ApiClient):
    """PRD §3.10: "Confirmation moves the reward to the terminal `CONFIRMED`
    state, credits the account's `cash_balance_cents` by the reward's
    `rebate_amount_cents`, and writes a `FOUND_MONEY` cash transaction whose
    positive `amount_cents` equals that rebate — the credit to cash, the ledger
    amount, and the captured rebate are conserved and equal."

    Design: Difficulty/compensating_invariant/found_money_confirm_conserves_cash_equals_transaction
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    # FLAT offer: rebate_amount is the fixed 750 regardless of spend.
    offer = create_offer(rebate_mode="FLAT", rebate_flat_cents=750,
                         max_rebate_cents=750, min_spend_cents=0, hold_days=0)
    reward = validate_success(api.create_found_money_reward(
        create_found_money_reward_payload(acct["id"], offer["id"], qualifying_spend_cents=20000),
        inv,
    ), expected_status=201)
    assert reward["rebate_amount_cents"] == 750
    confirmed = validate_success(api.confirm_found_money_reward(reward["id"], ADMIN))
    assert confirmed["status"] == "CONFIRMED"
    after = validate_success(api.get_account(acct["id"], inv))
    assert after["cash_balance_cents"] == 750, "cash credited by exactly the rebate"


def test_referral_qualify_conserves_referral_credits_both_sides(api: ApiClient):
    """PRD §3.11: "it credits the referrer account's `cash_balance_cents` by
    `bonus_cents`, credits the referred account's `cash_balance_cents` by
    `bonus_cents`, increases each account's derived `referral_credits_cents` by
    `bonus_cents`, and writes two `REFERRAL_BONUS` cash transactions, one per side,
    each with a positive `amount_cents` equal to the bonus."

    Design: Difficulty/compensating_invariant/referral_qualify_conserves_referral_credits_both_sides
    """
    referral, referrer, referred = setup_referred_invested_redeemed(bonus_cents=1000, invest_cents=600)
    qualified = validate_success(api.qualify_referral(referral["id"], ADMIN))
    assert qualified["status"] == "QUALIFIED"
    r_acct = validate_success(api.get_account(referrer["id"], make_investor_headers(referrer["id"])))
    b_acct = validate_success(api.get_account(referred["id"], make_investor_headers(referred["id"])))
    assert r_acct["referral_credits_cents"] == 1000
    assert r_acct["cash_balance_cents"] == 1000, "referrer cash credited by bonus"
    assert b_acct["referral_credits_cents"] == 1000
    # Each side has exactly one REFERRAL_BONUS credit of +1000.
    r_txns = validate_success(api.list_cash_transactions(
        referrer["id"], make_investor_headers(referrer["id"]), params={"tx_type": "REFERRAL_BONUS"}))
    b_txns = validate_success(api.list_cash_transactions(
        referred["id"], make_investor_headers(referred["id"]), params={"tx_type": "REFERRAL_BONUS"}))
    r_bonus = [t for t in r_txns if t["tx_type"] == "REFERRAL_BONUS"]
    b_bonus = [t for t in b_txns if t["tx_type"] == "REFERRAL_BONUS"]
    assert len(r_bonus) == 1 and r_bonus[0]["amount_cents"] == 1000
    assert len(b_bonus) == 1 and b_bonus[0]["amount_cents"] == 1000


def test_referral_qualify_credits_both_accounts_cash(api: ApiClient):
    """PRD §3.11: "it credits the referrer account's `cash_balance_cents` by
    `bonus_cents`, credits the referred account's `cash_balance_cents` by
    `bonus_cents`, increases each account's derived `referral_credits_cents` by
    `bonus_cents`, and writes two `REFERRAL_BONUS` cash transactions, one per
    side, each with a positive `amount_cents` equal to the bonus."

    Design: Difficulty/compensating_invariant/referral_qualify_conserves_referral_credits_both_sides
    """
    referral, referrer, referred = setup_referred_invested_redeemed(bonus_cents=2500, invest_cents=600)
    # Capture the referred account's pre-qualify cash so we can isolate the +bonus delta.
    b_before = validate_success(api.get_account(referred["id"], make_investor_headers(referred["id"])))
    validate_success(api.qualify_referral(referral["id"], ADMIN))
    r_after = validate_success(api.get_account(referrer["id"], make_investor_headers(referrer["id"])))
    b_after = validate_success(api.get_account(referred["id"], make_investor_headers(referred["id"])))
    assert r_after["cash_balance_cents"] == 2500, "referrer credited exactly the bonus"
    assert b_after["cash_balance_cents"] - b_before["cash_balance_cents"] == 2500, \
        "referred cash increases by exactly the bonus"


# ─── Queue B: cross_cutting (derived field reconciliation) ────────────────
def test_derived_pending_roundup_reconciles_on_cancel(api: ApiClient):
    """PRD §3.4: "An `Investor` may cancel it ... which moves it to the terminal
    `CANCELLED` state and decrements the account's `pending_roundup_cents` by that
    accrual's `effective_amount_cents` (a derived recompute)."

    Design: Corner/cross_cutting_complexity_layers/derived_pending_roundup_reconciles_on_cancel
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    card = add_card(acct["id"], multiplier=1, last_four="5050")
    accrual = add_accrual(acct["id"], card["id"], 1850)  # base 50 @x1 -> effective 50
    assert accrual["effective_amount_cents"] == 50
    before = validate_success(api.get_account(acct["id"], inv))
    assert before["pending_roundup_cents"] == 50
    cancelled = validate_success(api.cancel_roundup_accrual(accrual["id"], inv))
    assert cancelled["status"] == "CANCELLED"
    after = validate_success(api.get_account(acct["id"], inv))
    assert after["pending_roundup_cents"] == 0, "derived field reconciled to 0"
