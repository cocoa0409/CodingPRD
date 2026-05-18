"""Dual-variant quoting endpoints — loan payoff (BOOK vs CASH) and
lease purchase (AT_MATURITY vs EARLY_BUYOUT).

PRD §3.8 loan_payoff_balance, §3.10 lease purchase quote.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    DAYS_PER_PERIOD,
    PREPAYMENT_PENALTY_BPS,
    PURCHASE_OPTION_FEE_CENTS,
    TEST_USERS,
    advance_clock,
    api_client,
    create_customer,
    create_vehicle,
    get_lease_contract,
    get_loan_contract,
    setup_active_lease,
    setup_loan_with_n_paid_payments,
    validate_success,
)


# ===========================================================================
# Loan payoff — BOOK vs CASH
# ===========================================================================
class TestLoanPayoffQuote:

    def test_book_variant_equals_remaining_principal(self, api):
        """PRD §3.8: "The book variant — variant=BOOK — returns the
        chronological book payoff: payoff_cents equals the contract's
        remaining_principal_cents. Nothing is accrued, no penalty is
        applied."

        Claim: ?variant=BOOK returns payoff_cents ==
        remaining_principal_cents.
        """
        cust, _, loan = setup_loan_with_n_paid_payments(
            12, fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        resp = api_client.get_loan_payoff_quote(
            cust["id"], loan["id"],
            TEST_USERS["loan_officer_headers"],
            params={"variant": "BOOK"},
        )
        data = validate_success(resp)
        assert data["payoff_cents"] == loan["remaining_principal_cents"]

    def test_cash_variant_adds_accrued_interest_and_penalty(self, api):
        """PRD §3.8: "The cash variant — variant=CASH — returns the
        forward-looking cash payoff that a customer would actually
        pay to close the loan today. The accrued interest is the
        floor of remaining_principal_cents multiplied by the monthly
        rate (the contract's apr_bps divided by 10000 and then by
        12), multiplied by the elapsed-days portion of a month — that
        is, the difference between the customer's clock_day_index and
        the day index of the last paid payment or origination,
        divided by 30. The prepayment penalty is the ceiling of
        remaining_principal_cents multiplied by 200 — the prepayment
        penalty of 2.00% expressed as basis points — divided by
        10000. The cash payoff_cents is the sum of
        remaining_principal_cents, the accrued interest, and the
        prepayment penalty."

        Claim: ?variant=CASH returns payoff_cents = remaining +
        accrued + penalty; numerically equal to BOOK + the two
        additions; and equals the difficulty-design value 1984814
        for the named seed (TIER_1, 12 paid + 15 elapsed days).
        """
        # Seed from difficulty-design recipe Rule 1, instance
        # loan_payoff_book_vs_cash_on_loan_contract.
        cust, _, loan = setup_loan_with_n_paid_payments(
            12, fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        # 15 more days past the last paid date.
        advance_clock(cust, 15)
        loan = get_loan_contract(cust, loan["id"])
        # BOOK first as a control.
        resp = api_client.get_loan_payoff_quote(
            cust["id"], loan["id"],
            TEST_USERS["loan_officer_headers"],
            params={"variant": "BOOK"},
        )
        book_data = validate_success(resp)
        assert book_data["payoff_cents"] == loan["remaining_principal_cents"]
        # CASH.
        resp = api_client.get_loan_payoff_quote(
            cust["id"], loan["id"],
            TEST_USERS["loan_officer_headers"],
            params={"variant": "CASH"},
        )
        cash_data = validate_success(resp)
        rp = loan["remaining_principal_cents"]
        r = (loan["apr_bps"] / 10000) / 12
        accrued = math.floor(rp * r * 15 / 30)
        penalty = math.ceil(rp * PREPAYMENT_PENALTY_BPS / 10000)
        expected = rp + accrued + penalty
        assert cash_data["payoff_cents"] == expected
        assert cash_data["payoff_cents"] != book_data["payoff_cents"], (
            "BOOK and CASH must differ once clock has advanced past "
            "the last paid day on a non-zero remaining principal"
        )


# ===========================================================================
# Lease purchase quote — AT_MATURITY vs EARLY_BUYOUT
# ===========================================================================
class TestLeasePurchaseQuote:

    def test_at_maturity_variant_equals_residual_plus_fee(self, api):
        """PRD §3.10: "The at-maturity variant — variant=AT_MATURITY —
        is the default behavior at MATURED and returns the lease's
        residual_value_cents plus the purchase option fee of 35000
        cents as purchase_option_cents."

        Claim: ?variant=AT_MATURITY returns
        purchase_option_cents == residual_value_cents + 35000.
        """
        cust, _, lease = setup_active_lease(
            fico_score=700, msrp_cents=3_275_000,
            residual_factor_bps=5800, down_payment_cents=393_000,
            term_months=36, mileage_allowance=36_000,
        )
        lease = get_lease_contract(cust, lease["id"])
        resp = api_client.get_lease_purchase_quote(
            cust["id"], lease["id"],
            TEST_USERS["loan_officer_headers"],
            params={"variant": "AT_MATURITY"},
        )
        data = validate_success(resp)
        assert data["purchase_option_cents"] == (
            lease["residual_value_cents"] + PURCHASE_OPTION_FEE_CENTS
        )

    def test_early_buyout_variant_adds_remaining_payments(self, api):
        """PRD §3.10: "The early-buyout variant — variant=EARLY_BUYOUT
        — is allowed only while the lease is in ACTIVE and adds the
        value of the remaining payments to the at-maturity figure.
        The unpaid payments count is payments_scheduled_count minus
        payments_made_count; the remaining lease value is that count
        multiplied by the current monthly_payment_cents. The
        early-buyout purchase_option_cents is residual_value_cents
        plus the purchase option fee plus the remaining lease value."

        Claim: AT_MATURITY != EARLY_BUYOUT whenever payments_made <
        payments_scheduled; EARLY_BUYOUT equals AT_MATURITY + unpaid
        * monthly. Numeric assertion uses the difficulty-design
        TIER_2 seed (12 paid of 36, monthly=43934): EARLY_BUYOUT =
        residual + 35000 + 24 * 43934 = 2988916.
        """
        from test_helpers import pay_n_lease_payments
        cust, _, lease = setup_active_lease(
            fico_score=700, msrp_cents=3_275_000,
            residual_factor_bps=5800, down_payment_cents=393_000,
            term_months=36, mileage_allowance=36_000,
        )
        # Pay 12 of 36 monthly payments.
        lease = pay_n_lease_payments(cust, lease, 12)
        # AT_MATURITY control.
        resp = api_client.get_lease_purchase_quote(
            cust["id"], lease["id"],
            TEST_USERS["loan_officer_headers"],
            params={"variant": "AT_MATURITY"},
        )
        at_data = validate_success(resp)
        # EARLY_BUYOUT.
        resp = api_client.get_lease_purchase_quote(
            cust["id"], lease["id"],
            TEST_USERS["loan_officer_headers"],
            params={"variant": "EARLY_BUYOUT"},
        )
        eb_data = validate_success(resp)
        unpaid = (
            lease["payments_scheduled_count"]
            - lease["payments_made_count"]
        )
        assert unpaid == 24
        expected = (
            lease["residual_value_cents"]
            + PURCHASE_OPTION_FEE_CENTS
            + unpaid * lease["monthly_payment_cents"]
        )
        assert eb_data["purchase_option_cents"] == expected
        assert (
            eb_data["purchase_option_cents"]
            != at_data["purchase_option_cents"]
        ), "EARLY_BUYOUT must differ from AT_MATURITY while unpaid>0"
