"""Order notional computation and per-position maintenance margin tests."""
from test_helpers import (
    validate_success,
    ApiErrorId,
    open_and_activate_account, grant_options_level, open_position,
    draft_order, get_account,
    CO_SUBMITTER, HOLDER,
)


def test_maintenance_margin_round_per_position_then_sum(api):
    """PRD §2.7: "Maintenance margin is computed per position and floored per
    position before the per-position results are summed, never summed first and
    floored once." PRD §2.9: "For an `EQUITY` position the requirement is the
    absolute value of its `market_value_cents` multiplied by the equity
    maintenance rate of 25 percent, floored to whole cents."

    Two OPEN EQUITY positions with market_value 6 each: floor(6*0.25)=1 each,
    summed to 2 (NOT floor((6+6)*0.25)=3).

    Design: Difficulty/combinatorial_formula/maintenance_margin_round_per_position_then_sum
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    open_position(acct["id"], symbol="AAA", instrument_type="EQUITY",
                  quantity=1, market_value_cents=6)
    open_position(acct["id"], symbol="BBB", instrument_type="EQUITY",
                  quantity=1, market_value_cents=6)
    data = validate_success(api.get_account(acct["id"], CO_SUBMITTER))
    assert data["maintenance_margin_cents"] == 2, data["maintenance_margin_cents"]


def test_option_position_maintenance_full_rate(api):
    """PRD §2.9: "For an `OPTION` position the requirement is the absolute value
    of its `market_value_cents` multiplied by the option maintenance rate of
    100 percent, floored to whole cents."

    One OPEN OPTION position market_value 700000 contributes floor(700000*1.00)
    = 700000.

    Design: Corner/calculations/option_position_maintenance_full_rate
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    open_position(acct["id"], symbol="OPT", instrument_type="OPTION",
                  quantity=1, market_value_cents=700_000)
    data = validate_success(api.get_account(acct["id"], CO_SUBMITTER))
    assert data["maintenance_margin_cents"] == 700_000


def test_empty_positions_yield_zero_maintenance_margin(api):
    """PRD §2.9: "Closed positions are excluded entirely." PRD §3.5: "closing it
    recomputes the account's maintenance margin excluding that position, then
    recomputes equity and buying power."

    An account whose only OPEN position is then closed has
    maintenance_margin_cents == 0.

    Design: Difficulty/boundary_precision_check/empty_positions_yield_zero_maintenance_margin
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    pos = open_position(acct["id"], symbol="ACME", instrument_type="EQUITY",
                        quantity=10, market_value_cents=1_000_000)
    assert get_account(acct["id"])["maintenance_margin_cents"] == 250_000

    resp = api.close_position(pos["id"], HOLDER)
    closed = validate_success(resp)
    assert closed["status"] == "CLOSED"
    assert validate_success(api.get_account(acct["id"], CO_SUBMITTER))["maintenance_margin_cents"] == 0


def test_account_with_no_positions_has_zero_maintenance_margin(api):
    """PRD §2.9: "`maintenance_margin_cents` is the sum, over the account's
    `OPEN` positions taken in `created_at` ascending order, of each position's
    maintenance requirement."

    An account with no positions at all has maintenance_margin_cents == 0.

    Design: Difficulty/boundary_precision_check/empty_positions_yield_zero_maintenance_margin
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    data = validate_success(api.get_account(acct["id"], CO_SUBMITTER))
    assert data["maintenance_margin_cents"] == 0


def test_take_profit_notional_worst_case_leg_with_option_multiplier(api):
    """PRD §3.8: "for `TAKE_PROFIT` the larger of `limit_price_cents` and
    `stop_price_cents`, taking the worst case of the two legs. If the order's
    `instrument_type` is `OPTION`, this base is multiplied by the option
    contract multiplier of 100 to reflect contract size".

    TAKE_PROFIT OPTION qty 2, limit 30000, stop 40000 -> 2*max(30000,40000)*100
    = 2*40000*100 = 8000000.

    Design: Difficulty/combinatorial_formula/take_profit_notional_worst_case_leg_with_option_multiplier
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    grant_options_level(acct["id"], 1)
    ord_ = draft_order(acct["id"], symbol="OPT", instrument_type="OPTION", side="BUY",
                       order_type="TAKE_PROFIT", quantity=2,
                       limit_price_cents=30_000, stop_price_cents=40_000)

    resp = api.accept_order(ord_["id"], HOLDER)
    data = validate_success(resp)
    assert data["status"] == "ACCEPTED"
    assert data["notional_cents"] == 8_000_000, data["notional_cents"]


def test_stop_order_notional_uses_stop_price(api):
    """PRD §3.8: "for `STOP` the `stop_price_cents`". PRD §3.8: "The base figure
    is the order `quantity` multiplied by a per-unit price chosen by
    `order_type`".

    STOP EQUITY order qty 5 stop_price 40000 -> notional = 5*40000 = 200000
    (limit_price ignored).

    Design: Corner/calculations/stop_order_notional_uses_stop_price
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    ord_ = draft_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                       order_type="STOP", quantity=5, stop_price_cents=40_000)
    resp = api.accept_order(ord_["id"], HOLDER)
    data = validate_success(resp)
    assert data["notional_cents"] == 200_000, data["notional_cents"]


def test_order_notional_sell_to_close_vs_open_exposure(api):
    """PRD §3.8: "a `SELL` order against an existing `OPEN` long position in the
    same symbol reserves nothing — when `side` is `SELL` and the account holds
    an `OPEN` `Position` in the same symbol with positive quantity,
    `notional_cents` is 0, because closing a long frees rather than consumes
    buying power." PRD §3.8: "for `LIMIT` the `limit_price_cents`".

    SELL LIMIT qty 10 limit 50000 over an OPEN long position reserves 0; the
    same SELL with no matching long reserves 10*50000 = 500000.

    Design: Difficulty/dual_variant_calc/order_notional_sell_to_close_vs_open_exposure
    """
    acct_a = open_and_activate_account(holder_id="h_a", cash_balance_cents=1_000_000)
    open_position(acct_a["id"], symbol="ACME", instrument_type="EQUITY",
                  quantity=10, market_value_cents=500_000)
    ord_close = draft_order(acct_a["id"], holder_id="h_a", symbol="ACME",
                            instrument_type="EQUITY", side="SELL", order_type="LIMIT",
                            quantity=10, limit_price_cents=50_000)

    acct_b = open_and_activate_account(holder_id="h_b", cash_balance_cents=1_000_000)
    ord_open = draft_order(acct_b["id"], holder_id="h_b", symbol="ACME",
                           instrument_type="EQUITY", side="SELL", order_type="LIMIT",
                           quantity=10, limit_price_cents=50_000)

    from test_helpers import make_account_holder_headers
    close_data = validate_success(api.accept_order(ord_close["id"], make_account_holder_headers("h_a")))
    open_data = validate_success(api.accept_order(ord_open["id"], make_account_holder_headers("h_b")))

    assert close_data["notional_cents"] == 0, close_data["notional_cents"]
    assert open_data["notional_cents"] == 500_000, open_data["notional_cents"]
    assert close_data["notional_cents"] != open_data["notional_cents"]


def test_maintenance_margin_sum_two_equity_positions(api):
    """PRD §2.9: "`maintenance_margin_cents` is the sum, over the account's
    `OPEN` positions taken in `created_at` ascending order, of each position's
    maintenance requirement. For an `EQUITY` position the requirement is the
    absolute value of its `market_value_cents` multiplied by the equity
    maintenance rate of 25 percent, floored to whole cents."

    Two OPEN EQUITY positions market_value 1000000 and 2000000:
    floor(1000000*0.25)=250000 + floor(2000000*0.25)=500000 = 750000.

    Design: Difficulty/combinatorial_formula/maintenance_margin_round_per_position_then_sum
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    open_position(acct["id"], symbol="AAA", instrument_type="EQUITY",
                  quantity=1, market_value_cents=1_000_000)
    open_position(acct["id"], symbol="BBB", instrument_type="EQUITY",
                  quantity=1, market_value_cents=2_000_000)
    data = validate_success(api.get_account(acct["id"], CO_SUBMITTER))
    assert data["maintenance_margin_cents"] == 750_000


def test_take_profit_equity_notional_uses_worst_case_leg(api):
    """PRD §3.8: "for `TAKE_PROFIT` the larger of `limit_price_cents` and
    `stop_price_cents`, taking the worst case of the two legs."

    TAKE_PROFIT EQUITY qty 3, limit 30000, stop 40000 -> 3*max(30000,40000)*1
    = 120000 (no option multiplier).

    Design: Difficulty/combinatorial_formula/take_profit_notional_worst_case_leg_with_option_multiplier
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    ord_ = draft_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                       order_type="TAKE_PROFIT", quantity=3,
                       limit_price_cents=30_000, stop_price_cents=40_000)
    data = validate_success(api.accept_order(ord_["id"], HOLDER))
    assert data["notional_cents"] == 120_000, data["notional_cents"]


def test_sell_with_no_matching_long_reserves_full_notional(api):
    """PRD §3.8: "for `LIMIT` the `limit_price_cents`". PRD §3.8: "As a special
    case, a `SELL` order against an existing `OPEN` long position in the same
    symbol reserves nothing".

    A SELL LIMIT qty 10 limit 50000 with NO matching long position reserves the
    full 10*50000 = 500000.

    Design: Difficulty/dual_variant_calc/order_notional_sell_to_close_vs_open_exposure
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    ord_ = draft_order(acct["id"], symbol="ZZZ", instrument_type="EQUITY", side="SELL",
                       order_type="LIMIT", quantity=10, limit_price_cents=50_000)
    data = validate_success(api.accept_order(ord_["id"], HOLDER))
    assert data["notional_cents"] == 500_000, data["notional_cents"]
