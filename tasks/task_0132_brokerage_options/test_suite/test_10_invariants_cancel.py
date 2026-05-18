"""Compensating-action invariants: order cancel preserves cash;
outbound ACAT cancel preserves equity.

Coverage targets:
- A LIMIT BUY does not debit cash at submission (PRD §3.3 says cash is
  adjusted only on FILL, not on accept/working).
- DELETE /brokerage/orders/{id} on a WORKING order leaves cash
  unchanged.
- POST OUTBOUND ACAT + validate does not move funds.
- DELETE OUTBOUND ACAT (VALIDATED) does not move funds.
- TRANSFER_LOCKED posture flip reverts to OPEN after cancel; equity is
  preserved through the cycle.
"""
from __future__ import annotations

from test_helpers import (
    TEST_USERS,
    cancel_order,
    create_acat_transfer_payload,
    make_customer_headers,
    setup_account_with_outbound_acat_initiated,
    setup_account_with_outbound_acat_validated,
    setup_account_with_working_limit_order,
    submit_working_limit_buy,
    validate_success,
)


# ===========================================================================
# LIMIT order cancel preserves cash — PRD §3.3 + §3.4
# ===========================================================================
class TestCancelOrderPreservesCash:
    """PRD §3.3: 'A MARKET order auto-fills immediately ...
    Account.cash_balance_cents is adjusted by signed quantity times
    fill price'. By exclusion, non-MARKET (WORKING) orders do not
    adjust cash until they are filled."""

    def test_post_limit_does_not_debit_cash(self, api):
        """PRD §3.3: "Once margin clears, the order is persisted with
        margin_requirement_cents set to the computed total. A MARKET
        order auto-fills immediately at the submitted market-reference
        price ... Any non-MARKET order is persisted with Order.status
        set to ACCEPTED and then automatically advances to WORKING".

        Claim: a LIMIT order persisted at ACCEPTED/WORKING leaves
        cash_balance_cents unchanged (only fills adjust cash per PRD
        §3.3).
        """
        customer, account, order = (
            setup_account_with_working_limit_order(
                account_type="MARGIN_REG_T",
                cash_amount_cents=10_000_000,
            )
        )
        # Re-read account.
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert fresh["cash_balance_cents"] == 10_000_000

    def test_cancel_working_order_preserves_cash(self, api):
        """PRD §3.3: "A customer may cancel their own order while it is
        still in ACCEPTED or WORKING; the result is Order.status set
        to CANCELLED."
        PRD §3.3 (fills only): "Account.cash_balance_cents is adjusted
        by signed quantity times fill price".

        Claim: DELETE on a never-filled WORKING order leaves
        cash_balance_cents unchanged before/after the cancel.
        """
        customer, account, order = (
            setup_account_with_working_limit_order(
                account_type="MARGIN_REG_T",
                cash_amount_cents=10_000_000,
            )
        )
        before = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        cancel_order(customer, order["id"])
        after = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert (
            after["cash_balance_cents"] == before["cash_balance_cents"]
        ), (
            "cancelling a never-filled order must not move cash"
        )


# ===========================================================================
# OUTBOUND ACAT validate + cancel preserves equity — PRD §3.5
# ===========================================================================
class TestCancelOutboundAcatPreservesEquity:
    """PRD §3.5: 'When the clock subsequently crosses
    expected_completion_at, the transfer auto-advances from IN_TRANSIT
    to COMPLETED ... An OUTBOUND completion subtracts
    requested_value_cents from both Account.cash_balance_cents and
    Account.equity_value_cents'. By exclusion, validation alone does
    NOT move funds — only completion does."""

    def test_validate_does_not_move_funds(self, api):
        """PRD §3.5: "An OUTBOUND completion subtracts
        requested_value_cents from both Account.cash_balance_cents and
        Account.equity_value_cents".

        Claim: OUTBOUND validate leaves cash and equity unchanged; the
        debit happens at COMPLETED, not at VALIDATED.
        """
        customer, account, transfer = (
            setup_account_with_outbound_acat_initiated(
                cash_amount_cents=10_000_000,
                transfer_value_cents=500_000,
            )
        )
        before_cash = account["cash_balance_cents"]
        before_equity = account["equity_value_cents"]
        # Validate.
        v_resp = api.validate_acat_transfer(
            transfer["id"], TEST_USERS["compliance_headers"],
        )
        validate_success(v_resp)
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert fresh["cash_balance_cents"] == before_cash
        assert fresh["equity_value_cents"] == before_equity

    def test_cancel_validated_outbound_preserves_equity(self, api):
        """PRD §3.5: "if the cancellation occurs on a VALIDATED
        OUTBOUND transfer — the trading posture reverts from
        TRANSFER_LOCKED back to OPEN."
        PRD §3.5 (completion-only debit): "An OUTBOUND completion
        subtracts requested_value_cents from both
        Account.cash_balance_cents and Account.equity_value_cents".

        Claim: cancelling a VALIDATED OUTBOUND transfer (terminal
        CANCELLED reached without COMPLETED) leaves
        equity_value_cents unchanged from the pre-validate value.
        """
        customer, account, transfer = (
            setup_account_with_outbound_acat_validated(
                cash_amount_cents=10_000_000,
                transfer_value_cents=500_000,
            )
        )
        before_equity = account["equity_value_cents"]
        # Cancel.
        c_resp = api.cancel_acat_transfer(
            transfer["id"], make_customer_headers(customer["id"]),
        )
        validate_success(c_resp)
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert fresh["equity_value_cents"] == before_equity, (
            "cancelling a VALIDATED OUTBOUND must not move equity; "
            "PRD §3.5 reserves the debit for COMPLETED."
        )
        # And trading_posture reverts to OPEN.
        assert fresh["trading_posture"] == "OPEN"
