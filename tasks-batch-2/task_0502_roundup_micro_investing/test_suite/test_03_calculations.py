"""Pinned-rule calculations: round-up, found-money rebate, sweep totalling,
invest settlement, and the FIFO/HIFO + first-cycle subscription dual variants.

Queue A (Difficulty) — dual_variant_calc, combinatorial_formula.
Queue B (Corner) — section: calculations.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiClient, ApiErrorId,
    TEST_USERS, make_investor_headers,
    create_plan, create_portfolio, create_verified_account,
    add_card, add_accrual,
    create_offer, fund_account_via_found_money,
    setup_funded_invest_ready, create_settled_invest_order, submit_order,
    setup_account_with_pending_accruals, run_sweep,
    setup_two_lot_inventory, settle_withdraw, lot_for_order,
    create_found_money_reward_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue B: calculations ────────────────────────────────────────────────
def test_whole_dollar_purchase_zero_roundup(api: ApiClient):
    """PRD §3.4: "a purchase that is already an exact multiple of 100 cents (a
    whole-dollar purchase) yields a `base_roundup_cents` of 0. The
    `effective_amount_cents` is the `base_roundup_cents` multiplied by the
    multiplier ... for a whole-dollar purchase the base is 0, so the effective
    amount is 0 regardless of the multiplier."

    Design: Corner/calculations/whole_dollar_purchase_zero_roundup
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    card = add_card(acct["id"], multiplier=10, last_four="1010")
    accrual = add_accrual(acct["id"], card["id"], 2000)
    assert accrual["base_roundup_cents"] == 0
    assert accrual["effective_amount_cents"] == 0
    refetch = validate_success(api.get_account(acct["id"], inv))
    assert refetch["pending_roundup_cents"] == 0


def test_found_money_percent_cap_binds(api: ApiClient):
    """PRD §3.10: "the raw rebate is the qualifying spend multiplied by the
    offer's `rebate_percent_bps`, divided by 10000, floored; the captured
    `rebate_amount_cents` is the smaller of that raw rebate and the offer's
    `max_rebate_cents`, so the cap binds whenever the floored percentage rebate
    would exceed it."

    Design: Corner/calculations/found_money_percent_cap_binds
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    offer = create_offer(rebate_mode="PERCENT", rebate_percent_bps=500,
                         max_rebate_cents=1000, min_spend_cents=0, hold_days=0)
    res = api.create_found_money_reward(
        create_found_money_reward_payload(acct["id"], offer["id"], qualifying_spend_cents=50000),
        inv,
    )
    data = validate_success(res, expected_status=201)
    assert data["rebate_amount_cents"] == 1000, "raw 2500 clamps to cap 1000"


def test_min_spend_not_met_rejects_reward(api: ApiClient):
    """PRD §3.10: "First, the qualifying spend must reach the offer's
    `min_spend_cents`: a spend below that minimum is rejected with
    `ERR_MIN_SPEND_NOT_MET`."

    Design: Corner/calculations/min_spend_not_met_rejects_reward
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    offer = create_offer(rebate_mode="FLAT", rebate_flat_cents=250,
                         max_rebate_cents=250, min_spend_cents=1000, hold_days=0)
    res = api.create_found_money_reward(
        create_found_money_reward_payload(acct["id"], offer["id"], qualifying_spend_cents=999),
        inv,
    )
    validate_error(res, ApiErrorId.ERR_MIN_SPEND_NOT_MET.value)


def test_sweep_below_threshold_no_invest(api: ApiClient):
    """PRD §3.5: "If the post-sweep cash is below the threshold, the cash is
    swept but no invest order is created, and the cash simply sits in the
    buffer."

    Design: Corner/calculations/sweep_below_threshold_no_invest
    """
    # purchases 1799@x3 -> 3, 1850@x2 -> 100, 437@x1 -> 63 => total 166 (< 500).
    acct, _ = setup_account_with_pending_accruals(
        purchases=[(3, 1799), (2, 1850), (1, 437)], sweep_threshold_cents=500,
    )
    swept = run_sweep(acct["id"], expected_account_version=acct["version"])
    assert swept["cash_balance_cents"] == 166, "166 below threshold 500: not invested"
    assert swept["lifetime_invested_cents"] == 0


# ─── Queue A: combinatorial_formula ───────────────────────────────────────
def test_sweep_round_per_accrual_then_sum_pinned_order(api: ApiClient):
    """PRD §3.5: "the swept total is the sum of each accrual's
    individually-frozen effective amount — round-per-accrual at accrual time,
    then sum at sweep time — and the system must not re-derive the total from
    raw purchase amounts and round once."

    Design: Difficulty/combinatorial_formula/sweep_round_per_accrual_then_sum_pinned_order
    """
    # 1799@x3 -> 3, 1850@x2 -> 100, 437@x1 -> 63 => 166 (round-per-accrual then sum).
    acct, accruals = setup_account_with_pending_accruals(
        purchases=[(3, 1799), (2, 1850), (1, 437)], sweep_threshold_cents=100000,
    )
    inv = make_investor_headers(acct["id"])
    swept = run_sweep(acct["id"], expected_account_version=acct["version"])
    assert swept["cash_balance_cents"] == 166, "3 + 100 + 63, round-per-accrual then sum"
    assert swept["pending_roundup_cents"] == 0
    for accrual in accruals:
        refetch = validate_success(api.get_roundup_accrual(accrual["id"], inv))
        assert refetch["status"] == "SWEPT"


def test_sweep_per_accrual_effective_amounts_frozen_at_accrual_time(api: ApiClient):
    """PRD §3.4: "The `effective_amount_cents` is the `base_roundup_cents`
    multiplied by the multiplier read from the referenced card at accrual time
    ... Both values are captured once at creation and frozen on the accrual
    row."

    Design: Difficulty/combinatorial_formula/sweep_round_per_accrual_then_sum_pinned_order
    """
    # Each accrual freezes its own effective amount: 1799@x3 -> 3, 1850@x2 -> 100, 437@x1 -> 63.
    acct, accruals = setup_account_with_pending_accruals(
        purchases=[(3, 1799), (2, 1850), (1, 437)], sweep_threshold_cents=100000,
    )
    by_purchase = {a["purchase_amount_cents"]: a for a in accruals}
    assert by_purchase[1799]["effective_amount_cents"] == 3, "base 1 * x3"
    assert by_purchase[1850]["effective_amount_cents"] == 100, "base 50 * x2"
    assert by_purchase[437]["effective_amount_cents"] == 63, "base 63 * x1"


def test_invest_settlement_pinned_eval_order_fee_then_lot(api: ApiClient):
    """PRD §3.7: "The `management_fee_cents` withheld is the gross multiplied by
    the plan's `management_fee_bps`, divided by 10000, floored. The net principal
    is the gross minus that fee. The order's `settled_amount_cents` is set to the
    net principal. The system then opens a new tax lot whose `cost_basis_cents`
    and `remaining_basis_cents` are both the net principal, debits the account's
    `cash_balance_cents` by the full gross ... and increases the account's
    `lifetime_invested_cents` by the net principal."

    Design: Difficulty/combinatorial_formula/invest_settlement_pinned_eval_order_fee_then_lot
    """
    acct, bucket = setup_funded_invest_ready(cash_cents=10000, management_fee_bps=25)
    inv = make_investor_headers(acct["id"])
    order = create_settled_invest_order(acct["id"], bucket["id"], 10000)
    assert order["management_fee_cents"] == 25, "floor(10000*25/10000)"
    assert order["settled_amount_cents"] == 9975, "net principal"
    lot = lot_for_order(order["id"])
    assert lot["cost_basis_cents"] == 9975
    refetch = validate_success(api.get_account(acct["id"], inv))
    assert refetch["cash_balance_cents"] == 0, "full gross 10000 debited"
    assert refetch["lifetime_invested_cents"] == 9975


def test_invest_settlement_opens_lot_with_net_basis_remaining(api: ApiClient):
    """PRD §3.7: "The system then opens a new tax lot whose `cost_basis_cents` and
    `remaining_basis_cents` are both the net principal, debits the account's
    `cash_balance_cents` by the full gross (the entire gross leaves cash; the fee
    is withheld to the platform), and increases the account's
    `lifetime_invested_cents` by the net principal."

    Design: Difficulty/combinatorial_formula/invest_settlement_pinned_eval_order_fee_then_lot
    """
    acct, bucket = setup_funded_invest_ready(cash_cents=10000, management_fee_bps=25)
    order = create_settled_invest_order(acct["id"], bucket["id"], 10000)
    lot = lot_for_order(order["id"])
    # net = 10000 - floor(10000*25/10000) = 9975; both basis fields equal net.
    assert lot["cost_basis_cents"] == 9975
    assert lot["remaining_basis_cents"] == 9975
    assert lot["status"] == "OPEN"


# ─── Queue A: dual_variant_calc ───────────────────────────────────────────
def test_withdraw_fifo_realized_gain(api: ApiClient):
    """PRD §3.7: "the basis consumed is that lot's `remaining_basis_cents`
    multiplied by the amount taken, divided by the lot's market value, floored;
    the realized gain accrued from the lot is the amount taken minus the basis
    consumed; the lot's `remaining_basis_cents` is reduced by the basis consumed,
    and if it reaches 0 the lot is marked `DEPLETED`"

    Design: Difficulty/dual_variant_calc/withdraw_fifo_vs_hifo_realized_gain_divergence
    """
    # lot A basis 5000 @+1000bps (mv 5500, earlier), lot B basis 5000 @+4000bps (mv 7000, later).
    acct, bucket, lot_a, lot_b = setup_two_lot_inventory(lot_a_bps=1000, lot_b_bps=4000)
    fifo = settle_withdraw(acct["id"], bucket["id"], 6000, lot_selection_method="FIFO")
    assert fifo["realized_gain_cents"] == 643, "FIFO consumes oldest (A then part of B)"
    assert fifo["settled_amount_cents"] == 6000


def test_withdraw_hifo_realized_gain_diverges_from_fifo(api: ApiClient):
    """PRD §3.7: "Because `HIFO` consumes the highest-appreciation lots first, it
    minimizes realized gain relative to `FIFO` on identical inventory, whereas
    `FIFO` consumes the oldest cost basis first."

    Design: Difficulty/dual_variant_calc/withdraw_fifo_vs_hifo_realized_gain_divergence
    """
    acct, bucket, lot_a, lot_b = setup_two_lot_inventory(lot_a_bps=1000, lot_b_bps=4000)
    hifo = settle_withdraw(acct["id"], bucket["id"], 6000, lot_selection_method="HIFO")
    assert hifo["realized_gain_cents"] == 1715, "HIFO consumes highest-gain lot (B) first"
    assert hifo["realized_gain_cents"] != 643, "diverges from the FIFO result"
    assert hifo["settled_amount_cents"] == 6000


def test_subscription_first_cycle_prorated_then_steady_state(api: ApiClient):
    """PRD §3.3: "In the first-cycle variant — applicable exactly when
    `months_billed` is 0 ... the fee is a half-month proration: the plan's
    `monthly_fee_cents` multiplied by one and divided by two, rounded up to the
    next whole cent."
    PRD §3.3: "In the steady-state variant — applicable whenever `months_billed`
    is at least 1 — the fee equals the plan's full `monthly_fee_cents`."

    Design: Difficulty/dual_variant_calc/subscription_first_cycle_vs_steady_state_fee
    """
    plan = create_plan(monthly_fee_cents=600, management_fee_bps=0)
    portfolio = create_portfolio()
    acct, _, _ = create_verified_account(plan=plan, portfolio=portfolio,
                                         sweep_threshold_cents=100000)
    fund_account_via_found_money(acct["id"], 2000)
    # First charge (months_billed == 0): ceil(600/2) == 300.
    first = validate_success(api.charge_subscription(acct["id"], ADMIN))
    assert first["cash_balance_cents"] == 1700, "2000 - 300 first-cycle prorated"
    assert first["months_billed"] == 1
    assert first["billing_status"] == "ACTIVE"
    # Second charge (months_billed == 1): full 600.
    second = validate_success(api.charge_subscription(acct["id"], ADMIN))
    assert second["cash_balance_cents"] == 1100, "1700 - 600 full fee"
    assert second["months_billed"] == 2


def test_subscription_first_cycle_fee_recorded_in_ledger(api: ApiClient):
    """PRD §3.3: "a `CashTransaction` of type `SUBSCRIPTION_FEE` is created with a
    negative `amount_cents` equal to the fee, the account's `cash_balance_cents` is
    debited by that fee (floored at zero, with any shortfall recorded rather than
    driving the balance negative), `months_billed` is incremented by one, and the
    account version is bumped."

    Design: Difficulty/dual_variant_calc/subscription_first_cycle_vs_steady_state_fee
    """
    plan = create_plan(monthly_fee_cents=600, management_fee_bps=0)
    portfolio = create_portfolio()
    acct, _, _ = create_verified_account(plan=plan, portfolio=portfolio,
                                         sweep_threshold_cents=100000)
    fund_account_via_found_money(acct["id"], 2000)
    inv = make_investor_headers(acct["id"])
    validate_success(api.charge_subscription(acct["id"], ADMIN))  # first cycle: fee 300
    txns = validate_success(api.list_cash_transactions(
        acct["id"], inv, params={"tx_type": "SUBSCRIPTION_FEE"}))
    fee_rows = [t for t in txns if t["tx_type"] == "SUBSCRIPTION_FEE"]
    assert len(fee_rows) == 1
    assert fee_rows[0]["amount_cents"] == -300, "first-cycle prorated fee recorded as -300"
