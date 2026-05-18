"""Account lifecycle: create, initial state, close preconditions.

Coverage targets (PRD §3.1, §3.6):
- Account creation initial state: PENDING_KYC + RESTRICTED + zeros.
- Account close preconditions: no open orders, no non-terminal ACAT,
  cash_balance == 0, equity_value == 0.
- Account close cascade: status -> CLOSED, posture -> RESTRICTED.
- Account close failure due to open orders -> ERR_ACCOUNT_HAS_DEPENDENCIES.
- Account close failure due to non-terminal ACAT -> ERR_ACCOUNT_HAS_DEPENDENCIES.
- Account close failure due to non-zero cash/equity -> ERR_ACCOUNT_HAS_DEPENDENCIES.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_account,
    create_account,
    create_customer,
    make_customer_headers,
    setup_account_with_outbound_acat_initiated,
    setup_account_with_working_limit_order,
    setup_approved_customer_and_account,
    setup_funded_account,
    validate_error,
    validate_success,
)


# ===========================================================================
# Account creation initial state — PRD §3.1
# ===========================================================================
class TestAccountCreation:
    """PRD §3.1: 'The newly-minted Account begins life with status set
    to PENDING_KYC and trading_posture set to RESTRICTED; its
    options_level, cash_balance_cents, and equity_value_cents all start
    at 0, its pdt_flag is false, and its pdt_flagged_at is null.'"""

    def test_account_initial_state(self, api):
        """PRD §3.1: "The newly-minted Account begins life with status
        set to PENDING_KYC and trading_posture set to RESTRICTED; its
        options_level, cash_balance_cents, and equity_value_cents all
        start at 0, its pdt_flag is false, and its pdt_flagged_at is
        null."

        Claim: every field on a freshly-created Account matches the
        PRD-specified initial values.
        """
        customer = create_customer()
        account = create_account(customer=customer)
        assert_account(account)
        assert account["status"] == "PENDING_KYC"
        assert account["trading_posture"] == "RESTRICTED"
        assert account["options_level"] == 0
        assert account["cash_balance_cents"] == 0
        assert account["equity_value_cents"] == 0
        assert account["pdt_flag"] is False
        assert account["pdt_flagged_at"] is None
        assert account["version"] == 1


# ===========================================================================
# Account close — PRD §3.6
# ===========================================================================
class TestAccountClose:
    """PRD §3.6 close preconditions and side-effects."""

    def test_close_approved_empty_account_succeeds(self, api):
        """PRD §3.6: "A customer can close an APPROVED account, but
        only when every dependency is settled: there must be no Order
        whose status is in ACCEPTED or WORKING, no ACATTransfer whose
        status is in INITIATED, VALIDATED, or IN_TRANSIT for this
        account, and Account.cash_balance_cents must equal 0 and
        Account.equity_value_cents must equal 0 ... On success,
        Account.status advances from APPROVED to terminal CLOSED and
        Account.trading_posture is set back to RESTRICTED."

        Claim: an APPROVED account with no open orders / transfers and
        zero cash/equity can be closed: status -> CLOSED, posture ->
        RESTRICTED.
        """
        customer, account = setup_approved_customer_and_account()
        # Funds default to zero here (no INBOUND ACAT was run).
        assert account["cash_balance_cents"] == 0
        assert account["equity_value_cents"] == 0
        resp = api.close_account(
            account["id"], make_customer_headers(customer["id"]),
        )
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"
        assert closed["trading_posture"] == "RESTRICTED"

    def test_close_blocked_by_open_working_order(self, api):
        """PRD §3.6: "there must be no Order whose status is in
        ACCEPTED or WORKING ... Any unsettled dependency surfaces as
        ERR_ACCOUNT_HAS_DEPENDENCIES at HTTP 409."

        Claim: close attempted while a WORKING Order exists ->
        ERR_ACCOUNT_HAS_DEPENDENCIES / 409.
        """
        customer, account, order = (
            setup_account_with_working_limit_order(
                account_type="CASH", cash_amount_cents=10_000_000,
            )
        )
        assert order["status"] == "WORKING"
        resp = api.close_account(
            account["id"], make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_ACCOUNT_HAS_DEPENDENCIES.value,
        )

    def test_close_blocked_by_initiated_acat_transfer(self, api):
        """PRD §3.6: "no ACATTransfer whose status is in INITIATED,
        VALIDATED, or IN_TRANSIT for this account ... Any unsettled
        dependency surfaces as ERR_ACCOUNT_HAS_DEPENDENCIES at HTTP
        409."

        Claim: close attempted while an INITIATED OUTBOUND ACATTransfer
        exists -> ERR_ACCOUNT_HAS_DEPENDENCIES / 409.
        """
        customer, account, transfer = (
            setup_account_with_outbound_acat_initiated()
        )
        assert transfer["status"] == "INITIATED"
        resp = api.close_account(
            account["id"], make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_ACCOUNT_HAS_DEPENDENCIES.value,
        )

    def test_close_blocked_by_nonzero_cash_balance(self, api):
        """PRD §3.6: "Account.cash_balance_cents must equal 0 and
        Account.equity_value_cents must equal 0. Any unsettled
        dependency surfaces as ERR_ACCOUNT_HAS_DEPENDENCIES at HTTP
        409."

        Claim: close attempted while cash_balance_cents > 0 (after
        INBOUND ACAT completion) -> ERR_ACCOUNT_HAS_DEPENDENCIES / 409.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=1_000_000,
        )
        assert account["cash_balance_cents"] > 0
        resp = api.close_account(
            account["id"], make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_ACCOUNT_HAS_DEPENDENCIES.value,
        )
