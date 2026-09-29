"""Billing determinants under the estimated and the actual true-up treatments."""

from test_helpers import (
    adjust_invoice,
    assert_agreement_state,
    assert_invoice_determinants,
    create_invoice,
    hospital_billing_stack,
    issue_invoice,
    read_agreement,
    read_invoice,
)

JUNE_START = "2026-06-01T00:00:00Z"
JUNE_END = "2026-07-01T00:00:00Z"


class TestEstimatedVariant:
    """The estimated treatment admits every read and ignores the ratchet."""

    def test_estimated_billing_admits_both_read_types_and_floors_on_reserved_capacity(self):
        """Three June reads, one of them estimated, give a 900.250 MWh consumption.

        PRD: "The `ESTIMATED` variant admits reads of either `read_type`, both
        `ACTUAL` and `ESTIMATED`, and treats the agreement's
        `billed_demand_ratchet_kw` as 0.0 so that the demand determinant floors on
        the reserved capacity alone."

        Design: Difficulty/dual_variant_calc/invoice_estimated_vs_actual_true_up_variant_reconciliation
        """
        stack = hospital_billing_stack()

        invoice = create_invoice(
            stack["agreement"]["id"], JUNE_START, JUNE_END, "ESTIMATED"
        )

        assert_invoice_determinants(
            invoice,
            billed_energy_mwh=900.250,
            billed_demand_kw=3100.00,
            load_factor_pct=40.33,
            energy_charge=70669.63,
            demand_charge=44950.00,
            fixed_charge=1200.00,
            total_amount=116819.63,
            minimum_bill_applied=False,
            variant_applied="ESTIMATED",
            invoice_state="DRAFT",
        )

    def test_issuing_the_estimated_invoice_raises_the_ratchet_and_the_balance(self):
        """Issue is the one edge that moves the demand ratchet upward.

        PRD: "it raises the agreement's `billed_demand_ratchet_kw` to this
        invoice's `billed_demand_kw` when the invoice's figure is higher — the
        ratchet is only ever raised, never lowered, and only on this one edge".

        Design: Difficulty/dual_variant_calc/invoice_estimated_vs_actual_true_up_variant_reconciliation
        """
        stack = hospital_billing_stack()
        invoice = create_invoice(
            stack["agreement"]["id"], JUNE_START, JUNE_END, "ESTIMATED"
        )

        issued = issue_invoice(invoice["id"])

        assert_invoice_determinants(issued, invoice_state="ISSUED", total_amount=116819.63)
        assert_agreement_state(
            read_agreement(stack["agreement"]["id"]),
            billing_state="IN_ARREARS",
            balance_due=116819.63,
            billed_demand_ratchet_kw=3100.00,
        )


class TestActualTrueUpVariant:
    """The true-up treatment drops the estimated read and applies the ratchet."""

    def test_adjusting_to_the_true_up_variant_recomputes_from_actual_reads_only(self):
        """Dropping the estimated closing read halves the billable consumption.

        PRD: "The `ACTUAL_TRUE_UP` variant admits only reads whose `read_type` is
        `ACTUAL`, and applies the agreement's stored `billed_demand_ratchet_kw` as
        a third floor on billed demand."

        Design: Difficulty/dual_variant_calc/invoice_estimated_vs_actual_true_up_variant_reconciliation
        """
        stack = hospital_billing_stack()
        invoice = create_invoice(
            stack["agreement"]["id"], JUNE_START, JUNE_END, "ESTIMATED"
        )
        issue_invoice(invoice["id"])

        adjusted = adjust_invoice(invoice["id"], "ACTUAL_TRUE_UP")

        assert_invoice_determinants(
            adjusted,
            billed_energy_mwh=420.500,
            billed_demand_kw=3100.00,
            load_factor_pct=18.84,
            energy_charge=38686.00,
            demand_charge=44950.00,
            fixed_charge=1200.00,
            total_amount=84836.00,
            minimum_bill_applied=False,
            variant_applied="ACTUAL_TRUE_UP",
            invoice_state="ADJUSTED",
        )

    def test_the_lower_load_factor_selects_the_cheapest_tier_ceiling(self):
        """A load factor of 18.84 falls under the first tier ceiling of 30.

        PRD: "The tier applied is the first entry of the tariff's `tiers`, walked
        in `load_factor_max` ascending order, whose `load_factor_max` is greater
        than or equal to `load_factor_pct`".

        Design: Difficulty/dual_variant_calc/invoice_estimated_vs_actual_true_up_variant_reconciliation
        """
        stack = hospital_billing_stack()
        invoice = create_invoice(
            stack["agreement"]["id"], JUNE_START, JUNE_END, "ESTIMATED"
        )
        issue_invoice(invoice["id"])

        adjusted = adjust_invoice(invoice["id"], "ACTUAL_TRUE_UP")

        # 420.500 MWh at the 92.00 first-tier rate, not the 78.50 middle tier.
        assert_invoice_determinants(adjusted, energy_charge=38686.00)

    def test_the_adjustment_reprices_the_balance_but_leaves_the_ratchet_alone(self):
        """The balance falls to the adjusted total while the ratchet holds at 3100.

        PRD: "Adjustment does **not** touch the ratchet."

        Design: Difficulty/dual_variant_calc/invoice_estimated_vs_actual_true_up_variant_reconciliation
        """
        stack = hospital_billing_stack()
        invoice = create_invoice(
            stack["agreement"]["id"], JUNE_START, JUNE_END, "ESTIMATED"
        )
        issue_invoice(invoice["id"])

        adjust_invoice(invoice["id"], "ACTUAL_TRUE_UP")

        assert_agreement_state(
            read_agreement(stack["agreement"]["id"]),
            contract_state="ACTIVE",
            billing_state="IN_ARREARS",
            balance_due=84836.00,
            billed_demand_ratchet_kw=3100.00,
        )

    def test_the_stored_invoice_reflects_the_last_variant_that_ran(self):
        """A re-read of the invoice shows the true-up numbers, not the estimated ones.

        PRD: "**Adjustment** re-runs the whole determinant calculation under a freshly
        supplied `variant`, with an optional `adjustment_note`, and overwrites
        `billed_energy_mwh`, `billed_demand_kw`, `load_factor_pct`,
        `energy_charge`, `demand_charge`, `fixed_charge`, `total_amount`,
        `minimum_bill_applied` and `variant_applied` from the current register
        data."

        Design: Difficulty/dual_variant_calc/invoice_estimated_vs_actual_true_up_variant_reconciliation
        """
        stack = hospital_billing_stack()
        invoice = create_invoice(
            stack["agreement"]["id"], JUNE_START, JUNE_END, "ESTIMATED"
        )
        issue_invoice(invoice["id"])
        adjust_invoice(invoice["id"], "ACTUAL_TRUE_UP")

        stored = read_invoice(invoice["id"])

        assert_invoice_determinants(
            stored,
            billed_energy_mwh=420.500,
            total_amount=84836.00,
            variant_applied="ACTUAL_TRUE_UP",
            invoice_state="ADJUSTED",
        )
