"""Order-submission payload validation + lifecycle transitions.

Coverage targets (PRD §3.3):
- option_strategy required iff instrument_type==OPTION
  -> ERR_ORDER_STRATEGY_REQUIRED.
- limit_price_cents required for LIMIT / STOP_LIMIT / TAKE_PROFIT
  -> ERR_ORDER_PRICE_MISSING.
- stop_price_cents required for STOP / STOP_LIMIT
  -> ERR_ORDER_PRICE_MISSING.
- quantity >= 1, price > 0 -> ERR_VALIDATION.
- option_strategy vs Account.options_level
  -> ERR_OPTIONS_LEVEL_INSUFFICIENT.
- MARKET auto-fills; non-MARKET advances ACCEPTED -> WORKING.
- Order cancel transitions: ACCEPTED/WORKING -> CANCELLED, wrong state
  -> ERR_INVALID_STATE.
- Operator fill: price respects LIMIT/STOP semantics
  -> ERR_FILL_PRICE_VIOLATES_LIMITS.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_order,
    create_order_payload,
    fill_order_payload,
    make_customer_headers,
    setup_account_with_options_level,
    setup_account_with_working_limit_order,
    setup_funded_account,
    submit_order,
    submit_working_limit_buy,
    validate_error,
    validate_success,
)


# ===========================================================================
# Strategy required iff OPTION — PRD §3.3
# ===========================================================================
class TestOptionStrategyRequiredness:
    """PRD §3.3: 'option_strategy field is required when and only when
    instrument_type equals OPTION; supplying it for an equity order, or
    omitting it for an options order, is rejected with
    ERR_ORDER_STRATEGY_REQUIRED at HTTP 422.'"""

    def test_option_without_strategy_rejected(self, api):
        """PRD §3.3: "The option_strategy field is required when and
        only when instrument_type equals OPTION; supplying it for an
        equity order, or omitting it for an options order, is rejected
        with ERR_ORDER_STRATEGY_REQUIRED at HTTP 422."

        Claim: instrument_type=OPTION without option_strategy
        -> ERR_ORDER_STRATEGY_REQUIRED / 422.
        """
        customer, account = setup_account_with_options_level(
            level=4,
            account_type="MARGIN_REG_T",
            cash_amount_cents=10_000_000,
        )
        payload = create_order_payload(
            account_id=account["id"],
            instrument_type="OPTION",
            option_strategy=None,
            side="BUY", order_type="LIMIT",
            quantity=1, limit_price_cents=100,
        )
        payload.pop("option_strategy", None)
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_ORDER_STRATEGY_REQUIRED.value,
        )

    def test_equity_with_strategy_rejected(self, api):
        """PRD §3.3: "The option_strategy field is required when and
        only when instrument_type equals OPTION; supplying it for an
        equity order, or omitting it for an options order, is rejected
        with ERR_ORDER_STRATEGY_REQUIRED at HTTP 422."

        Claim: instrument_type=EQUITY with option_strategy present
        -> ERR_ORDER_STRATEGY_REQUIRED / 422.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        payload = create_order_payload(
            account_id=account["id"],
            instrument_type="EQUITY",
            option_strategy="LONG_CALL",
            side="BUY", order_type="LIMIT",
            quantity=1, limit_price_cents=100,
        )
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_ORDER_STRATEGY_REQUIRED.value,
        )


# ===========================================================================
# Price-field requiredness — PRD §3.3
# ===========================================================================
class TestOrderPriceRequiredness:
    """PRD §3.3: 'limit_price_cents is required for LIMIT, STOP_LIMIT,
    and TAKE_PROFIT orders; stop_price_cents is required for STOP and
    STOP_LIMIT orders; any missing price for the chosen order_type is
    rejected with ERR_ORDER_PRICE_MISSING at HTTP 422.'"""

    @pytest.mark.parametrize("order_type",
                             ["LIMIT", "STOP_LIMIT", "TAKE_PROFIT"])
    def test_limit_price_missing_rejected(self, api, order_type):
        """PRD §3.3: "limit_price_cents is required for LIMIT,
        STOP_LIMIT, and TAKE_PROFIT orders ... any missing price for
        the chosen order_type is rejected with ERR_ORDER_PRICE_MISSING
        at HTTP 422."

        Claim: missing limit_price_cents for LIMIT/STOP_LIMIT/
        TAKE_PROFIT -> ERR_ORDER_PRICE_MISSING.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        payload = {
            "account_id": account["id"],
            "symbol": "AAPL",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "order_type": order_type,
            "quantity": 1,
        }
        if order_type in ("STOP_LIMIT",):
            payload["stop_price_cents"] = 100
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_PRICE_MISSING.value)

    def test_stop_price_missing_rejected(self, api):
        """PRD §3.3: "stop_price_cents is required for STOP and
        STOP_LIMIT orders; any missing price for the chosen order_type
        is rejected with ERR_ORDER_PRICE_MISSING at HTTP 422."

        Claim: missing stop_price_cents for STOP order ->
        ERR_ORDER_PRICE_MISSING.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        payload = {
            "account_id": account["id"],
            "symbol": "AAPL",
            "instrument_type": "EQUITY",
            "side": "BUY",
            "order_type": "STOP",
            "quantity": 1,
            # stop_price_cents intentionally absent.
        }
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_PRICE_MISSING.value)


# ===========================================================================
# Generic validation — PRD §3.3
# ===========================================================================
class TestOrderGenericValidation:
    """PRD §3.3: 'quantity must be a positive integer, and any supplied
    price field must be strictly greater than 0; any breach is rejected
    with the generic ERR_VALIDATION at HTTP 422.'"""

    def test_quantity_zero_rejected(self, api):
        """PRD §3.3: "quantity must be a positive integer, and any
        supplied price field must be strictly greater than 0; any
        breach is rejected with the generic ERR_VALIDATION at HTTP
        422."

        Claim: quantity=0 -> ERR_VALIDATION / 422.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        payload = create_order_payload(
            account_id=account["id"],
            instrument_type="EQUITY",
            side="BUY", order_type="LIMIT",
            quantity=0, limit_price_cents=100,
        )
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_negative_limit_price_rejected(self, api):
        """PRD §3.3: "any supplied price field must be strictly greater
        than 0; any breach is rejected with the generic ERR_VALIDATION
        at HTTP 422."

        Claim: limit_price_cents=0 -> ERR_VALIDATION / 422.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        payload = create_order_payload(
            account_id=account["id"],
            instrument_type="EQUITY",
            side="BUY", order_type="LIMIT",
            quantity=1, limit_price_cents=0,
        )
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# option strategy vs account.options_level — PRD §3.3
# ===========================================================================
class TestOptionsLevelRequired:
    """PRD §3.3: 'COVERED_CALL and CASH_SECURED_PUT require an
    options_level of at least 1; LONG_CALL and LONG_PUT require at
    least 2; SPREAD requires at least 3; NAKED_CALL and NAKED_PUT
    require at least 4. Any order whose strategy outranks its account's
    level is rejected with ERR_OPTIONS_LEVEL_INSUFFICIENT at HTTP
    422.'"""

    def test_naked_call_requires_level_4(self, api):
        """PRD §3.3: "NAKED_CALL and NAKED_PUT require at least 4. Any
        order whose strategy outranks its account's level is rejected
        with ERR_OPTIONS_LEVEL_INSUFFICIENT at HTTP 422."

        Claim: NAKED_CALL on account with options_level=3 ->
        ERR_OPTIONS_LEVEL_INSUFFICIENT.
        """
        customer, account = setup_account_with_options_level(
            level=3, account_type="MARGIN_REG_T",
            cash_amount_cents=10_000_000,
        )
        assert account["options_level"] == 3
        payload = create_order_payload(
            account_id=account["id"],
            instrument_type="OPTION",
            option_strategy="NAKED_CALL",
            side="SELL", order_type="LIMIT",
            quantity=1, limit_price_cents=100,
        )
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_OPTIONS_LEVEL_INSUFFICIENT.value,
        )

    def test_long_call_requires_level_2(self, api):
        """PRD §3.3: "LONG_CALL and LONG_PUT require at least 2 ... Any
        order whose strategy outranks its account's level is rejected
        with ERR_OPTIONS_LEVEL_INSUFFICIENT at HTTP 422."

        Claim: LONG_CALL on account with options_level=1 ->
        ERR_OPTIONS_LEVEL_INSUFFICIENT.
        """
        customer, account = setup_account_with_options_level(
            level=1, account_type="MARGIN_REG_T",
            cash_amount_cents=10_000_000,
        )
        payload = create_order_payload(
            account_id=account["id"],
            instrument_type="OPTION",
            option_strategy="LONG_CALL",
            side="BUY", order_type="LIMIT",
            quantity=1, limit_price_cents=100,
        )
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_OPTIONS_LEVEL_INSUFFICIENT.value,
        )


# ===========================================================================
# Order state-machine: MARKET auto-fills, non-MARKET -> WORKING
# (PRD §3.3)
# ===========================================================================
class TestOrderInitialStateTransition:

    def test_limit_order_advances_to_working(self, api):
        """PRD §3.3: "Any non-MARKET order is persisted with
        Order.status set to ACCEPTED and then automatically advances
        to WORKING on the same request as the system routes it to
        market."

        Claim: a LIMIT order returns with status=WORKING (auto-
        advanced from ACCEPTED on the same request).
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        order = submit_working_limit_buy(
            customer, account, quantity=1, limit_price_cents=100,
        )
        assert_order(order)
        assert order["status"] == "WORKING"

    def test_market_order_auto_fills(self, api):
        """PRD §3.3: "A MARKET order auto-fills immediately at the
        submitted market-reference price: Order.status becomes FILLED,
        fill_price_cents is set to that reference, filled_at is set to
        the current now()".

        Claim: a MARKET order returns with status=FILLED and
        fill_price_cents populated.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        order = submit_order(
            customer, account,
            symbol="AAPL", instrument_type="EQUITY",
            side="BUY", order_type="MARKET",
            quantity=1, limit_price_cents=100,  # market-reference price
        )
        assert order["status"] == "FILLED"
        assert order["fill_price_cents"] is not None
        assert order["filled_at"] is not None


# ===========================================================================
# Cancel — PRD §3.3
# ===========================================================================
class TestCancelOrder:
    """PRD §3.3: 'A customer may cancel their own order while it is
    still in ACCEPTED or WORKING; the result is Order.status set to
    CANCELLED. Cancellation against any other status returns
    ERR_INVALID_STATE.'"""

    def test_cancel_working_order_succeeds(self, api):
        """PRD §3.3: "A customer may cancel their own order while it is
        still in ACCEPTED or WORKING; the result is Order.status set
        to CANCELLED."

        Claim: DELETE /brokerage/orders/{id} on a WORKING order ->
        Order.status = CANCELLED.
        """
        customer, account, order = (
            setup_account_with_working_limit_order(
                account_type="MARGIN_REG_T",
                cash_amount_cents=10_000_000,
            )
        )
        resp = api.cancel_order(
            order["id"], make_customer_headers(customer["id"]),
        )
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_filled_order_rejected(self, api):
        """PRD §3.3: "Cancellation against any other status returns
        ERR_INVALID_STATE."

        Claim: DELETE /brokerage/orders/{id} on a FILLED order ->
        ERR_INVALID_STATE / 409.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        filled = submit_order(
            customer, account,
            symbol="AAPL", instrument_type="EQUITY",
            side="BUY", order_type="MARKET",
            quantity=1, limit_price_cents=100,
        )
        assert filled["status"] == "FILLED"
        resp = api.cancel_order(
            filled["id"], make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Operator fill — PRD §3.3
# ===========================================================================
class TestOperatorFill:
    """PRD §3.3 operator fill semantics."""

    def test_fill_limit_buy_above_limit_rejected(self, api):
        """PRD §3.3: "a LIMIT BUY requires the execution price to be
        less than or equal to limit_price_cents ... Any violation is
        rejected with ERR_FILL_PRICE_VIOLATES_LIMITS at HTTP 422."

        Claim: operator fill on LIMIT BUY at price > limit_price_cents
        -> ERR_FILL_PRICE_VIOLATES_LIMITS / 422.
        """
        customer, account, order = (
            setup_account_with_working_limit_order(
                account_type="MARGIN_REG_T",
                cash_amount_cents=10_000_000,
            )
        )
        # LIMIT BUY @ 100 cents. Operator fills at 110 cents -> too high.
        resp = api.fill_order(
            order["id"],
            fill_order_payload(execution_price_cents=110),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_FILL_PRICE_VIOLATES_LIMITS.value,
        )

    def test_fill_limit_buy_at_or_below_limit_succeeds(self, api):
        """PRD §3.3: "a LIMIT BUY requires the execution price to be
        less than or equal to limit_price_cents".

        Claim: operator fill on LIMIT BUY at price <= limit succeeds;
        order transitions WORKING -> FILLED with fill_price_cents and
        filled_at populated.
        """
        customer, account, order = (
            setup_account_with_working_limit_order(
                account_type="MARGIN_REG_T",
                cash_amount_cents=10_000_000,
            )
        )
        # LIMIT BUY @ 100; operator fills at 100 (exactly at limit).
        resp = api.fill_order(
            order["id"],
            fill_order_payload(execution_price_cents=100),
            TEST_USERS["platform_admin_headers"],
        )
        filled = validate_success(resp)
        assert filled["status"] == "FILLED"
        assert filled["fill_price_cents"] == 100
        assert filled["filled_at"] is not None

    def test_fill_non_working_order_rejected(self, api):
        """PRD §3.3: "Operator fill is allowed only when Order.status
        equals WORKING; an attempt against any other status returns
        ERR_INVALID_STATE."

        Claim: fill on a FILLED order -> ERR_INVALID_STATE / 409.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        filled = submit_order(
            customer, account,
            symbol="AAPL", instrument_type="EQUITY",
            side="BUY", order_type="MARKET",
            quantity=1, limit_price_cents=100,
        )
        assert filled["status"] == "FILLED"
        resp = api.fill_order(
            filled["id"],
            fill_order_payload(execution_price_cents=100),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
