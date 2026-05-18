"""Trade lifecycle: create, execute, settle, cancel.

Coverage targets (PRD §3.4, §2.7):
- Create PENDING, transitions, terminal states.
- Cash-balance precondition for BUY.
- is_investable precondition for BUY.
- Insufficient lot/position shares for SELL (FIFO / SPECIFIC_LOT).
- Cancel preconditions (PENDING, not rebalance child).
- Account-frozen precondition.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    buy_and_settle,
    create_security,
    create_trade,
    create_trade_payload,
    execute_trade,
    freeze_account,
    re_get_trade,
    settle_trade,
    setup_active_client_with_account,
    setup_frozen_account_with_pending_buy,
    setup_pending_buy_trade,
    validate_error,
    validate_success,
)


# ===========================================================================
# Trade create — PRD §3.4
# ===========================================================================
class TestTradeCreate:

    def test_create_buy_trade_pending(self, api):
        """PRD §3.4: "A Trade is created in PENDING by an Advisor or
        a ClientUser, naming the target security_id, the side (BUY
        or SELL), the requested_shares (a positive number, fractional
        to four decimal places)".

        Claim: POST /accounts/{id}/trades with side=BUY returns
        status=PENDING.
        """
        _, account = setup_active_client_with_account()
        security = create_security()
        payload = create_trade_payload(
            security_id=security["id"], side="BUY",
            requested_shares=2,
        )
        resp = api.create_trade(
            account["id"], payload, TEST_USERS["advisor_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING"
        assert data["side"] == "BUY"


# ===========================================================================
# Execute — BUY preconditions — PRD §3.4
# ===========================================================================
class TestBuyExecutePreconditions:

    def test_buy_not_investable_rejected(self, api):
        """PRD §3.4: "For a BUY, the target Security must be marked
        is_investable (otherwise ERR_SECURITY_NOT_INVESTABLE)".

        Claim: executing a BUY against a Security where
        is_investable=false -> ERR_SECURITY_NOT_INVESTABLE.
        """
        _, account = setup_active_client_with_account()
        security = create_security(is_investable=False)
        trade = create_trade(
            account, security, side="BUY", requested_shares=5,
        )
        resp = api.execute_trade(
            account["id"], trade["id"],
            TEST_USERS["advisor_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_SECURITY_NOT_INVESTABLE.value,
        )

    def test_buy_insufficient_cash_rejected(self, api):
        """PRD §3.4: "For a BUY ... the account's cash_balance_cents
        must be at least the requested-shares times the execution
        price rounded half-up to whole cents (otherwise
        ERR_INSUFFICIENT_CASH)".

        Claim: BUY whose required cash exceeds balance ->
        ERR_INSUFFICIENT_CASH.
        """
        # Fund a tiny amount.
        _, account = setup_active_client_with_account(fund_cents=100)
        security = create_security(last_price_cents=10_000)
        trade = create_trade(
            account, security, side="BUY", requested_shares=5,
        )
        resp = api.execute_trade(
            account["id"], trade["id"],
            TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CASH.value)

    def test_execute_on_non_pending_trade_rejected(self, api):
        """PRD §3.4: "trying to execute a trade that has already
        moved to EXECUTED, SETTLED, CANCELLED, or REJECTED is rejected
        with ERR_INVALID_STATE."

        Claim: executing twice -> second execute -> ERR_INVALID_STATE.
        """
        scenario = setup_pending_buy_trade()
        execute_trade(scenario["account"], scenario["trade"])
        resp = api.execute_trade(
            scenario["account"]["id"], scenario["trade"]["id"],
            TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Execute — SELL preconditions — PRD §3.4
# ===========================================================================
class TestSellExecutePreconditions:

    def test_sell_insufficient_position_shares_fifo(self, api):
        """PRD §3.4: "when the method is FIFO, the sum of
        shares_remaining across all OPEN and PARTIALLY_CLOSED lots
        for the position must be at least requested_shares or the
        trade is rejected with ERR_INSUFFICIENT_POSITION_SHARES".

        Claim: SELL FIFO of more shares than the position holds ->
        ERR_INSUFFICIENT_POSITION_SHARES.
        """
        _, account = setup_active_client_with_account()
        security = create_security(last_price_cents=10_000)
        # Buy 5 shares.
        buy_and_settle(account, security, 5)
        # Try to sell 10.
        trade = create_trade(
            account, security, side="SELL", requested_shares=10,
            cost_basis_method="FIFO",
        )
        resp = api.execute_trade(
            account["id"], trade["id"],
            TEST_USERS["advisor_headers"],
        )
        validate_error(
            resp,
            ApiErrorId.ERR_INSUFFICIENT_POSITION_SHARES.value,
        )

    def test_sell_specific_lot_unknown_lot_rejected(self, api):
        """PRD §3.4: "When the method is SPECIFIC_LOT, a
        specific_lot_id must accompany the body and must resolve to a
        Lot whose position_id belongs to the same Position being sold
        and whose shares_remaining is at least the requested share
        count; otherwise the trade is rejected with
        ERR_INSUFFICIENT_LOT_SHARES."

        Claim: SELL SPECIFIC_LOT with a non-resolving / nonexistent
        specific_lot_id -> ERR_INSUFFICIENT_LOT_SHARES (the lot
        cannot satisfy the share requirement).
        """
        _, account = setup_active_client_with_account()
        security = create_security(last_price_cents=10_000)
        buy_and_settle(account, security, 3)
        payload = create_trade_payload(
            security_id=security["id"], side="SELL",
            requested_shares=3, cost_basis_method="SPECIFIC_LOT",
            specific_lot_id="00000000-0000-0000-0000-000000000000",
        )
        # The PRD wraps both 'unknown lot' and 'insufficient lot
        # shares' under ERR_INSUFFICIENT_LOT_SHARES per the priority
        # 11 validation in §2.7; FK violation is also a faithful
        # PRD-only reading, so we accept either ID via
        # validate_error_is_one_of.
        from test_helpers import validate_error_is_one_of
        # Create may surface the error, otherwise execute will.
        resp = api.create_trade(
            account["id"], payload,
            TEST_USERS["advisor_headers"],
        )
        if resp.status_code >= 400:
            validate_error_is_one_of(
                resp,
                [
                    ApiErrorId.ERR_INSUFFICIENT_LOT_SHARES.value,
                    ApiErrorId.ERR_FK_NOT_FOUND.value,
                ],
            )
        else:
            trade = resp.json()["data"]
            resp2 = api.execute_trade(
                account["id"], trade["id"],
                TEST_USERS["advisor_headers"],
            )
            validate_error_is_one_of(
                resp2,
                [
                    ApiErrorId.ERR_INSUFFICIENT_LOT_SHARES.value,
                    ApiErrorId.ERR_FK_NOT_FOUND.value,
                ],
            )


# ===========================================================================
# Cancel — PRD §3.4
# ===========================================================================
class TestCancel:

    def test_cancel_pending_trade_succeeds(self, api):
        """PRD §3.4: "A PENDING trade can also be cancelled. The
        cancel action requires the trade to still be in PENDING and
        to not be associated with a RebalanceRun".

        Claim: cancel of a PENDING client-initiated trade ->
        status=CANCELLED.
        """
        scenario = setup_pending_buy_trade()
        resp = api.cancel_trade(
            scenario["account"]["id"], scenario["trade"]["id"],
            None, TEST_USERS["advisor_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"

    def test_cancel_non_pending_rejected(self, api):
        """PRD §3.4: "A cancel attempt that fails either condition
        surfaces as ERR_INVALID_TRADE_STATE."

        Claim: cancel after execute -> ERR_INVALID_TRADE_STATE.
        """
        scenario = setup_pending_buy_trade()
        execute_trade(scenario["account"], scenario["trade"])
        resp = api.cancel_trade(
            scenario["account"]["id"], scenario["trade"]["id"],
            None, TEST_USERS["advisor_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_TRADE_STATE.value,
        )


# ===========================================================================
# Account-frozen gate — PRD §3.3
# ===========================================================================
class TestAccountFrozenGate:

    def test_create_trade_on_frozen_account_rejected(self, api):
        """PRD §3.3: "Any mutating operation on an account or its
        children — trade creation, execute, settle, cancel,
        rebalance start, harvest approve, harvest execute, dividend
        recording, cash deposit — requires compliance_status of
        ACTIVE. A frozen account rejects the mutation with
        ERR_ACCOUNT_FROZEN."

        Claim: POST trade on a frozen account -> ERR_ACCOUNT_FROZEN.
        """
        _, account = setup_active_client_with_account()
        freeze_account(account)
        security = create_security()
        payload = create_trade_payload(
            security_id=security["id"], side="BUY",
            requested_shares=1,
        )
        resp = api.create_trade(
            account["id"], payload,
            TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_FROZEN.value)

    def test_execute_on_frozen_account_rejected(self, api):
        """PRD §3.3: "Any mutating operation on an account or its
        children — trade creation, execute, settle, cancel,
        rebalance start, harvest approve, harvest execute, dividend
        recording, cash deposit — requires compliance_status of
        ACTIVE. A frozen account rejects the mutation with
        ERR_ACCOUNT_FROZEN."

        Claim: execute on a frozen account -> ERR_ACCOUNT_FROZEN.
        """
        scenario = setup_frozen_account_with_pending_buy()
        resp = api.execute_trade(
            scenario["account"]["id"], scenario["trade"]["id"],
            TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_FROZEN.value)
