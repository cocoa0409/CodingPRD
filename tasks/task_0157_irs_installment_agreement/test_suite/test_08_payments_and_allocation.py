"""Payment allocation waterfall and overpayment handling. PRD §3.5.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_allocation_sums_to,
    create_and_activate_agreement,
    create_taxpayer,
    create_tax_liability,
    get_tax_liability,
    make_taxpayer_headers,
    record_installment_payment,
    record_installment_payment_payload,
    validate_error,
    validate_success,
)


class TestWaterfallAllocation:

    def test_waterfall_csed_soonest_first(self, api):
        """PRD §3.5: "The server first sorts the targets by
        csed_effective_date ascending (so that liabilities whose
        statutory window closes soonest are paid first, which preserves
        revenue)."

        Claim: a $5,000 payment across two liabilities ($4,000 and
        $6,000) sorted by csed-soonest pays $4,000 to the early-CSED
        one fully and the $1,000 remainder to the later-CSED one.
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        # L_a: assessment 2018-01-01 -> csed 2028-01-01 (sooner)
        # L_b: assessment 2020-01-01 -> csed 2030-01-01 (later)
        liab_a = create_tax_liability(
            taxpayer["id"],
            assessment_date="2018-01-01T00:00:00.000Z",
            tax_year=2017,
            original_assessed_amount_cents=400_000,
        )
        liab_b = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            tax_year=2019,
            original_assessed_amount_cents=600_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liab_a["id"], liab_b["id"]],
            proposed_monthly_payment_cents=500_000,
            payment_method="CHECK",
        )
        payment = record_installment_payment(
            agreement["id"], amount_cents=500_000,
            received_at="2020-02-01T00:00:00.000Z",
        )
        # Allocation sums.
        assert_allocation_sums_to(payment, 500_000)
        rows = {r["liability_id"]: r["applied_cents"]
                for r in payment["allocation"]}
        assert rows[liab_a["id"]] == 400_000, (
            "PRD §3.5: csed-soonest is paid first, so liab_a (CSED 2028) "
            "absorbs its full 400_000 balance"
        )
        assert rows[liab_b["id"]] == 100_000, (
            "remaining 100_000 lands on liab_b (CSED 2030)"
        )

    def test_overpayment_on_installment_rejected(self, api):
        """PRD §3.5: "For an INSTALLMENT or OIC_INSTALLMENT payment,
        any surplus remaining after every targeted liability has been
        settled is rejected with ERR_OVERPAYMENT."

        Claim: payment amount > total covered balance →
        ERR_OVERPAYMENT.

        # difficulty: compensating_invariant/payment_allocation_total_invariant
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liab_a = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=400_000,
        )
        liab_b = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=600_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liab_a["id"], liab_b["id"]],
            proposed_monthly_payment_cents=1_500_000,
            payment_method="CHECK",
        )
        # Pay 500_000 once (legitimate).
        record_installment_payment(
            agreement["id"], amount_cents=500_000,
            received_at="2020-02-01T00:00:00.000Z",
        )
        # Now over-pay: remaining 500_000 + 500_000 surplus.
        resp = api.record_installment_payment(
            agreement["id"],
            record_installment_payment_payload(
                amount_cents=1_000_000,
                received_at="2020-03-01T00:00:00.000Z",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        # ownership: actor is IRSOfficer; rebuild with IRSOfficer headers.
        from test_helpers import TEST_USERS
        resp = api.record_installment_payment(
            agreement["id"],
            record_installment_payment_payload(
                amount_cents=1_000_000,
                received_at="2020-03-01T00:00:00.000Z",
            ),
            TEST_USERS["irs_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)


class TestAllocationConservation:

    def test_payment_allocation_sums_to_amount_cents(self, api):
        """PRD §3.5: "an array of { liability_id, applied_cents } rows
        whose applied_cents values sum exactly to amount_cents."

        Claim: SUM(applied_cents) == amount_cents on a multi-liability
        installment payment.

        # difficulty: compensating_invariant/payment_allocation_total_invariant
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liab_a = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=400_000,
        )
        liab_b = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=600_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liab_a["id"], liab_b["id"]],
            proposed_monthly_payment_cents=1_500_000,
            payment_method="CHECK",
        )
        payment = record_installment_payment(
            agreement["id"], amount_cents=500_000,
            received_at="2020-02-01T00:00:00.000Z",
        )
        assert_allocation_sums_to(payment, 500_000)

    def test_failed_payment_leaves_payments_applied_unchanged(self, api):
        """PRD §3.5: applied amounts derive only from successful
        allocations.

        PRD §3.5 + PRD §3.4 read together: "Recording an installment
        receipt ... allocates the payment across the agreement's
        covered liabilities ... An installment-kind payment whose
        amount_cents would exceed the sum of current_balance_cents over
        the targeted liabilities is rejected with ERR_OVERPAYMENT."

        Claim: when the second payment is rejected, the per-liability
        payments_applied_cents are unchanged from the first payment's
        outcome (compensating invariant).

        # difficulty: compensating_invariant/payment_allocation_total_invariant
        """
        from test_helpers import TEST_USERS
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liab_a = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=400_000,
        )
        liab_b = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=600_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liab_a["id"], liab_b["id"]],
            proposed_monthly_payment_cents=1_500_000,
            payment_method="CHECK",
        )
        record_installment_payment(
            agreement["id"], amount_cents=500_000,
            received_at="2020-02-01T00:00:00.000Z",
        )
        before_a = get_tax_liability(liab_a["id"])["payments_applied_cents"]
        before_b = get_tax_liability(liab_b["id"])["payments_applied_cents"]
        sum_before = before_a + before_b
        assert sum_before == 500_000, "first payment allocated fully"
        # Over-pay attempt (1_000_000 vs remaining 500_000) — must fail.
        resp = api.record_installment_payment(
            agreement["id"],
            record_installment_payment_payload(
                amount_cents=1_000_000,
                received_at="2020-03-01T00:00:00.000Z",
            ),
            TEST_USERS["irs_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)
        # Compensating invariant: payments_applied_cents unchanged.
        after_a = get_tax_liability(liab_a["id"])["payments_applied_cents"]
        after_b = get_tax_liability(liab_b["id"])["payments_applied_cents"]
        assert after_a == before_a and after_b == before_b, (
            "PRD §3.5 invariant: a rejected payment must not mutate "
            "per-liability payments_applied_cents"
        )
