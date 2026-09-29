"""Where in a money formula the rounding happens, and what the fee tier reads."""

import pytest

from test_helpers import (
    build_private_scenario,
    dispose_unit,
    expected_disposition_fee,
    expected_invoice_lines,
    issue_invoice,
    read_account,
    read_invoice,
    read_tank,
    read_unit,
    set_clock,
)


def _premium_stored_unit(*, tank_code, slot_code, parent_name, collection_site_code):
    """A private unit cryopreserved in a PREMIUM tank, billed to a five-year account."""
    return build_private_scenario(
        tank_code=tank_code,
        tank_class="PREMIUM",
        capacity_slots=10,
        primary_parent_name=parent_name,
        collection_site_code=collection_site_code,
        plan_term_years=5,
        prepaid_through_date="2027-06-30",
        slot_code=slot_code,
    )


class TestInvoiceLineRounding:
    def test_each_line_is_rounded_before_it_joins_the_total(self):
        """The premium surcharge is taken from the already-rounded base line.

        "`surcharge_line_cents` is `base_line_cents` — the **already-rounded** base line —
        multiplied by 0.075 and rounded half up"

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order_pinned_mode_b
        """
        scenario = _premium_stored_unit(
            tank_code="TANK-P",
            slot_code="P-01",
            parent_name="Premium Parent",
            collection_site_code="SITE-02",
        )
        set_clock("2026-09-01T00:00:00Z")

        invoice = issue_invoice(
            scenario["account"]["id"],
            billing_period_start="2026-09-01",
            billing_period_end="2026-12-10",
            prorated_days=100,
        )

        assert invoice["base_line_cents"] == 4932
        assert invoice["surcharge_line_cents"] == 370
        assert invoice["admin_line_cents"] == 225
        assert invoice["late_fee_line_cents"] == 0
        lines = expected_invoice_lines(100, premium_tank=True)
        assert invoice["base_line_cents"] == lines["base_line_cents"]
        assert invoice["surcharge_line_cents"] == lines["surcharge_line_cents"]
        assert invoice["admin_line_cents"] == lines["admin_line_cents"]

    def test_the_total_is_the_plain_sum_of_the_rounded_lines(self):
        """Round-then-sum gives 5527 cents where sum-then-round would give 5526.

        "at a `prorated_days` of 100 on a `PREMIUM` tank the two orders differ by one cent,
        and this specification mandates round-then-sum."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order_pinned_mode_b
        """
        scenario = _premium_stored_unit(
            tank_code="TANK-P",
            slot_code="P-01",
            parent_name="Premium Parent",
            collection_site_code="SITE-02",
        )
        set_clock("2026-09-01T00:00:00Z")

        invoice = issue_invoice(
            scenario["account"]["id"],
            billing_period_start="2026-09-01",
            billing_period_end="2026-12-10",
            prorated_days=100,
        )

        assert invoice["amount_due_cents"] == 5527
        assert invoice["amount_due_cents"] != 5526
        assert invoice["amount_due_cents"] == (
            invoice["base_line_cents"]
            + invoice["surcharge_line_cents"]
            + invoice["admin_line_cents"]
            + invoice["late_fee_line_cents"]
        )

    def test_the_new_invoice_opens_issued_thirty_days_out_and_lands_on_the_balance(self):
        """A freshly issued invoice is due thirty days after its period start.

        "The invoice opens in `status` of `ISSUED` with `due_date` set to
        `billing_period_start` plus 30 days."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order_pinned_mode_b
        """
        scenario = _premium_stored_unit(
            tank_code="TANK-P",
            slot_code="P-01",
            parent_name="Premium Parent",
            collection_site_code="SITE-02",
        )
        set_clock("2026-09-01T00:00:00Z")

        invoice = issue_invoice(
            scenario["account"]["id"],
            billing_period_start="2026-09-01",
            billing_period_end="2026-12-10",
            prorated_days=100,
        )

        assert invoice["status"] == "ISSUED"
        assert invoice["due_date"].startswith("2026-10-01")
        assert invoice["amount_paid_cents"] == 0

        account = read_account(scenario["account"]["id"])
        assert account["balance_cents"] == 5527


class TestDispositionSettlementTier:
    def test_the_full_year_premium_invoice_totals_nineteen_thousand_five_seventy_five(self):
        """A full prepaid year on a premium tank bills base, surcharge and admin.

        "`admin_line_cents` is 18000 cents multiplied by 0.0125, rounded half up."

        Design: Difficulty/combinatorial_formula/disposition_settlement_tier_keyed_on_pre_fee_subtotal_mode_c
        """
        scenario = _premium_stored_unit(
            tank_code="TANK-P2",
            slot_code="P2-01",
            parent_name="Settle Parent",
            collection_site_code="SITE-02",
        )
        set_clock("2026-09-01T00:00:00Z")

        invoice = issue_invoice(
            scenario["account"]["id"],
            billing_period_start="2026-09-01",
            billing_period_end="2027-08-31",
            prorated_days=365,
        )

        assert invoice["amount_due_cents"] == 19575
        assert invoice["base_line_cents"] == 18000
        assert invoice["surcharge_line_cents"] == 1350
        assert invoice["admin_line_cents"] == 225

    def test_the_fee_tier_reads_the_pre_fee_subtotal_and_not_the_final_total(self):
        """A pre-fee subtotal of 9515 cents attracts the middle tier, not the top one.

        "The **disposition fee** is a tier keyed on that pre-fee subtotal and never on the
        final total: a subtotal at or below 0 attracts 2500 cents, a subtotal from 1 to 9999
        cents inclusive attracts 5000 cents, and a subtotal of 10000 cents or more attracts
        7500 cents."

        Design: Difficulty/combinatorial_formula/disposition_settlement_tier_keyed_on_pre_fee_subtotal_mode_c
        """
        scenario = _premium_stored_unit(
            tank_code="TANK-P2",
            slot_code="P2-01",
            parent_name="Settle Parent",
            collection_site_code="SITE-02",
        )
        set_clock("2026-09-01T00:00:00Z")
        issue_invoice(
            scenario["account"]["id"],
            billing_period_start="2026-09-01",
            billing_period_end="2027-08-31",
            prorated_days=365,
        )

        set_clock("2026-12-08T00:00:00Z")
        dispose_unit(scenario["unit"]["id"], reason="QUALITY_FAILURE", director_user_id="md-002")

        account = read_account(scenario["account"]["id"])
        assert account["last_settlement_total_cents"] == 14515
        assert account["last_settlement_total_cents"] != 17015
        assert expected_disposition_fee(9515) == 5000

    def test_disposal_discards_the_unit_and_frees_its_slot(self):
        """Disposal writes all four disposal fields and empties the slot.

        "The unit's `processing_status` is set to `DISCARDED`, its `availability_status` to
        `DISPOSED`, its `disposition_reason` to the supplied `reason` and its `disposed_at`
        from the logical clock."

        Design: Difficulty/combinatorial_formula/disposition_settlement_tier_keyed_on_pre_fee_subtotal_mode_c
        """
        scenario = _premium_stored_unit(
            tank_code="TANK-P2",
            slot_code="P2-01",
            parent_name="Settle Parent",
            collection_site_code="SITE-02",
        )
        set_clock("2026-09-01T00:00:00Z")
        invoice = issue_invoice(
            scenario["account"]["id"],
            billing_period_start="2026-09-01",
            billing_period_end="2027-08-31",
            prorated_days=365,
        )

        set_clock("2026-12-08T00:00:00Z")
        dispose_unit(scenario["unit"]["id"], reason="QUALITY_FAILURE", director_user_id="md-002")

        unit = read_unit(scenario["unit"]["id"])
        assert unit["processing_status"] == "DISCARDED"
        assert unit["availability_status"] == "DISPOSED"
        assert unit["disposition_reason"] == "QUALITY_FAILURE"
        assert unit["disposed_at"].startswith("2026-12-08")

        tank = read_tank(scenario["tank"]["id"])
        assert tank["occupied_slots"] == 0
        assert read_invoice(invoice["id"])["amount_due_cents"] == 19575
