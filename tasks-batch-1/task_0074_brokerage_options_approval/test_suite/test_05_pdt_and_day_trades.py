"""Pattern-Day-Trader threshold, trailing-window membership, and day-trade tests."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    open_and_activate_account, accept_order, draft_order,
    fill_same_day_round_trip, setup_three_same_day_day_trades,
    seed_day_trades_and_flag, get_account,
    CO_SUBMITTER, HOLDER,
)


def test_pdt_fourth_day_trade_flips_at_threshold(api):
    """PRD §3.9: "The prospective count is the number of existing day-trade rows
    for the account whose `trade_date` equals this order's `trade_date`, plus
    one for this order. If the account is not yet `pdt_flagged`, its
    `equity_cents` is below the $25,000.00 minimum, and the prospective count
    reaches the threshold of 4 or more, the acceptance is blocked with
    `ERR_PDT_RULE_BLOCK`."

    Three existing same-day DayTrade rows + a prospective 4th same-day closing
    leg under $25k equity -> ERR_PDT_RULE_BLOCK.

    Design: Difficulty/boundary_precision_check/pdt_fourth_day_trade_flips_at_threshold
    """
    acct_id, _ = setup_three_same_day_day_trades(cash_balance_cents=100_000,
                                                 trade_date="2026-06-01")
    d4 = draft_order(acct_id, symbol="DT4", instrument_type="EQUITY", side="SELL",
                     order_type="LIMIT", quantity=1, limit_price_cents=100,
                     opened_position_same_day=True, trade_date="2026-06-01")
    resp = api.accept_order(d4["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_PDT_RULE_BLOCK.value)


def test_pdt_third_day_trade_allowed_below_threshold(api):
    """PRD §3.9: "At exactly three day trades the account is not flagged; the
    fourth day trade flips it."

    With only two existing same-day DayTrade rows, the prospective 3rd
    same-day closing leg is below the threshold of 4 and is accepted.

    Design: Difficulty/boundary_precision_check/pdt_fourth_day_trade_flips_at_threshold
    """
    acct = open_and_activate_account(cash_balance_cents=100_000)
    fill_same_day_round_trip(acct["id"], "DT1", "2026-06-01")
    fill_same_day_round_trip(acct["id"], "DT2", "2026-06-01")
    # prospective count = 2 existing + 1 = 3 < 4 → allowed
    d3 = draft_order(acct["id"], symbol="DT3", instrument_type="EQUITY", side="SELL",
                     order_type="LIMIT", quantity=1, limit_price_cents=100,
                     opened_position_same_day=True, trade_date="2026-06-01")
    resp = api.accept_order(d3["id"], HOLDER)
    data = validate_success(resp)
    assert data["status"] == "ACCEPTED"


def test_pdt_trailing_window_inclusive_membership(api):
    """PRD §3.9: "set the window start to that anchor date minus 5 calendar
    days, and count the day-trade rows whose `trade_date` falls within that
    window from the window start through the anchor date inclusive."

    Three DayTrade rows on 2026-06-01 plus a prospective 4th closing leg on
    2026-06-01 all fall inside the window and trip ERR_PDT_RULE_BLOCK.

    Design: Difficulty/resource_temporal_overlap/pdt_trailing_window_inclusive_membership
    """
    acct_id, _ = setup_three_same_day_day_trades(cash_balance_cents=100_000,
                                                 trade_date="2026-06-01")
    w4 = draft_order(acct_id, symbol="WD4", instrument_type="EQUITY", side="SELL",
                     order_type="LIMIT", quantity=1, limit_price_cents=100,
                     opened_position_same_day=True, trade_date="2026-06-01")
    resp = api.accept_order(w4["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_PDT_RULE_BLOCK.value)


def test_pdt_window_excludes_out_of_range_day_trade(api):
    """PRD §3.9: "take the anchor date as the most recent `trade_date` among the
    account's day-trade rows (if the account has no day-trade rows the count is
    0), set the window start to that anchor date minus 5 calendar days, and
    count the day-trade rows whose `trade_date` falls within that window from
    the window start through the anchor date inclusive."

    With the anchor at 2026-06-01, an earlier DayTrade dated 2026-05-01 falls
    OUTSIDE the trailing 5-day window, so day_trade_count == 1 and the account
    stays ACTIVE.

    Design: Difficulty/resource_temporal_overlap/pdt_window_excludes_out_of_range_day_trade
    """
    acct = open_and_activate_account(cash_balance_cents=3_000_000)  # equity >= 25k
    fill_same_day_round_trip(acct["id"], "OLD", "2026-05-01")
    new_filled = fill_same_day_round_trip(acct["id"], "NEW", "2026-06-01")
    assert new_filled["status"] == "FILLED"

    after = validate_success(api.get_account(acct["id"], CO_SUBMITTER))
    assert after["day_trade_count"] == 1, after["day_trade_count"]
    assert after["status"] == "ACTIVE"


def test_restore_restricted_pdt_account_below_equity_min_returns_equity_call(api):
    """PRD §3.1: "if the account is `pdt_flagged`, its `equity_cents` must be at
    least the pattern-day-trader minimum equity of $25,000.00 (2,500,000
    cents); if a flagged account is below that floor, the restore is rejected
    with `ERR_PDT_EQUITY_CALL`."

    An account flagged + RESTRICTED via 4 seeded day trades under $25k equity
    cannot be restored to ACTIVE.

    Design: Corner/state_machines/restore_restricted_pdt_account_below_equity_min_returns_equity_call
    """
    acct = open_and_activate_account(cash_balance_cents=100_000)
    flagged = seed_day_trades_and_flag(acct["id"], "2026-06-01", 4)
    assert flagged["status"] == "RESTRICTED"
    assert flagged["pdt_flagged"] is True

    resp = api.activate_account(acct["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_PDT_EQUITY_CALL.value)


def test_daytrade_is_immutable_no_version_field(api):
    """PRD §2.4: "A day-trade row is an append-only event record and carries
    only `id` and `created_at`; it has neither an `updated_at` nor a `version`
    field, because it is never modified after it is written." PRD §3.5: "creates
    a `DayTrade` row capturing the account, this order's id as the
    `closing_order_id`, the order's `symbol`, and its `trade_date`".

    One same-day closing order FILLED produces exactly one DayTrade row whose
    closing_order_id is the order id.

    Design: Corner/entities/daytrade_is_immutable_no_version_field
    """
    acct = open_and_activate_account(cash_balance_cents=3_000_000)
    filled = fill_same_day_round_trip(acct["id"], "DT", "2026-06-01")

    rows, meta = validate_paginated(api.list_day_trades(CO_SUBMITTER, {"account_id": acct["id"]}))
    assert meta["total_count"] == 1, meta["total_count"]
    assert rows[0]["closing_order_id"] == filled["id"]
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]


def test_pdt_window_includes_anchor_minus_five_days(api):
    """PRD §3.9: "set the window start to that anchor date minus 5 calendar
    days, and count the day-trade rows whose `trade_date` falls within that
    window from the window start through the anchor date inclusive."

    Two same-day round trips on 2026-05-27 and one on 2026-06-01: the anchor is
    2026-06-01, window start 2026-05-27 (inclusive); a prospective 4th leg on
    2026-06-01 reaches count 4 (the 3 in-window rows plus this one) under $25k
    equity -> ERR_PDT_RULE_BLOCK. Wait: prospective count keys on the order's
    trade_date only, so only the two 2026-06-01-equal rows plus this one count.

    Design: Difficulty/resource_temporal_overlap/pdt_trailing_window_inclusive_membership
    """
    # Three FILLED same-day round trips all on 2026-06-01 (within the window),
    # then a 4th same-day closing leg on 2026-06-01 trips the prospective block.
    acct = open_and_activate_account(cash_balance_cents=100_000)
    for sym in ("AA", "BB", "CC"):
        fill_same_day_round_trip(acct["id"], sym, "2026-06-01")
    d4 = draft_order(acct["id"], symbol="DD", instrument_type="EQUITY", side="SELL",
                     order_type="LIMIT", quantity=1, limit_price_cents=100,
                     opened_position_same_day=True, trade_date="2026-06-01")
    resp = api.accept_order(d4["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_PDT_RULE_BLOCK.value)


def test_pdt_far_dated_round_trip_does_not_flag(api):
    """PRD §3.9: "take the anchor date as the most recent `trade_date` among the
    account's day-trade rows ... count the day-trade rows whose `trade_date`
    falls within that window from the window start through the anchor date
    inclusive."

    A single same-day round trip dated 2026-05-01 (the only DayTrade) yields
    day_trade_count == 1 and the account remains ACTIVE — far from the threshold.

    Design: Difficulty/resource_temporal_overlap/pdt_window_excludes_out_of_range_day_trade
    """
    acct = open_and_activate_account(cash_balance_cents=3_000_000)
    fill_same_day_round_trip(acct["id"], "SOLO", "2026-05-01")
    after = validate_success(api.get_account(acct["id"], CO_SUBMITTER))
    assert after["day_trade_count"] == 1
    assert after["status"] == "ACTIVE"
