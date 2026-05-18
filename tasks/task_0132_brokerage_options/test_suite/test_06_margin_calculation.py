"""Margin requirement calculation: CASH / Reg T / PMA + naked add-on.

Coverage targets (PRD §3.3):
- CASH base = full notional (100%).
- MARGIN_REG_T base = ceil(notional * 0.50).
- MARGIN_PMA base = ceil(notional * 0.15) and is strictly lower than
  Reg T on identical inputs.
- Reg T naked option add-on = ceil(notional * 0.20); PMA naked has no
  add-on.
- Per-term ceiling rounding BEFORE summation (rounding order is pinned).
- ERR_INSUFFICIENT_MARGIN when computed requirement > cash_balance_cents.
"""
from __future__ import annotations

import math

from test_helpers import (
    ApiErrorId,
    NAKED_ADDON_RATE,
    PMA_RATE,
    REG_T_RATE,
    TEST_USERS,
    create_order_payload,
    make_customer_headers,
    setup_account_with_options_level,
    setup_funded_account,
    submit_order,
    validate_error,
)


# ===========================================================================
# CASH 100% — PRD §3.3
# ===========================================================================
class TestCashFullMargin:
    """PRD §3.3: 'For a CASH account, the base equals the full notional
    — 100% of the trade must be available in cash.'"""

    def test_cash_margin_equals_notional(self, api):
        """PRD §3.3: "For a CASH account, the base equals the full
        notional — 100% of the trade must be available in cash."

        Claim: CASH account order with notional=N -> stored
        margin_requirement_cents == N.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=10_000_000,
        )
        # qty=10, limit=$1.00 -> notional = 1000 cents.
        order = submit_order(
            customer, account,
            symbol="AAPL", instrument_type="EQUITY",
            side="BUY", order_type="LIMIT",
            quantity=10, limit_price_cents=100,
        )
        assert order["margin_requirement_cents"] == 1000


# ===========================================================================
# Reg T 50% — PRD §3.3
# ===========================================================================
class TestRegTHalfMargin:
    """PRD §3.3: 'For a MARGIN_REG_T account, Regulation T's 50%
    initial-margin rule applies: the base is the notional multiplied by
    0.50 and rounded up to the next whole cent.'"""

    def test_reg_t_margin_half_notional(self, api):
        """PRD §3.3: "For a MARGIN_REG_T account, Regulation T's 50%
        initial-margin rule applies: the base is the notional
        multiplied by 0.50 and rounded up to the next whole cent."

        Claim: Reg T account; qty=100, limit=$150 -> notional =
        1_500_000 cents; margin_requirement_cents == ceil(1_500_000 *
        0.50) == 750_000.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=10_000_000,
        )
        notional = 100 * 15_000
        order = submit_order(
            customer, account,
            symbol="AAPL", instrument_type="EQUITY",
            side="BUY", order_type="LIMIT",
            quantity=100, limit_price_cents=15_000,
        )
        expected = math.ceil(notional * REG_T_RATE)
        assert order["margin_requirement_cents"] == expected == 750_000


# ===========================================================================
# PMA 15% — PRD §3.3
# ===========================================================================
class TestPmaStressMargin:
    """PRD §3.3: 'For a MARGIN_PMA account, Portfolio Margin's stress-
    test rate of 15% applies: the base is the notional multiplied by
    0.15 and rounded up to the next whole cent — strictly lower than
    the Reg T figure on identical inputs, which is the entire point of
    the PMA framework.'"""

    def test_pma_margin_fifteen_percent(self, api):
        """PRD §3.3: "For a MARGIN_PMA account, Portfolio Margin's
        stress-test rate of 15% applies: the base is the notional
        multiplied by 0.15 and rounded up to the next whole cent —
        strictly lower than the Reg T figure on identical inputs".

        Claim: PMA account; qty=100, limit=$150 -> notional =
        1_500_000 cents; margin_requirement_cents == ceil(1_500_000 *
        0.15) == 225_000.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_PMA", cash_amount_cents=10_000_000,
        )
        notional = 100 * 15_000
        order = submit_order(
            customer, account,
            symbol="AAPL", instrument_type="EQUITY",
            side="BUY", order_type="LIMIT",
            quantity=100, limit_price_cents=15_000,
        )
        expected = math.ceil(notional * PMA_RATE)
        assert order["margin_requirement_cents"] == expected == 225_000


# ===========================================================================
# Reg T naked option add-on — PRD §3.3
# ===========================================================================
class TestRegTNakedAddon:
    """PRD §3.3: 'The add-on term applies only to a MARGIN_REG_T
    account submitting an option order with option_strategy equal to
    NAKED_CALL or NAKED_PUT; in that single case, an additional 20% of
    notional, rounded up to the next whole cent, is added to the
    base.'"""

    def test_reg_t_naked_call_per_term_rounding(self, api):
        """PRD §3.3: "an additional 20% of notional, rounded up to the
        next whole cent, is added to the base ... ceiling rounding is
        applied to each term before the sum, so the rounding order is
        pinned and cannot be relaxed by aggregating first."

        Claim: Reg T NAKED_CALL with notional=12_347 (qty=1,
        limit=$123.47) -> margin_requirement_cents ==
        ceil(12_347 * 0.50) + ceil(12_347 * 0.20)
        == 6_174 + 2_470 == 8_644 (per-term ceil).
        Sum-then-ceil would give ceil(12_347 * 0.70) = 8_643 — wrong.
        """
        customer, account = setup_account_with_options_level(
            level=4,
            account_type="MARGIN_REG_T",
            cash_amount_cents=10_000_000,
        )
        notional = 12_347
        order = submit_order(
            customer, account,
            symbol="AAPL", instrument_type="OPTION",
            option_strategy="NAKED_CALL",
            side="SELL", order_type="LIMIT",
            quantity=1, limit_price_cents=notional,
        )
        base = math.ceil(notional * REG_T_RATE)   # 6_174
        addon = math.ceil(notional * NAKED_ADDON_RATE)  # 2_470
        assert order["margin_requirement_cents"] == base + addon == 8_644
        # And explicitly that sum-then-ceil would be wrong.
        wrong = math.ceil(notional * (REG_T_RATE + NAKED_ADDON_RATE))
        assert order["margin_requirement_cents"] != wrong, (
            "PRD §3.3: ceiling rounding is applied to each term BEFORE "
            "the sum — sum-then-ceil is the wrong rounding order."
        )


# ===========================================================================
# PMA naked has no add-on — PRD §3.3
# ===========================================================================
class TestPmaNoNakedAddon:
    """PRD §3.3: 'A PMA account submitting a naked option carries no
    such add-on (PMA replaces the add-on with its lower base rate). On
    any other combination of account_type and option_strategy, the
    add-on is exactly 0.'"""

    def test_pma_naked_has_no_addon(self, api):
        """PRD §3.3: "A PMA account submitting a naked option carries
        no such add-on (PMA replaces the add-on with its lower base
        rate)."

        Claim: PMA account with NAKED_CALL strategy ->
        margin_requirement_cents == ceil(notional * 0.15) only, no
        20% add-on.
        """
        customer, account = setup_account_with_options_level(
            level=4,
            account_type="MARGIN_PMA",
            cash_amount_cents=10_000_000,
        )
        notional = 100_000  # qty=1, limit=$1000
        order = submit_order(
            customer, account,
            symbol="AAPL", instrument_type="OPTION",
            option_strategy="NAKED_CALL",
            side="SELL", order_type="LIMIT",
            quantity=1, limit_price_cents=notional,
        )
        expected = math.ceil(notional * PMA_RATE)
        assert order["margin_requirement_cents"] == expected == 15_000


# ===========================================================================
# Insufficient margin — PRD §3.3
# ===========================================================================
class TestInsufficientMargin:
    """PRD §3.3: 'an order whose required initial margin exceeds the
    available cash balance is rejected with ERR_INSUFFICIENT_MARGIN at
    HTTP 422.'"""

    def test_required_margin_exceeds_cash_balance(self, api):
        """PRD §3.3: "an order whose required initial margin exceeds
        the available cash balance is rejected with
        ERR_INSUFFICIENT_MARGIN at HTTP 422."

        Claim: Reg T account with $1k cash and an order whose Reg T
        margin requirement is $7.5k -> ERR_INSUFFICIENT_MARGIN / 422.
        """
        customer, account = setup_funded_account(
            account_type="MARGIN_REG_T", cash_amount_cents=100_000,  # $1k
        )
        # notional = 100*15_000 = 1_500_000 cents; Reg T req = 750_000.
        payload = create_order_payload(
            account_id=account["id"],
            symbol="AAPL", instrument_type="EQUITY",
            side="BUY", order_type="LIMIT",
            quantity=100, limit_price_cents=15_000,
        )
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_MARGIN.value,
        )
