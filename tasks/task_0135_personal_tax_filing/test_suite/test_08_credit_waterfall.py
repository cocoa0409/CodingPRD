"""Credit waterfall — CTC / AOTC / EITC and balance reconciliation.

Coverage targets (PRD §3.6, §3.7):
- Compute evaluates eligibility (PENDING -> ELIGIBLE/INELIGIBLE).
- CTC phase-out rounds AGI excess UP to next $1000 before 5% rate.
- Refundable cap per child = $1,700 cents.
- EITC phase-out cliff at end.
- Balance reconciliation: balance = payments - net_tax.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    add_credit,
    advance_clock_to,
    compute_tax_return,
    create_taxpayer,
    iso_date,
    iso_instant_utc,
    make_taxpayer_headers,
    re_get_tax_return,
    schedule_payment,
    setup_simple_w2_return,
)


# ===========================================================================
# Eligibility evaluation — PRD §3.4 / §3.6
# ===========================================================================
class TestEligibilityOnCompute:

    def test_compute_sets_credit_eligibility_to_eligible(self, api):
        """PRD §3.4: "Computing the return - see §3.5 and §3.6 - sets
        eligibility_status to either ELIGIBLE (with a computed approved
        amount and refundable portion) or INELIGIBLE (with a short
        ineligibility_reason explaining why and zeros for the amounts)."

        Claim: a CTC row that should be eligible reports
        eligibility_status=ELIGIBLE post-compute with a positive
        approved amount.
        """
        # SINGLE with 1 qualifying child, AGI well below phase-out.
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=3_000_000, federal_withholding_cents=0,
            filing_status="SINGLE",
            dependents_count=1, qualifying_children_under_17=1,
        )
        credit = add_credit(
            taxpayer, tax_return["id"],
            credit_type="CTC", requested_amount_cents=200_000,
        )
        assert credit["eligibility_status"] == "PENDING"
        compute_tax_return(taxpayer, tax_return["id"])
        # Re-read credit.
        listed = api.list_credits(
            tax_return["id"], make_taxpayer_headers(taxpayer["id"]),
        ).json()["data"]
        row = next(r for r in listed if r["id"] == credit["id"])
        assert row["eligibility_status"] == "ELIGIBLE"
        # PRD §3.6 CTC = 1 * 200_000 = 200_000; AGI well below phase-out.
        assert row["approved_amount_cents"] == 200_000
        # Refundable portion = min(200_000, 1 * 170_000) = 170_000.
        assert row["refundable_portion_cents"] == 170_000


# ===========================================================================
# Balance due / refund — PRD §3.7
# ===========================================================================
class TestBalance:

    def test_refund_when_withholding_exceeds_tax(self, api):
        """PRD §3.7: "balance_due_or_refund_cents is the payments
        total minus the net tax; a positive value is a refund owed
        to the taxpayer".

        Claim: wages=2_500_000 SINGLE STANDARD; withholding=500_000;
        no credits -> taxable=1_000_000, regular_tax=100_000,
        amt=0, balance = 500_000 - 100_000 = +400_000 (refund).
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=2_500_000, federal_withholding_cents=500_000,
            filing_status="SINGLE",
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["total_withholding_cents"] == 500_000
        assert computed["regular_tax_cents"] == 100_000
        assert computed["amt_cents"] == 0
        # No credits -> net_tax = 100_000.
        assert computed["balance_due_or_refund_cents"] == 400_000

    def test_balance_due_when_tax_exceeds_payments(self, api):
        """PRD §3.7: "a negative value is a balance due to the IRS".

        Claim: wages=2_500_000 SINGLE STANDARD; withholding=0 -> net
        tax=100_000, balance = 0 - 100_000 = -100_000.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=2_500_000, federal_withholding_cents=0,
            filing_status="SINGLE",
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["balance_due_or_refund_cents"] == -100_000


# ===========================================================================
# Confirmed payments contribute to balance — PRD §3.7
# ===========================================================================
class TestConfirmedPaymentsInBalance:

    def test_confirmed_payment_increases_payments_total(self, api):
        """PRD §3.7: "It then totals estimated_payments_applied_cents
        as the sum of amount_cents across every EstimatedTaxPayment
        belonging to the same taxpayer and tax year whose status is
        CONFIRMED."

        Claim: after a SCHEDULED payment auto-CONFIRMs (via clock
        advance), recomputing the return picks up that payment in
        estimated_payments_applied_cents.
        """
        # Start clock at known instant.
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=2_500_000, federal_withholding_cents=0,
            filing_status="SINGLE",
        )
        pay_date = iso_date(date(2026, 4, 15))
        payment = schedule_payment(
            taxpayer,
            tax_year=tax_return["tax_year"], quarter="Q1",
            amount_cents=50_000,
            scheduled_pay_date=pay_date,
        )
        assert payment["status"] == "SCHEDULED"
        # Advance clock past pay-date.
        advance_clock_to(iso_instant_utc(2026, 4, 15, 0, 0, 0))
        # Compute the return -- estimated_payments_applied_cents should
        # now include the 50_000 from the confirmed payment.
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["estimated_payments_applied_cents"] == 50_000
        # Balance = 0 (withholding) + 50_000 - 100_000 = -50_000.
        assert computed["balance_due_or_refund_cents"] == -50_000


# ===========================================================================
# total_credits_cents — PRD §3.6
# ===========================================================================
class TestTotalCreditsCents:

    def test_total_credits_cents_sums_approved(self, api):
        """PRD §3.6: "The total_credits_cents field on the return is
        the sum of every approved credit's approved amount on the
        return - refundable and non-refundable combined."

        Claim: with a single approved CTC of 200_000,
        total_credits_cents == 200_000.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=3_000_000, federal_withholding_cents=0,
            filing_status="SINGLE",
            dependents_count=1, qualifying_children_under_17=1,
        )
        add_credit(
            taxpayer, tax_return["id"],
            credit_type="CTC", requested_amount_cents=200_000,
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["total_credits_cents"] == 200_000
