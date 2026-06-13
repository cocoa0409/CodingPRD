"""Order placement, reserve, matching cascade, fees, cancellation, freeze cascade,
optimistic concurrency, and order-shape validations."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_trader_headers, find_balance, assert_order, assert_trade,
    assert_balance_partition_reconciles, ApiErrorId,
    set_clock, create_usd_btc_with_fees, create_usd_asset, create_btc_asset,
    create_tier_base_fee_schedule, create_account, create_account_at_tier,
    credit_fiat, create_and_credit_deposit, get_account_version, place_order,
    rest_sell_limit, setup_seller_with_resting_btc_ask, setup_buyer_with_usd,
    setup_trade_match_scenario,
)

OP = TEST_USERS["operator_headers"]


def _order_payload(account_id, **kw):
    base = {"account_id": account_id, "base_asset": "BTC", "quote_asset": "USD"}
    base.update(kw)
    return base


# ===========================================================================
# Difficulty / dual_variant_calc — maker vs taker fee diverge on same notional
# ===========================================================================
def test_maker_taker_fee_diverge_same_notional(api):
    """PRD §3.9: "The maker side pays this notional multiplied by the maker rate of
    the resting account's tier, divided by ten thousand to convert basis points to a
    fraction, then rounded half up to the quote asset's decimals; this becomes
    `maker_fee`. The taker side pays the same notional multiplied by the taker rate
    of the incoming account's tier, divided by ten thousand, rounded half up to the
    quote asset's decimals; this becomes `taker_fee`."

    Design: Difficulty/dual_variant_calc/maker_taker_fee_diverges_same_notional
    """
    seller, maker, buyer = setup_trade_match_scenario(
        clock="2026-02-01T00:00:00Z", sell_price=40000, buyer_usd=60000)
    # buyer sends a MARKET BUY 1.0 BTC that crosses
    place_order(buyer["id"], "BTC", "USD", "BUY", "MARKET", 1.0, time_in_force="IOC")
    trader = make_trader_headers(buyer["id"])
    trades, _ = validate_paginated(api.list_trades(
        trader, params={"maker_order_id": maker["id"]}))
    assert len(trades) == 1
    trade = trades[0]
    assert trade["taker_order_id"] != maker["id"]
    assert trade["price"] == 40000
    assert trade["quantity"] == 1.0
    assert trade["notional_usd"] == 40000
    # maker 10 bps -> 40.00; taker 30 bps -> 120.00
    assert trade["maker_fee"] == pytest.approx(40.00, abs=0.01)
    assert trade["taker_fee"] == pytest.approx(120.00, abs=0.01)
    assert_trade(trade)


def test_trade_records_both_order_ids_and_notional(api):
    """PRD §3.8: "A `Trade` is appended recording the `maker_order_id` (the resting
    order), the `taker_order_id` (the incoming order), the `base_asset`, the
    `quote_asset`, the `price` (the resting maker's limit price), the `quantity`
    exchanged, the `notional_usd` (the quantity times the price times the quote
    asset's spot price)"

    Design: Difficulty/dual_variant_calc/maker_taker_fee_diverges_same_notional
    """
    seller, maker, buyer = setup_trade_match_scenario(
        clock="2026-02-01T00:00:00Z", sell_price=40000, buyer_usd=60000)
    taker = place_order(buyer["id"], "BTC", "USD", "BUY", "MARKET", 1.0,
                        time_in_force="IOC")
    trader = make_trader_headers(buyer["id"])
    trades, _ = validate_paginated(api.list_trades(
        trader, params={"taker_order_id": taker["id"]}))
    assert len(trades) == 1
    trade = trades[0]
    assert trade["maker_order_id"] == maker["id"]
    assert trade["taker_order_id"] == taker["id"]
    assert trade["notional_usd"] == 40000


# ===========================================================================
# Difficulty / combinatorial_formula — MARKET BUY reserve nested min/max/tier
# ===========================================================================
def test_market_buy_reserve_nested_then_settles(api):
    """PRD §3.8: "For a `MARKET` `BUY`, the system takes the best resting ask — the
    lowest `limit_price` among `OPEN` resting `SELL` orders for that pair, rejecting
    with `ERR_NO_LIQUIDITY` if the book is empty — and reserves `quantity` multiplied
    by that best ask, then scaled up by a five-percent slippage ceiling (one plus
    five hundredths) and again by one plus the worst-case taker fee fraction."

    Design: Difficulty/combinatorial_formula/market_buy_reserve_nested_min_max_tier
    """
    set_clock("2026-03-01T00:00:00Z")
    create_usd_btc_with_fees()
    seller = create_account_at_tier("TIER_1", email="rsell@x.com", full_name="RSeller")
    create_and_credit_deposit(seller["id"], "BTC", 1.0, 35000, required_confirmations=1)
    rest_sell_limit(seller["id"], "BTC", "USD", 1.0, 40000)
    buyer = setup_buyer_with_usd(usd=50000, email="rbuy@x.com", full_name="RBuyer")
    # MARKET BUY 1.0 BTC; reserve = 1.0 * 40000 * 1.05 * 1.003 = 42126.00; order fully fills
    place_order(buyer["id"], "BTC", "USD", "BUY", "MARKET", 1.0, time_in_force="GTC")
    trader = make_trader_headers(buyer["id"])
    bals, _ = validate_paginated(api.list_balances(trader, params={"account_id": buyer["id"], "asset": "USD"}))
    usd = find_balance(bals, "USD")
    # post-fill: 50000 - 40000 - 120.00 taker fee = 9880.00; reserve released
    assert usd["available_amount"] == pytest.approx(9880.00, abs=0.01)
    assert usd["reserved_amount"] == pytest.approx(0.0, abs=0.01)


def test_market_buy_reserve_headroom_rejects_when_below_reserve(api):
    """PRD §3.8: "The reserved quantity is rounded up to the reserve asset's decimal
    precision so the reserve is never short, and the system requires the reserve
    asset's `available_amount` to be at least the reserved quantity, rejecting
    otherwise with `ERR_INSUFFICIENT_AVAILABLE`."

    Design: Difficulty/combinatorial_formula/market_buy_reserve_nested_min_max_tier
    """
    set_clock("2026-03-15T00:00:00Z")
    create_usd_btc_with_fees()
    seller = create_account_at_tier("TIER_1", email="rsell2@x.com", full_name="RSeller2")
    create_and_credit_deposit(seller["id"], "BTC", 1.0, 35000, required_confirmations=1)
    rest_sell_limit(seller["id"], "BTC", "USD", 1.0, 40000)
    # buyer holds 41000 USD: enough to pay the 40000 fill but below the
    # 1.0 * 40000 * 1.05 * 1.003 = 42126.00 worst-case reserve
    buyer = setup_buyer_with_usd(usd=41000, email="rbuy2@x.com", full_name="RBuyer2")
    version = get_account_version(buyer["id"], make_trader_headers(buyer["id"]))
    resp = api.create_order(
        _order_payload(buyer["id"], side="BUY", order_type="MARKET", quantity=1.0,
                       time_in_force="GTC", expected_account_version=version),
        make_trader_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE.value)


def test_taker_volume_round_then_sum_order_pinned(api):
    """PRD §3.9: "The rounding order is pinned: each qualifying trade's notional is
    rounded to two USD decimals first, and the rounded per-trade values are then
    summed, rather than summing exact values and rounding once."

    Design: Difficulty/combinatorial_formula/taker_volume_30d_round_then_sum_order_pinned
    """
    set_clock("2026-04-01T00:00:00Z")
    create_usd_asset()
    create_btc_asset(symbol="TKN", decimals=8, required_confirmations=1,
                     is_fiat=False, min_withdrawal_amount=0.001, network_fee=0.001,
                     spot_price_usd=1)
    create_tier_base_fee_schedule()
    maker_acc = create_account_at_tier("TIER_1", email="vmak@x.com", full_name="VMaker")
    create_and_credit_deposit(maker_acc["id"], "TKN", 3000, 1, required_confirmations=1)
    taker_acc = create_account_at_tier("TIER_1", email="vtak@x.com", full_name="VTaker")
    credit_fiat(taker_acc["id"], "USD", 1000)
    # three resting SELL LIMITs of 1.00005 TKN @ 100.00 => notional 100.005 each
    for _ in range(3):
        rest_sell_limit(maker_acc["id"], "TKN", "USD", 1.00005, 100.00)
    # taker fills each in a separate MARKET BUY
    for _ in range(3):
        place_order(taker_acc["id"], "TKN", "USD", "BUY", "MARKET", 1.00005,
                    time_in_force="IOC")
    trader = make_trader_headers(taker_acc["id"])
    acc = validate_success(api.get_account(taker_acc["id"], trader))
    # round-then-sum: 100.01 + 100.01 + 100.01 == 300.03 (NOT 300.02)
    assert acc["taker_volume_30d_usd"] == pytest.approx(300.03, abs=0.001)


def test_single_taker_trade_notional_rounded_to_cents(api):
    """PRD §3.9: "each qualifying trade's notional is rounded to two USD decimals
    first, and the rounded per-trade values are then summed, rather than summing
    exact values and rounding once."
    PRD §3.8: "the `notional_usd` (the quantity times the price times the quote
    asset's spot price)"

    Design: Difficulty/combinatorial_formula/taker_volume_30d_round_then_sum_order_pinned
    """
    set_clock("2026-04-15T00:00:00Z")
    create_usd_asset()
    create_btc_asset(symbol="TKN", decimals=8, required_confirmations=1,
                     is_fiat=False, min_withdrawal_amount=0.001, network_fee=0.001,
                     spot_price_usd=1)
    create_tier_base_fee_schedule()
    maker_acc = create_account_at_tier("TIER_1", email="vmak2@x.com", full_name="VMaker2")
    create_and_credit_deposit(maker_acc["id"], "TKN", 3000, 1, required_confirmations=1)
    taker_acc = create_account_at_tier("TIER_1", email="vtak2@x.com", full_name="VTaker2")
    credit_fiat(taker_acc["id"], "USD", 1000)
    # one resting SELL LIMIT 1.00005 TKN @ 100.00 => exact notional 100.005
    rest_sell_limit(maker_acc["id"], "TKN", "USD", 1.00005, 100.00)
    place_order(taker_acc["id"], "TKN", "USD", "BUY", "MARKET", 1.00005,
                time_in_force="IOC")
    trader = make_trader_headers(taker_acc["id"])
    acc = validate_success(api.get_account(taker_acc["id"], trader))
    # the single trade's notional 100.005 rounds half-up to 100.01
    assert acc["taker_volume_30d_usd"] == pytest.approx(100.01, abs=0.001)


# ===========================================================================
# Difficulty / non_linear_state_machine — order parallel fill axis
# ===========================================================================
def _two_buyers_setup():
    set_clock("2026-06-01T00:00:00Z")
    create_usd_btc_with_fees()
    seller = create_account_at_tier("TIER_1", email="pmsell@x.com", full_name="PSeller")
    create_and_credit_deposit(seller["id"], "BTC", 1.0, 35000, required_confirmations=1)
    rest = rest_sell_limit(seller["id"], "BTC", "USD", 1.0, 40000)
    b1 = setup_buyer_with_usd(usd=30000, email="pb1@x.com", full_name="PB1")
    b2 = setup_buyer_with_usd(usd=30000, email="pb2@x.com", full_name="PB2")
    return rest, b1, b2


def test_resting_order_partially_filled_after_first_fill(api):
    """PRD §3.8: "An order that is partially filled moves
    `OPEN → PARTIALLY_FILLED`"
    PRD §3.8: "Both orders have their `filled_quantity` incremented"

    Design: Difficulty/non_linear_state_machine/order_parallel_fill_axis_partial_then_fill
    """
    rest, b1, b2 = _two_buyers_setup()
    place_order(b1["id"], "BTC", "USD", "BUY", "MARKET", 0.5, time_in_force="IOC")
    seller_trader = make_trader_headers(rest["account_id"])
    order = validate_success(api.get_order(rest["id"], seller_trader))
    assert order["lifecycle_status"] == "PARTIALLY_FILLED"
    assert order["filled_quantity"] == pytest.approx(0.5, abs=1e-9)


def test_resting_order_filled_after_second_fill(api):
    """PRD §3.8: "a resting order completed by a later incoming order moves
    `PARTIALLY_FILLED → FILLED`, likewise zeroing its `reserved_remaining`."

    Design: Difficulty/non_linear_state_machine/order_parallel_fill_axis_partial_then_fill
    """
    rest, b1, b2 = _two_buyers_setup()
    place_order(b1["id"], "BTC", "USD", "BUY", "MARKET", 0.5, time_in_force="IOC")
    place_order(b2["id"], "BTC", "USD", "BUY", "MARKET", 0.5, time_in_force="IOC")
    seller_trader = make_trader_headers(rest["account_id"])
    order = validate_success(api.get_order(rest["id"], seller_trader))
    assert order["lifecycle_status"] == "FILLED"
    assert order["filled_quantity"] == pytest.approx(1.0, abs=1e-9)
    assert order["reserved_remaining"] == pytest.approx(0.0, abs=1e-9)


# ===========================================================================
# Difficulty / transitive_cascade — account freeze depth-3 cancel/release
# ===========================================================================
def _frozen_setup_with_open_order():
    set_clock("2026-08-01T00:00:00Z")
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="frz@x.com", full_name="Frz")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 50000)
    order = place_order(acc_id, "BTC", "USD", "BUY", "LIMIT", 1.0,
                        limit_price=40000, time_in_force="GTC")
    return acc_id, order


def test_freeze_sets_account_frozen_and_cancels_order(api):
    """PRD §3.2: "An `Operator` freezes an account — typically on a sanctions hit —
    moving it along `ACTIVE → FROZEN`"
    PRD §2.5: "every order belonging to that account that is still `OPEN` or
    `PARTIALLY_FILLED` is cancelled, and each such order's reserved funds are
    released back to spendable balance exactly as in an ordinary cancellation."

    Design: Difficulty/transitive_cascade/account_freeze_depth3_cancel_release_cascade
    """
    acc_id, order = _frozen_setup_with_open_order()
    frozen = validate_success(api.freeze_account(acc_id, OP))
    assert frozen["account_status"] == "FROZEN"
    cancelled = validate_success(api.get_order(order["id"], OP))
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["reserved_remaining"] == pytest.approx(0.0, abs=0.01)


def test_freeze_releases_order_reserve_back_to_available(api):
    """PRD §2.5: "each such order's reserved funds are released back to spendable
    balance exactly as in an ordinary cancellation."
    PRD §3.8: "release reserved_remaining back to Balance.available"

    Design: Difficulty/transitive_cascade/account_freeze_depth3_cancel_release_cascade
    """
    acc_id, order = _frozen_setup_with_open_order()
    validate_success(api.freeze_account(acc_id, OP))
    bals, _ = validate_paginated(api.list_balances(OP, params={"account_id": acc_id, "asset": "USD"}))
    usd = find_balance(bals, "USD")
    assert usd["reserved_amount"] == pytest.approx(0.0, abs=0.01)
    assert usd["available_amount"] == pytest.approx(50000.0, abs=0.01)


# ===========================================================================
# Difficulty / priority_pair_validation_conflict — frozen beats insufficient
# ===========================================================================
def test_frozen_account_order_returns_frozen_not_insufficient(api):
    """PRD §3.8: "The account must be `ACTIVE`, or the placement is rejected with
    `ERR_ACCOUNT_FROZEN`."
    PRD §2.10: "the general rule is that authentication, authorization, ownership,
    existence, and state-machine legality are always resolved before domain-specific
    business rules"

    Design: Difficulty/priority_pair_validation_conflict/frozen_beats_insufficient_state_vs_fiscal
    """
    set_clock("2026-09-01T00:00:00Z")
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="pf1@x.com", full_name="PF1")
    acc_id = acc["id"]
    # FROZEN and 0 USD available (cannot fund) — both checks would fire
    validate_success(api.freeze_account(acc_id, OP))
    version = validate_success(api.get_account(acc_id, OP))["version"]
    resp = api.create_order(
        _order_payload(acc_id, side="BUY", order_type="LIMIT", quantity=1.0,
                       limit_price=40000, time_in_force="GTC",
                       expected_account_version=version),
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_FROZEN.value)


def test_active_account_short_funds_returns_insufficient(api):
    """PRD §3.8: "there must be enough spendable balance to cover the computed
    reserve, or the placement is rejected with `ERR_INSUFFICIENT_AVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_beats_insufficient_state_vs_fiscal
    """
    set_clock("2026-09-01T00:00:00Z")
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="pf2@x.com", full_name="PF2")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 100)  # ACTIVE but far short of the 40120 reserve
    version = get_account_version(acc_id, make_trader_headers(acc_id))
    resp = api.create_order(
        _order_payload(acc_id, side="BUY", order_type="LIMIT", quantity=1.0,
                       limit_price=40000, time_in_force="GTC",
                       expected_account_version=version),
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE.value)


# ===========================================================================
# Difficulty / cross_entity_state_dependency — order requires ACTIVE account
# ===========================================================================
def test_order_on_frozen_account_rejected(api):
    """PRD §3.2: "Freezing blocks all trading, withdrawal, and staking writes: any
    such attempt against a frozen account is rejected with `ERR_ACCOUNT_FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/order_requires_account_active
    """
    set_clock("2026-12-05T00:00:00Z")
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="ce2@x.com", full_name="CE2")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 50000)  # well-funded, so only the frozen check can fire
    validate_success(api.freeze_account(acc_id, OP))
    version = validate_success(api.get_account(acc_id, OP))["version"]
    resp = api.create_order(
        _order_payload(acc_id, side="BUY", order_type="LIMIT", quantity=0.5,
                       limit_price=40000, time_in_force="GTC",
                       expected_account_version=version),
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_FROZEN.value)


def test_order_on_active_account_after_unfreeze_succeeds(api):
    """PRD §3.2: "An `Operator` reverses the freeze, moving the account along
    `FROZEN → ACTIVE`; this is defined only when the account is currently `FROZEN`."
    PRD §3.8: "The account must be `ACTIVE`, or the placement is rejected with
    `ERR_ACCOUNT_FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/order_requires_account_active
    """
    set_clock("2026-12-05T00:00:00Z")
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="ce2b@x.com", full_name="CE2B")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 50000)
    validate_success(api.freeze_account(acc_id, OP))
    validate_success(api.unfreeze_account(acc_id, OP))
    reactivated = validate_success(api.get_account(acc_id, OP))
    assert reactivated["account_status"] == "ACTIVE"
    # the order now places successfully against the ACTIVE account
    order = place_order(acc_id, "BTC", "USD", "BUY", "LIMIT", 0.5,
                        limit_price=40000, time_in_force="GTC")
    assert order["lifecycle_status"] == "OPEN"


# ===========================================================================
# Difficulty / compensating_invariant — cancel conserves quote available+reserved
# ===========================================================================
def _account_with_open_buy_limit():
    set_clock("2027-03-01T00:00:00Z")
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="ci1@x.com", full_name="CI1")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 50000)
    order = place_order(acc_id, "BTC", "USD", "BUY", "LIMIT", 1.0,
                        limit_price=40000, time_in_force="GTC")
    return acc_id, order


def test_place_buy_limit_reserves_quote(api):
    """PRD §3.8: "For a `LIMIT` `BUY`, the reserve asset is the `quote_asset` and the
    reserved quantity is the gross cost — `quantity` multiplied by `limit_price` —
    scaled up by the worst-case taker fee, that is, multiplied by one plus thirty
    basis points expressed as a fraction (thirty divided by ten thousand)."

    Design: Difficulty/compensating_invariant/order_cancel_conserves_quote_spendable_plus_reserved
    """
    acc_id, order = _account_with_open_buy_limit()
    trader = make_trader_headers(acc_id)
    bals, _ = validate_paginated(api.list_balances(trader, params={"account_id": acc_id, "asset": "USD"}))
    usd = find_balance(bals, "USD")
    # 1.0 * 40000 * 1.003 = 40120.00 reserved; available 9880.00; sum 50000
    assert usd["available_amount"] == pytest.approx(9880.00, abs=0.01)
    assert usd["reserved_amount"] == pytest.approx(40120.00, abs=0.01)
    assert usd["available_amount"] + usd["reserved_amount"] == pytest.approx(50000, abs=0.01)


def test_cancel_buy_limit_restores_quote_available(api):
    """PRD §3.8: "release reserved_remaining back to Balance.available (BUY: quote;
    SELL: base); set reserved_remaining = 0"
    PRD §2.6: "The `total_amount` is the sum of `available_amount`,
    `reserved_amount`, and `held_amount`"

    Design: Difficulty/compensating_invariant/order_cancel_conserves_quote_spendable_plus_reserved
    """
    acc_id, order = _account_with_open_buy_limit()
    trader = make_trader_headers(acc_id)
    validate_success(api.cancel_order(order["id"], trader))
    bals, _ = validate_paginated(api.list_balances(trader, params={"account_id": acc_id, "asset": "USD"}))
    usd = find_balance(bals, "USD")
    assert usd["available_amount"] == pytest.approx(50000, abs=0.01)
    assert usd["reserved_amount"] == pytest.approx(0.0, abs=0.01)
    assert usd["available_amount"] + usd["reserved_amount"] == pytest.approx(50000, abs=0.01)


# ===========================================================================
# Corner / state_machines — cancel already-cancelled order
# ===========================================================================
def test_cancel_already_cancelled_order_invalid_state(api):
    """PRD §3.8: "The `lifecycle_status` ranges over `OPEN`, `PARTIALLY_FILLED`,
    `FILLED`, and `CANCELLED`, with `FILLED` and `CANCELLED` terminal."
    PRD §2.10: "a transition attempted from a state where it is not defined is
    rejected with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/cancel_already_cancelled_order_returns_invalid_state
    """
    set_clock("2027-03-10T00:00:00Z")
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="cc@x.com", full_name="CC")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 50000)
    order = place_order(acc_id, "BTC", "USD", "BUY", "LIMIT", 1.0,
                        limit_price=40000, time_in_force="GTC")
    trader = make_trader_headers(acc_id)
    validate_success(api.cancel_order(order["id"], trader))
    resp = api.cancel_order(order["id"], trader)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner / validations — order-shape and trading-gate checks
# ===========================================================================
def test_trading_below_tier1_rejected(api):
    """PRD §3.8: "Trading requires the account's `kyc_tier` to be at least `TIER_1`"
    PRD §3.8: "any of these violations is rejected with `ERR_KYC_TIER_INSUFFICIENT`
    for the tier failure"

    Design: Corner/validations/trading_below_tier1_rejected
    """
    create_usd_btc_with_fees()
    acc = create_account(email="t0@x.com", full_name="T0")  # TIER_0
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 50000)
    version = get_account_version(acc_id, make_trader_headers(acc_id))
    resp = api.create_order(
        _order_payload(acc_id, side="BUY", order_type="LIMIT", quantity=0.1,
                       limit_price=40000, time_in_force="GTC",
                       expected_account_version=version),
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_KYC_TIER_INSUFFICIENT.value)


def test_limit_order_missing_price_rejected(api):
    """PRD §3.8: "a `LIMIT` order requires `limit_price` to be present and greater
    than zero"

    Design: Corner/validations/limit_order_missing_price_rejected
    """
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="lo@x.com", full_name="LO")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 50000)
    version = get_account_version(acc_id, make_trader_headers(acc_id))
    resp = api.create_order(
        _order_payload(acc_id, side="BUY", order_type="LIMIT", quantity=0.1,
                       time_in_force="GTC", expected_account_version=version),
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER.value)


def test_market_buy_empty_book_no_liquidity(api):
    """PRD §3.8: "A `MARKET` `BUY` requires a non-empty resting `SELL` book or it is
    rejected with `ERR_NO_LIQUIDITY`."

    Design: Corner/validations/market_buy_empty_book_no_liquidity
    """
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="nl@x.com", full_name="NL")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 50000)
    version = get_account_version(acc_id, make_trader_headers(acc_id))
    resp = api.create_order(
        _order_payload(acc_id, side="BUY", order_type="MARKET", quantity=0.1,
                       time_in_force="IOC", expected_account_version=version),
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_NO_LIQUIDITY.value)


def test_insufficient_available_for_order_rejected(api):
    """PRD §3.8: "Finally, there must be enough spendable balance to cover the
    computed reserve, or the placement is rejected with `ERR_INSUFFICIENT_AVAILABLE`."

    Design: Corner/validations/insufficient_available_for_order_rejected
    """
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="ia@x.com", full_name="IA")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 100)  # reserve 40120 > 100
    version = get_account_version(acc_id, make_trader_headers(acc_id))
    resp = api.create_order(
        _order_payload(acc_id, side="BUY", order_type="LIMIT", quantity=1.0,
                       limit_price=40000, time_in_force="GTC",
                       expected_account_version=version),
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE.value)


def test_existence_check_before_state_on_unknown_order(api):
    """PRD §2.9: "the system validates each referenced resource left to right and
    rejects the first identifier that does not resolve to an existing resource with
    `ERR_NOT_FOUND`."
    PRD §2.10: "then the existence of every referenced resource, then whether the
    target resource is in a state from which the requested transition is defined"

    Design: Corner/validations/existence_check_before_state_on_unknown_order
    """
    acc = create_account_at_tier("TIER_1", email="ex@x.com", full_name="EX")
    resp = api.cancel_order("11111111-1111-4111-8111-111111111111",
                            make_trader_headers(acc["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner / cross_cutting_complexity_layers — OCC and derived reconciliation
# ===========================================================================
def test_occ_add_address_correct_version_succeeds_and_increments(api):
    """PRD §3.5: "the optimistic-concurrency token `expected_account_version`. A new
    address is created with a `status` of `PENDING_HOLD` and an `activates_at` set to
    its `created_at` plus twenty-four hours; the add increments the account's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_then_increments
    """
    create_btc_asset()
    acc = create_account(email="oc1@x.com", full_name="OC1")
    acc_id = acc["id"]
    assert acc["version"] == 1
    trader = make_trader_headers(acc_id)
    resp = api.create_withdrawal_address(
        {"account_id": acc_id, "asset": "BTC", "chain_address": "0xOC",
         "label": "out", "expected_account_version": 1}, trader)
    validate_success(resp, 201)
    after = validate_success(api.get_account(acc_id, trader))
    assert after["version"] == 2


def test_occ_stale_version_on_order_place_conflict(api):
    """PRD §2.8: "If another writer has advanced the account's version since the
    client last read it — for instance, a prior order placement or a fill cascade
    that already debited or reserved the account's balances — the placement is
    rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412"
    PRD §3.8: "Placing an order increments the placing account's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_order_place_conflict
    """
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="oc2@x.com", full_name="OC2")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 50000)
    trader = make_trader_headers(acc_id)
    stale_version = get_account_version(acc_id, trader)
    # first placement consumes that version and bumps it
    validate_success(api.create_order(
        _order_payload(acc_id, side="BUY", order_type="LIMIT", quantity=0.1,
                       limit_price=40000, time_in_force="GTC",
                       expected_account_version=stale_version), trader), 201)
    # second placement reuses the now-stale version
    resp = api.create_order(
        _order_payload(acc_id, side="BUY", order_type="LIMIT", quantity=0.1,
                       limit_price=40000, time_in_force="GTC",
                       expected_account_version=stale_version), trader)
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)


def test_derived_available_reconciles_after_deposit_and_order(api):
    """PRD §2.6: "The `total_amount` is the sum of `available_amount`,
    `reserved_amount`, and `held_amount`, and `available_amount` always equals
    `total_amount` minus `reserved_amount` minus `held_amount`."

    Design: Corner/cross_cutting_complexity_layers/derived_available_reconciles_after_deposit_and_order
    """
    create_usd_btc_with_fees()
    acc = create_account_at_tier("TIER_1", email="df@x.com", full_name="DF")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 50000)
    place_order(acc_id, "BTC", "USD", "BUY", "LIMIT", 1.0,
                limit_price=40000, time_in_force="GTC")
    trader = make_trader_headers(acc_id)
    bals, _ = validate_paginated(api.list_balances(trader, params={"account_id": acc_id, "asset": "USD"}))
    usd = find_balance(bals, "USD")
    assert usd["total_amount"] == pytest.approx(50000, abs=0.01)
    assert usd["available_amount"] == pytest.approx(9880.00, abs=0.01)
    assert usd["reserved_amount"] == pytest.approx(40120.00, abs=0.01)
    assert usd["held_amount"] == pytest.approx(0.0, abs=0.01)
    assert_balance_partition_reconciles(usd)


# ===========================================================================
# Corner / consistency_model — immediate consistency of a crossing MARKET BUY
# ===========================================================================
def test_immediate_consistency_fill_visible_same_response(api):
    """PRD §3.8: "an order filled completely in one round moves `OPEN → FILLED` and
    has its `reserved_remaining` set to zero"
    PRD §3.8: "Both orders have their `filled_quantity` incremented, their
    `avg_fill_price` recomputed as the notional-weighted average across their fills
    (null until the first fill)"

    Design: Corner/consistency_model/immediate_consistency_fill_visible_same_response
    """
    set_clock("2026-06-15T00:00:00Z")
    create_usd_btc_with_fees()
    seller = create_account_at_tier("TIER_1", email="im_s@x.com", full_name="ImS")
    create_and_credit_deposit(seller["id"], "BTC", 1.0, 35000, required_confirmations=1)
    rest_sell_limit(seller["id"], "BTC", "USD", 1.0, 40000)
    buyer = setup_buyer_with_usd(usd=50000, email="im_b@x.com", full_name="ImB")
    order = place_order(buyer["id"], "BTC", "USD", "BUY", "MARKET", 1.0,
                        time_in_force="IOC")
    assert order["lifecycle_status"] == "FILLED"
    assert order["filled_quantity"] == pytest.approx(1.0, abs=1e-9)
    assert order["avg_fill_price"] == pytest.approx(40000, abs=0.01)
