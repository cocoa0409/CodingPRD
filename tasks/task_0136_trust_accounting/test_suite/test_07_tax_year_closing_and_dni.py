"""Tax-year closing cycle, DNI computation, trust_income_tax brackets,
K-1 issuance — PRD §3.5, §3.7, §3.8."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BRACKET_1_RATE,
    BRACKET_1_TOP,
    BRACKET_2_RATE,
    BRACKET_2_TOP,
    BRACKET_3_RATE,
    BRACKET_3_TOP,
    BRACKET_4_RATE,
    advance_clock_to,
    api_client,
    approve_distribution,
    assert_k1,
    assert_tax_year,
    begin_close_tax_year,
    book_transaction,
    execute_distribution,
    finalize_tax_year,
    iso_instant_utc,
    list_k1s_for_year,
    propose_distribution,
    re_get_trust,
    setup_active_trust,
    setup_active_trust_with_income,
    setup_closed_tax_year,
    validate_error,
    validate_success,
)


# ===========================================================================
# begin-close — PRD §3.5
# ===========================================================================
class TestBeginClose:

    def test_begin_close_blocked_before_year_end(
        self, api, tax_preparer_headers,
    ):
        """PRD §3.5: "The transition OPEN → CLOSING requires that the
        logical clock has reached at least the TaxYear's end_date;
        otherwise the request is rejected with
        ERR_TAX_YEAR_NOT_ENDED."

        Claim: begin-close while the clock is still inside the year
        -> ERR_TAX_YEAR_NOT_ENDED.

        To insulate this test from clock advances persisted by other
        tests (PRD §2.10: "The clock never moves backwards in normal
        operation"), the TaxYear is opened far enough in the future
        that no other test in this suite ever advances past it.
        """
        # Use a far-future inception year so the clock is guaranteed
        # to be below end_date even if prior tests advanced the
        # clock.
        scenario = setup_active_trust(
            inception_date="2099-01-01", calendar_year=2099,
        )
        resp = api.begin_close_tax_year(
            scenario.trust["id"], scenario.tax_year["id"],
            tax_preparer_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_TAX_YEAR_NOT_ENDED.value,
        )

    def test_begin_close_auto_rejects_proposed_distributions(
        self, api,
    ):
        """PRD §3.5: "As a side effect of beginning the close, every
        Distribution in PROPOSED status for this tax_year_id is
        automatically transitioned to REJECTED."

        Claim: a PROPOSED distribution becomes REJECTED after
        begin-close.
        """
        scenario = setup_active_trust_with_income(income_amount=1_000.00)
        dist = propose_distribution(
            scenario.trust, scenario.beneficiary,
            scenario.primary_trustee_headers,
            amount_income=100.00,
            distribution_type="DISCRETIONARY",
        )
        advance_clock_to(iso_instant_utc(2027, 1, 2))
        scenario.tax_year = begin_close_tax_year(
            scenario.trust, scenario.tax_year,
        )
        resp = api.get_distribution(
            scenario.trust["id"], dist["id"],
            scenario.primary_trustee_headers,
        )
        after = validate_success(resp, 200)
        assert after["status"] == "REJECTED", (
            f"PROPOSED distribution should be auto-rejected on "
            f"begin-close; got status={after['status']!r}"
        )

    def test_begin_close_blocked_when_approved_distributions_exist(
        self, api,
    ):
        """PRD §3.5: "It also requires that no Distribution belonging
        to this tax_year_id is in APPROVED status — the preparer must
        execute or reject every approved-but-unexecuted distribution
        before closing can start; otherwise
        ERR_HAS_APPROVED_DISTRIBUTIONS."

        Claim: begin-close with an APPROVED distribution still in the
        year -> ERR_HAS_APPROVED_DISTRIBUTIONS.
        """
        scenario = setup_active_trust_with_income(income_amount=5_000.00)
        dist = propose_distribution(
            scenario.trust, scenario.beneficiary,
            scenario.primary_trustee_headers,
            amount_income=500.00,
        )
        approve_distribution(
            scenario.trust, dist, scenario.second_trustee_headers,
        )
        advance_clock_to(iso_instant_utc(2027, 1, 2))
        from test_helpers import TEST_USERS
        resp = api.begin_close_tax_year(
            scenario.trust["id"], scenario.tax_year["id"],
            TEST_USERS["tax_preparer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_HAS_APPROVED_DISTRIBUTIONS.value,
        )


# ===========================================================================
# DNI computation — PRD §3.5
# ===========================================================================
class TestDniComputation:

    def test_dni_equals_gross_income_minus_expenses(self, api):
        """PRD §3.5: "The TaxYear's dni is the gross income minus the
        deductible expense, floored at zero (a negative net is
        recorded as 0.00 DNI rather than negative DNI), and the
        final result is rounded half-up to two decimal places."

        Claim: with $10,000 INCOME_ORDINARY and no expenses, DNI =
        10,000.00 after begin-close.
        """
        scenario = setup_active_trust_with_income(income_amount=10_000.00)
        advance_clock_to(iso_instant_utc(2027, 1, 2))
        scenario.tax_year = begin_close_tax_year(
            scenario.trust, scenario.tax_year,
        )
        assert_tax_year(scenario.tax_year)
        assert scenario.tax_year["dni"] == pytest.approx(
            10_000.00, abs=0.01,
        )

    def test_dni_floored_at_zero_for_negative_net(self, api):
        """PRD §3.5: "floored at zero (a negative net is recorded as
        0.00 DNI rather than negative DNI)".

        Claim: $100 of income + $300 of expense -> DNI = 0.00 (not
        -200).
        """
        scenario = setup_active_trust(calendar_year=2026)
        # Add some principal to absorb expenses, then book expense >
        # income.
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="INCOME_ORDINARY", amount=100.00,
            principal_or_income="INCOME",
            transaction_date=iso_instant_utc(2026, 6, 1),
        )
        # We need income_balance to cover the expense post-cascade;
        # the expense subtracts from income_balance, which can go
        # negative in the formula only on aggregation, not in
        # bookkeeping. Add a buffer.
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="INCOME_INTEREST", amount=500.00,
            principal_or_income="INCOME",
            transaction_date=iso_instant_utc(2026, 6, 2),
        )
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="EXPENSE_ADMINISTRATIVE", amount=800.00,
            principal_or_income="INCOME",
            transaction_date=iso_instant_utc(2026, 6, 3),
        )
        advance_clock_to(iso_instant_utc(2027, 1, 2))
        scenario.tax_year = begin_close_tax_year(
            scenario.trust, scenario.tax_year,
        )
        # gross_income = 100 + 500 = 600; expenses = 800;
        # 600 - 800 = -200 -> floored to 0.
        assert scenario.tax_year["dni"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# trust_taxable_income & trust_income_tax — PRD §3.8
# ===========================================================================
class TestTrustTaxableIncome:

    def test_grantor_variant_taxable_income_is_zero(self, api):
        """PRD §3.8: "Under the grantor variant ... the Trust's
        trust_taxable_income is forced to 0.00 regardless of dni,
        and the Trust's trust_income_tax is also 0.00."

        Claim: REVOCABLE+GRANTOR trust with $10,000 income produces
        trust_taxable_income=0.00 and trust_income_tax=0.00 at
        finalize.
        """
        scenario = setup_closed_tax_year(
            trust_type="REVOCABLE",
            grantor_tax_status="GRANTOR",
            income_amount=10_000.00,
        )
        assert scenario.tax_year["status"] == "CLOSED"
        assert scenario.tax_year["trust_taxable_income"] == (
            pytest.approx(0.00, abs=0.01)
        )
        assert scenario.tax_year["trust_income_tax"] == (
            pytest.approx(0.00, abs=0.01)
        )

    def test_non_grantor_variant_taxable_income_minus_distributions(
        self, api,
    ):
        """PRD §3.8: "The Trust's trust_taxable_income is then the
        TaxYear's dni minus that sum, floored at zero, rounded
        half-up to two decimal places."

        Claim: NON_GRANTOR trust with DNI=10,000 and $3,000 of
        executed income distribution -> trust_taxable_income =
        10,000 - 3,000 = 7,000.00.
        """
        scenario = setup_closed_tax_year(
            trust_type="IRREVOCABLE",
            grantor_tax_status="NON_GRANTOR",
            income_amount=10_000.00,
            distribution_income=3_000.00,
        )
        assert scenario.tax_year["status"] == "CLOSED"
        assert scenario.tax_year["trust_taxable_income"] == (
            pytest.approx(7_000.00, abs=0.01)
        )

    def test_trust_income_tax_at_band1_only(self, api):
        """PRD §3.8: "The first band covers taxable income from 0.00
        up to 3,100.00 at a marginal rate of 10%."

        Claim: NON_GRANTOR DNI=$3,100 no distributions -> taxable =
        $3,100 -> tax = 3,100 * 0.10 = 310.00.
        """
        scenario = setup_closed_tax_year(
            trust_type="IRREVOCABLE",
            grantor_tax_status="NON_GRANTOR",
            income_amount=3_100.00,
            distribution_income=0.0,
        )
        assert scenario.tax_year["trust_taxable_income"] == (
            pytest.approx(3_100.00, abs=0.01)
        )
        assert scenario.tax_year["trust_income_tax"] == (
            pytest.approx(310.00, abs=0.01)
        )

    def test_trust_income_tax_multi_band(self, api):
        """PRD §3.8: "The first band covers taxable income from 0.00
        up to 3,100.00 at a marginal rate of 10%. The second band
        covers the range above 3,100.00 up to 11,150.00 at 24%. The
        third band covers the range above 11,150.00 up to 15,200.00
        at 35%. The fourth band covers everything above 15,200.00 at
        37%."

        Claim: NON_GRANTOR DNI=$20,000, no distributions ->
        trust_taxable_income=20,000.00; tax =
        3100*0.10 + (11150-3100)*0.24 + (15200-11150)*0.35 +
        (20000-15200)*0.37 = 310 + 1932 + 1417.50 + 1776 = 5435.50.
        """
        scenario = setup_closed_tax_year(
            trust_type="IRREVOCABLE",
            grantor_tax_status="NON_GRANTOR",
            income_amount=20_000.00,
            distribution_income=0.0,
        )
        assert scenario.tax_year["trust_taxable_income"] == (
            pytest.approx(20_000.00, abs=0.01)
        )
        # Bracket arithmetic:
        #   3100 * 0.10 = 310
        #   (11150 - 3100) * 0.24 = 8050 * 0.24 = 1932
        #   (15200 - 11150) * 0.35 = 4050 * 0.35 = 1417.50
        #   (20000 - 15200) * 0.37 = 4800 * 0.37 = 1776
        #   total = 5435.50
        assert scenario.tax_year["trust_income_tax"] == (
            pytest.approx(5_435.50, abs=0.01)
        )


# ===========================================================================
# Finalize side effect on Trust.income_balance — PRD §3.5
# ===========================================================================
class TestFinalizeIncomeBalanceDebit:

    def test_finalize_debits_income_balance_by_trust_income_tax(
        self, api,
    ):
        """PRD §3.5: "The Trust's income_balance is then debited by
        the computed trust_income_tax".

        Claim: NON_GRANTOR with DNI = 10,000 (no distributions)
        debits income_balance by trust_income_tax. tax = 310 + 0.24
        * (10000 - 3100) = 310 + 1656 = 1966.00. So
        income_balance after = 10,000 - 1,966 = 8,034.00.
        """
        scenario = setup_closed_tax_year(
            trust_type="IRREVOCABLE",
            grantor_tax_status="NON_GRANTOR",
            income_amount=10_000.00,
            distribution_income=0.0,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        assert scenario.tax_year["trust_income_tax"] == (
            pytest.approx(1_966.00, abs=0.01)
        )
        assert scenario.trust["income_balance"] == pytest.approx(
            10_000.00 - 1_966.00, abs=0.01,
        )

    # NOTE on ERR_INSUFFICIENT_INCOME_FOR_TAX (PRD §3.5):
    # The error is unreachable through the PRD's in-year economics
    # without piling additional debits (GST tax payments, cross-year
    # prior debits) onto income_balance. The construction is
    # multi-fixture and the precise tax-vs-balance arithmetic is
    # PRD-derivable but fragile across implementations. Skipped under
    # the error-precedence silence pattern; the catalog entry is
    # covered by the §5 error table existence test elsewhere.
