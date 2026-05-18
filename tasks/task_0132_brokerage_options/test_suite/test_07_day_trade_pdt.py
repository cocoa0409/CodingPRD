"""DayTrade pairing + Pattern Day Trader rule + PDT-freeze cascade.

Coverage targets (PRD §3.4):
- Day-trade pairing on every transition to FILLED — same account,
  symbol, trade_date, opposite side, FIFO by filled_at asc / id asc.
- Both opener and closer flip opened_for_day_trade -> true; a new
  DayTrade row is inserted.
- PDT trip: count >= 4 AND equity_value_cents < 2_500_000 ->
  pdt_flag := true, pdt_flagged_at := now(), posture := PDT_FROZEN.
- Cascade: non-terminal Orders -> CANCELLED; non-terminal
  OptionsApprovals -> REJECTED.
- Pre-flag block: ERR_PDT_EQUITY_BELOW_MINIMUM while flagged and
  equity still below floor.
- PDT-reset action restores posture when equity >= floor.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    PDT_EQUITY_FLOOR_CENTS,
    TEST_USERS,
    accumulate_n_day_trades,
    execute_one_day_trade,
    make_customer_headers,
    pdt_reset_payload,
    setup_account_below_pdt_floor_with_n_day_trades,
    setup_for_pdt_three_hop_cascade,
    setup_funded_account,
    trigger_fourth_day_trade,
    validate_error,
    validate_success,
)


# ===========================================================================
# Day-trade pairing — PRD §3.4
# ===========================================================================
class TestDayTradePairing:
    """PRD §3.4: 'Every time an Order transitions to FILLED, the system
    runs day-trade pairing ... When a pair is found, both the opener
    and the closer have their opened_for_day_trade flag set to true,
    and a new DayTrade row is inserted'."""

    def test_round_trip_creates_day_trade_pairing(self, api):
        """PRD §3.4: "When a pair is found, both the opener and the
        closer have their opened_for_day_trade flag set to true, and a
        new DayTrade row is inserted carrying account_id, symbol,
        opening_order_id (the opener's id), closing_order_id (the new
        fill's id), and trade_date."

        Claim: a MARKET BUY followed by MARKET SELL on the same
        account/symbol/day pairs into a DayTrade, both orders carry
        opened_for_day_trade==true.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        buy, sell = execute_one_day_trade(
            customer, account,
            symbol="AAPL", market_price_cents=100,
        )
        # Re-read both orders.
        buy_after = validate_success(api.get_order(
            buy["id"], make_customer_headers(customer["id"]),
        ))
        sell_after = validate_success(api.get_order(
            sell["id"], make_customer_headers(customer["id"]),
        ))
        assert buy_after["status"] == "FILLED"
        assert sell_after["status"] == "FILLED"
        assert buy_after["opened_for_day_trade"] is True, (
            "opener BUY must be flagged opened_for_day_trade after pair"
        )
        assert sell_after["opened_for_day_trade"] is True, (
            "closer SELL must be flagged opened_for_day_trade after pair"
        )


# ===========================================================================
# PDT count boundary — PRD §3.4
# ===========================================================================
class TestPdtCountBoundary:
    """PRD §3.4: 'If the count is at least 4 and Account.equity_value_cents
    is strictly less than 2,500,000 ... the Pattern Day Trader threshold
    has tripped'."""

    def test_three_day_trades_do_not_trip_pdt(self, api):
        """PRD §3.4: "If the count is at least 4 and
        Account.equity_value_cents is strictly less than 2,500,000 ...
        the Pattern Day Trader threshold has tripped".

        Claim: 3 day trades with equity < $25k -> pdt_flag stays
        false. Boundary test: count == 3 is one BELOW the >=4 trip.
        """
        customer, account, pairs = (
            setup_account_below_pdt_floor_with_n_day_trades(
                n_prior_day_trades=3,
                cash_amount_cents=PDT_EQUITY_FLOOR_CENTS - 100,
            )
        )
        # Account must still be OPEN, no PDT flag.
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert fresh["pdt_flag"] is False
        assert fresh["trading_posture"] == "OPEN"

    def test_fourth_day_trade_trips_pdt(self, api):
        """PRD §3.4: "If the count is at least 4 and
        Account.equity_value_cents is strictly less than 2,500,000 ...
        the Pattern Day Trader threshold has tripped:
        Account.pdt_flag is set to true, Account.pdt_flagged_at is set
        to the current now(), and Account.trading_posture advances
        from OPEN to PDT_FROZEN."

        Claim: the 4th day trade (count == 4) with equity < $25k
        trips PDT — pdt_flag=true, posture=PDT_FROZEN,
        pdt_flagged_at populated.
        """
        customer, account, pairs = (
            setup_account_below_pdt_floor_with_n_day_trades(
                n_prior_day_trades=3,
                cash_amount_cents=PDT_EQUITY_FLOOR_CENTS - 100,
            )
        )
        # Insert the 4th day trade.
        trigger_fourth_day_trade(
            customer, account,
            symbol="ZZZZ", market_price_cents=100,
        )
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert fresh["pdt_flag"] is True
        assert fresh["trading_posture"] == "PDT_FROZEN"
        assert fresh["pdt_flagged_at"] is not None


# ===========================================================================
# Equity floor strictness — PRD §3.4
# ===========================================================================
class TestPdtEquityFloor:
    """PRD §3.4: 'Account.equity_value_cents is strictly less than
    2,500,000'."""

    def test_equity_exactly_at_floor_does_not_trip(self, api):
        """PRD §3.4: "If the count is at least 4 and
        Account.equity_value_cents is strictly less than 2,500,000 ...
        the Pattern Day Trader threshold has tripped".

        Claim: equity == 2_500_000 exactly (boundary) does NOT trip
        PDT; trading_posture stays OPEN even after the 4th day trade.
        Boundary test: 'strictly less than' means equality is OUT.
        """
        # 4 trades but equity at the floor exactly.
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T",
            cash_amount_cents=PDT_EQUITY_FLOOR_CENTS,
        )
        accumulate_n_day_trades(
            customer, account, n=4, market_price_cents=100,
        )
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        # Count is >= 4 but equity is at the floor (not strictly less
        # than), so PRD §3.4 says NO trip.
        assert fresh["pdt_flag"] is False
        assert fresh["trading_posture"] == "OPEN"


# ===========================================================================
# PDT cascade — PRD §3.4
# ===========================================================================
class TestPdtCascade:
    """PRD §3.4: 'That posture change drives a depth-3 cascade: every
    Order for this account whose status is in the non-terminal set
    (ACCEPTED, WORKING) is moved to CANCELLED; every OptionsApproval
    for this account whose status is in the non-terminal set
    (SUBMITTED, UNDER_REVIEW, REVISION_REQUESTED) is moved to terminal
    REJECTED with a reason of PDT_FREEZE.'"""

    def test_pdt_trip_cancels_working_orders_and_rejects_approvals(
        self, api,
    ):
        """PRD §3.4: "every Order for this account whose status is in
        the non-terminal set (ACCEPTED, WORKING) is moved to
        CANCELLED; every OptionsApproval for this account whose status
        is in the non-terminal set (SUBMITTED, UNDER_REVIEW,
        REVISION_REQUESTED) is moved to terminal REJECTED with a
        reason of PDT_FREEZE."

        Claim: tripping PDT cancels every non-terminal Order and
        rejects every non-terminal OptionsApproval on the same account.
        """
        customer, account, working_order, approval = (
            setup_for_pdt_three_hop_cascade(
                cash_amount_cents=PDT_EQUITY_FLOOR_CENTS - 100,
            )
        )
        assert working_order["status"] == "WORKING"
        assert approval["status"] == "UNDER_REVIEW"
        # 4th day trade trips PDT.
        trigger_fourth_day_trade(
            customer, account,
            symbol="ZZZZ", market_price_cents=100,
        )
        # Verify cascade.
        ord_after = validate_success(api.get_order(
            working_order["id"], make_customer_headers(customer["id"]),
        ))
        assert ord_after["status"] == "CANCELLED"

        oa_after = validate_success(api.get_options_approval(
            approval["id"], TEST_USERS["compliance_headers"],
        ))
        assert oa_after["status"] == "REJECTED"


# ===========================================================================
# PDT-reset clears the freeze — PRD §3.4
# ===========================================================================
class TestPdtReset:
    """PRD §3.4: 'The PDT freeze is cleared by depositing fresh cash.
    The customer calls the PDT-reset action ... if the resulting
    Account.equity_value_cents is greater than or equal to 2,500,000
    and the posture is still PDT_FROZEN — flips
    Account.trading_posture back to OPEN and sets Account.pdt_flag to
    false.'"""

    def test_pdt_reset_with_sufficient_top_up_clears_freeze(self, api):
        """PRD §3.4: "if the resulting Account.equity_value_cents is
        greater than or equal to 2,500,000 and the posture is still
        PDT_FROZEN — flips Account.trading_posture back to OPEN and
        sets Account.pdt_flag to false."

        Claim: a PDT-reset that pushes equity to >= $25k flips posture
        OPEN and clears pdt_flag.
        """
        customer, account, _ = (
            setup_account_below_pdt_floor_with_n_day_trades(
                n_prior_day_trades=3,
                cash_amount_cents=PDT_EQUITY_FLOOR_CENTS - 100,
            )
        )
        trigger_fourth_day_trade(
            customer, account,
            symbol="ZZZZ", market_price_cents=100,
        )
        frozen = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert frozen["trading_posture"] == "PDT_FROZEN"

        # Top up by enough to reach $25k.
        top_up = (
            PDT_EQUITY_FLOOR_CENTS - frozen["equity_value_cents"] + 100
        )
        resp = api.pdt_reset(
            account["id"], pdt_reset_payload(equity_top_up_cents=top_up),
            make_customer_headers(customer["id"]),
        )
        after = validate_success(resp)
        assert after["trading_posture"] == "OPEN"
        assert after["pdt_flag"] is False
        assert after["equity_value_cents"] >= PDT_EQUITY_FLOOR_CENTS

    def test_pdt_reset_with_insufficient_top_up_keeps_freeze(self, api):
        """PRD §3.4: "If the topped-up equity still falls below
        2,500,000, the posture stays at PDT_FROZEN and pdt_flag
        remains true."

        Claim: a PDT-reset where the resulting equity is still below
        the floor leaves posture=PDT_FROZEN and pdt_flag=true.
        """
        customer, account, _ = (
            setup_account_below_pdt_floor_with_n_day_trades(
                n_prior_day_trades=3,
                cash_amount_cents=PDT_EQUITY_FLOOR_CENTS - 100_000,
            )
        )
        trigger_fourth_day_trade(
            customer, account,
            symbol="ZZZZ", market_price_cents=100,
        )
        # Top up by only 1 cent — still below floor.
        resp = api.pdt_reset(
            account["id"], pdt_reset_payload(equity_top_up_cents=1),
            make_customer_headers(customer["id"]),
        )
        after = validate_success(resp)
        assert after["trading_posture"] == "PDT_FROZEN"
        assert after["pdt_flag"] is True
