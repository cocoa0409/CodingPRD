"""Rebalance run state machine and Form 1099-B lifecycle.

Coverage targets (PRD §3.8, §3.11):
- One run per (account_id, quarter_key) non-FAILED.
- Form1099B uniqueness per (client_id, tax_year).
- Issue precondition: no non-terminal SELL Trades for the year.
"""
from __future__ import annotations

import pytest
from datetime import date

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    buy_and_settle,
    create_form_1099b,
    create_form_1099b_payload,
    create_security,
    create_trade,
    execute_trade,
    quarter_key_of,
    setup_account_with_drift,
    setup_active_client_with_account,
    suspend_client,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rebalance uniqueness — PRD §3.8
# ===========================================================================
class TestRebalanceUniqueness:

    def test_duplicate_run_same_quarter_rejected(self, api):
        """PRD §3.8: "only one run may exist per (account_id,
        quarter_key) pair whose status is anything other than FAILED;
        ... Violating any of those preconditions surfaces as
        ERR_REBALANCE_ALREADY_IN_PROGRESS".

        Claim: starting a second rebalance for the same (account,
        quarter_key) -> ERR_REBALANCE_ALREADY_IN_PROGRESS.
        """
        scenario = setup_account_with_drift(target_drift_pct=5.50)
        account = scenario["account"]
        qk = quarter_key_of(date.today())
        # First start.
        resp1 = api.start_rebalance(
            account["id"], {"quarter_key": qk},
            TEST_USERS["advisor_headers"],
        )
        validate_success(resp1, expected_status=201)
        # Second start, same (account, qk).
        resp2 = api.start_rebalance(
            account["id"], {"quarter_key": qk},
            TEST_USERS["advisor_headers"],
        )
        validate_error(
            resp2, ApiErrorId.ERR_REBALANCE_ALREADY_IN_PROGRESS.value,
        )


# ===========================================================================
# Form 1099-B uniqueness — PRD §3.11
# ===========================================================================
class TestForm1099BUniqueness:

    def test_duplicate_form_for_same_year_rejected(self, api):
        """PRD §3.11: "Only one form may exist per (client_id,
        tax_year) pair; a duplicate create surfaces as
        ERR_FORM_ALREADY_EXISTS (HTTP 409)".

        Claim: second POST /clients/{id}/forms-1099b for the same
        (client, tax_year) -> ERR_FORM_ALREADY_EXISTS.
        """
        client, _ = setup_active_client_with_account()
        create_form_1099b(client, 2025)
        resp = api.create_form_1099b(
            client["id"], create_form_1099b_payload(tax_year=2025),
            TEST_USERS["tax_admin_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_FORM_ALREADY_EXISTS.value,
        )


# ===========================================================================
# Form 1099-B issuance precondition — PRD §3.11
# ===========================================================================
class TestForm1099BIssuance:

    def test_issue_blocked_by_open_sell_trade(self, api):
        """PRD §3.11: "Issuance requires the client's kyc_status to
        be ACTIVE ... and zero SELL trades for the client in the
        named tax year remaining non-terminal — every such trade
        must already be SETTLED, CANCELLED, or REJECTED. When any
        sell is still PENDING or EXECUTED, issuance is rejected with
        ERR_OPEN_TRADES_FOR_TAX_YEAR."

        Claim: with one SELL in EXECUTED (non-terminal) for tax_year
        2025, POST issue -> ERR_OPEN_TRADES_FOR_TAX_YEAR.
        """
        client, account = setup_active_client_with_account()
        security = create_security(last_price_cents=10_000)
        # Build a SETTLED BUY so we have a position to SELL out of.
        buy_and_settle(account, security, 10)
        # Create a SELL trade and only execute (not settle) so it's
        # in EXECUTED (non-terminal).
        sell = create_trade(
            account, security, side="SELL", requested_shares=5,
            cost_basis_method="FIFO",
        )
        execute_trade(account, sell)
        # Create a Form and try to issue it. PRD §3.11 says executed
        # year is derived from Trade.executed_at; since we just
        # executed, the year is current.
        form = create_form_1099b(
            client, date.today().year,
        )
        resp = api.issue_form_1099b(
            client["id"], form["id"],
            TEST_USERS["tax_admin_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_OPEN_TRADES_FOR_TAX_YEAR.value,
        )

    def test_issue_blocked_when_client_suspended(self, api):
        """PRD §3.11: "Issuance requires the client's kyc_status to
        be ACTIVE (a SUSPENDED client cannot have a form issued; the
        cross-entity precondition surfaces as ERR_INVALID_STATE)".

        Claim: with the client SUSPENDED, POST issue ->
        ERR_INVALID_STATE.
        """
        client, _ = setup_active_client_with_account()
        form = create_form_1099b(client, date.today().year)
        suspend_client(client)
        resp = api.issue_form_1099b(
            client["id"], form["id"],
            TEST_USERS["tax_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
