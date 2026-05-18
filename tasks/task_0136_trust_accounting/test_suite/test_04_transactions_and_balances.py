"""Transactions and Trust balance recomputation — PRD §3.3, §3.9."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_transaction,
    book_transaction,
    create_transaction_payload,
    iso_instant_utc,
    re_get_trust,
    setup_active_trust,
    setup_active_trust_with_income,
    setup_closed_tax_year,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Append-only contract — PRD §2.4 / §3.3
# ===========================================================================
class TestTransactionAppendOnly:

    def test_transaction_omits_updated_at_and_version(self, api):
        """PRD §2.4: "the Transaction resource is an append-only
        event-log record that carries only id and created_at; it has
        no updated_at and no version, because a booked transaction
        is never edited in place".

        Claim: returned Transaction omits updated_at and version.
        """
        scenario = setup_active_trust()
        resp = api.create_transaction(
            scenario.trust["id"],
            create_transaction_payload(
                txn_type="INCOME_ORDINARY",
                amount=100.00,
                principal_or_income="INCOME",
                transaction_date=iso_instant_utc(2026, 6, 1),
            ),
            scenario.primary_trustee_headers,
        )
        txn = validate_success(resp, 201)
        assert_transaction(txn)
        assert "updated_at" not in txn or txn.get("updated_at") is None
        assert "version" not in txn or txn.get("version") is None


# ===========================================================================
# Tax-year resolution — PRD §3.3
# ===========================================================================
class TestTransactionTaxYearResolution:

    def test_transaction_pins_tax_year_id_from_date(self, api):
        """PRD §3.3: "The Transaction record carries a trust_id and,
        populated by the server at booking time, a tax_year_id
        resolved by mapping transaction_date to the TaxYear whose
        calendar year contains it."

        Claim: a 2026 transaction is pinned to the 2026 TaxYear.
        """
        scenario = setup_active_trust(calendar_year=2026)
        txn = book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="INCOME_ORDINARY", amount=500.00,
            transaction_date=iso_instant_utc(2026, 7, 15),
            principal_or_income="INCOME",
        )
        assert txn["tax_year_id"] == scenario.tax_year["id"]

    def test_transaction_outside_open_tax_year_rejected(self, api):
        """PRD §3.3: "A Transaction's transaction_date must fall
        inside a TaxYear that is in either OPEN or CLOSING status for
        this trust; otherwise the request is rejected with
        ERR_TAX_YEAR_CLOSED."

        Claim: transaction in a calendar year for which no TaxYear is
        OPEN/CLOSING -> ERR_TAX_YEAR_CLOSED.
        """
        scenario = setup_active_trust(calendar_year=2026)
        # No 2027 TaxYear opened — date falls outside any open year.
        resp = api.create_transaction(
            scenario.trust["id"],
            create_transaction_payload(
                txn_type="INCOME_ORDINARY", amount=10.00,
                transaction_date=iso_instant_utc(2027, 6, 1),
                principal_or_income="INCOME",
            ),
            scenario.primary_trustee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TAX_YEAR_CLOSED.value)


# ===========================================================================
# Balance recomputation — PRD §3.3 / §3.9
# ===========================================================================
class TestBalanceCascade:

    def test_income_transaction_increases_income_balance(self, api):
        """PRD §3.3: "Booking a Transaction triggers a balance
        recomputation cascade on the parent Trust — depending on
        principal_or_income, either principal_balance or
        income_balance is updated, the Trust's version and updated_at
        are refreshed".

        Claim: INCOME_ORDINARY booked under principal_or_income=INCOME
        adds Transaction.amount to Trust.income_balance and bumps the
        Trust's version.
        """
        scenario = setup_active_trust()
        before_income = scenario.trust["income_balance"]
        before_version = scenario.trust["version"]
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="INCOME_ORDINARY", amount=750.00,
            transaction_date=iso_instant_utc(2026, 5, 1),
            principal_or_income="INCOME",
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        assert scenario.trust["income_balance"] == pytest.approx(
            before_income + 750.00, abs=0.01,
        )
        assert scenario.trust["version"] > before_version

    def test_expense_transaction_decreases_balance(self, api):
        """PRD §3.3: "the sign is implied by txn_type (income types
        add, expense types subtract)".

        Claim: EXPENSE_ADMINISTRATIVE on principal_or_income=INCOME
        subtracts amount from income_balance.
        """
        scenario = setup_active_trust_with_income(income_amount=1_000.00)
        before_income = scenario.trust["income_balance"]
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="EXPENSE_ADMINISTRATIVE", amount=100.00,
            transaction_date=iso_instant_utc(2026, 5, 2),
            principal_or_income="INCOME",
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        assert scenario.trust["income_balance"] == pytest.approx(
            before_income - 100.00, abs=0.01,
        )


# ===========================================================================
# Listing transactions — PRD §3.3
# ===========================================================================
class TestTransactionListing:

    def test_list_transactions_pagination_envelope(self, api):
        """PRD §3.3: "Transactions may be listed under a Trust with
        optional filters tax_year_id, txn_type, from, and to (the
        last two delimiting a date range), with the standard limit
        and offset pagination parameters."

        Claim: list endpoint returns a paginated envelope.
        """
        scenario = setup_active_trust_with_income(
            income_amount=100.00,
        )
        # Book another transaction.
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="INCOME_INTEREST", amount=200.00,
            transaction_date=iso_instant_utc(2026, 6, 2),
            principal_or_income="INCOME",
        )
        resp = api.list_transactions(
            scenario.trust["id"], scenario.primary_trustee_headers,
        )
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert "total_count" in meta
