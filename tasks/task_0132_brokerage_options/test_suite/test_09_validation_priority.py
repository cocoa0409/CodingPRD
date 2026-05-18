"""Validation ordering — PRD §2.9, §2.10.

Coverage targets:
- Existence wins over business rules when the path id is unresolvable.
- Posture gates (ACCOUNT_NOT_APPROVED / KYC_NOT_VERIFIED /
  TRADING_FROZEN) run before source-state and business checks.
- ERR_TRADING_FROZEN covers RESTRICTED, PDT_FROZEN, TRANSFER_LOCKED on
  POST /orders.

Per the Silence-pattern policy in SKILL.md (validation-priority), tests
only assert specific orderings that PRD prose explicitly pins.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PDT_EQUITY_FLOOR_CENTS,
    TEST_USERS,
    create_order_payload,
    make_customer_headers,
    setup_account_below_pdt_floor_with_n_day_trades,
    setup_account_with_outbound_acat_validated,
    setup_approved_customer_and_account,
    setup_funded_account,
    trigger_fourth_day_trade,
    validate_error,
)


# ===========================================================================
# Existence runs before everything else — PRD §2.8
# ===========================================================================
class TestExistenceFirst:
    """PRD §2.8: 'Path parameters are resolved strictly left to right,
    and a path-parameter failure at any step short-circuits all
    subsequent validation. ... Existence checks always run before
    ownership, state, and business-rule checks.'"""

    def test_close_unknown_account_returns_not_found_not_dependencies(
        self, api,
    ):
        """PRD §2.8: "Existence checks always run before ownership,
        state, and business-rule checks."

        Claim: POST /brokerage/accounts/{nonexistent}/close ->
        ERR_ACCOUNT_NOT_FOUND, not ERR_ACCOUNT_HAS_DEPENDENCIES — even
        when a sibling account on the same customer has open orders
        that would have tripped the dependency check on a real id.
        """
        # Build a sibling account with a working order so the
        # dependency check WOULD trip on a real id.
        from test_helpers import setup_account_with_working_limit_order
        customer, _account, _order = (
            setup_account_with_working_limit_order(
                account_type="CASH", cash_amount_cents=10_000_000,
            )
        )
        # But close a NON-EXISTENT id with the same customer's headers.
        resp = api.close_account(
            NON_EXISTENT_UUID, make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


# ===========================================================================
# Posture gate — ERR_TRADING_FROZEN covers non-OPEN postures
# (PRD §2.9, §3.4, §3.5)
# ===========================================================================
class TestTradingFrozenPostureGate:
    """PRD §2.9: 'for order submission specifically,
    Account.trading_posture must equal OPEN or the request is rejected
    with ERR_TRADING_FROZEN — this latter rejection thus covers
    RESTRICTED, PDT_FROZEN, and TRANSFER_LOCKED postures alike.'"""

    def test_order_blocked_when_posture_is_transfer_locked(self, api):
        """PRD §2.9: "for order submission specifically,
        Account.trading_posture must equal OPEN or the request is
        rejected with ERR_TRADING_FROZEN — this latter rejection thus
        covers RESTRICTED, PDT_FROZEN, and TRANSFER_LOCKED postures
        alike."

        Claim: POST /brokerage/orders while
        trading_posture=TRANSFER_LOCKED -> ERR_TRADING_FROZEN / 409.
        """
        customer, account, _transfer = (
            setup_account_with_outbound_acat_validated()
        )
        assert account["trading_posture"] == "TRANSFER_LOCKED"
        payload = create_order_payload(
            account_id=account["id"],
            symbol="AAPL", instrument_type="EQUITY",
            side="BUY", order_type="LIMIT",
            quantity=1, limit_price_cents=100,
        )
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRADING_FROZEN.value)

    def test_order_blocked_when_posture_is_pdt_frozen(self, api):
        """PRD §2.9: "for order submission specifically,
        Account.trading_posture must equal OPEN or the request is
        rejected with ERR_TRADING_FROZEN — this latter rejection thus
        covers RESTRICTED, PDT_FROZEN, and TRANSFER_LOCKED postures
        alike."

        Claim: POST /brokerage/orders while
        trading_posture=PDT_FROZEN -> ERR_TRADING_FROZEN / 409.
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
        # Now posture should be PDT_FROZEN.
        payload = create_order_payload(
            account_id=account["id"],
            symbol="AAPL", instrument_type="EQUITY",
            side="BUY", order_type="LIMIT",
            quantity=1, limit_price_cents=100,
        )
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRADING_FROZEN.value)


# ===========================================================================
# Account-not-approved gate — PRD §2.9
# ===========================================================================
class TestAccountNotApprovedGate:
    """PRD §2.9: 'Account.status must equal APPROVED or the request is
    rejected with ERR_ACCOUNT_NOT_APPROVED'."""

    def test_order_blocked_when_account_is_pending_kyc(self, api):
        """PRD §2.9: "Account.status must equal APPROVED or the
        request is rejected with ERR_ACCOUNT_NOT_APPROVED".

        Claim: POST /brokerage/orders on a PENDING_KYC account ->
        ERR_ACCOUNT_NOT_APPROVED / 409.
        """
        from test_helpers import create_account, create_customer
        customer = create_customer()
        account = create_account(customer=customer)
        # Account is PENDING_KYC.
        assert account["status"] == "PENDING_KYC"
        payload = create_order_payload(
            account_id=account["id"],
            symbol="AAPL", instrument_type="EQUITY",
            side="BUY", order_type="LIMIT",
            quantity=1, limit_price_cents=100,
        )
        resp = api.create_order(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_ACCOUNT_NOT_APPROVED.value,
        )


# ===========================================================================
# KYC-not-verified gate — PRD §2.9
# ===========================================================================
# Note: this gate is impossible to test in isolation from
# account-not-approved without a path where Account.status=APPROVED
# while Customer.kyc_status != VERIFIED. The PRD's KYC verification
# pipeline ties these together (verify cascades both), so a customer
# with kyc_status=PENDING also has account in KYC_REVIEW (not APPROVED).
# Skipping per the `validation-priority` Silence-pattern: PRD prose
# does not name a reachable single-gate state for ERR_KYC_NOT_VERIFIED
# distinct from the cascade.
