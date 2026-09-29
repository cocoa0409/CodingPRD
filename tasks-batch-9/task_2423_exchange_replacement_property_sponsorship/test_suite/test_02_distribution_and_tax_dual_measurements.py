"""Two places where the same period is measured twice and the answers differ.

A distribution is measured on accrual at declaration and on cash at payment; a
grantor-trust statement is measured on year-end units or on unit-days. In both
cases the inputs are byte-identical and only the convention changes.
"""

from test_helpers import (
    CANONICAL_DISTRIBUTION,
    CANONICAL_TAX_STATEMENT,
    create_tax_statement,
    declare_distribution,
    pay_distribution,
    read_distribution,
    setup_operating_with_rent_and_debt,
    trust_version,
)


class TestDistributionProvisionalAccrualVersusFinalCash:
    def test_declaration_reports_the_annualised_accrual_measurement(self):
        """The provisional figure annualises lease rent and loan interest.

        PRD: "The accrued base rent is the lease's `base_rent_annual_cents`
        multiplied by the `period_days` and divided by 365, rounded half up."

        Design: Difficulty/dual_variant_calc/distribution_provisional_accrual_vs_final_cash_diverge
        """
        deal = setup_operating_with_rent_and_debt()

        distribution = declare_distribution(
            deal["trust"]["id"], trust_version(deal["trust"]["id"])
        )

        assert distribution["status"] == "DECLARED"
        assert distribution["provisional_amount_cents"] == (
            CANONICAL_DISTRIBUTION["provisional_amount_cents"]
        )
        assert distribution["final_amount_cents"] is None
        assert distribution["reconciliation_delta_cents"] is None

    def test_payment_reports_the_cash_measurement_and_the_two_diverge(self):
        """The final figure sums only the entries that landed inside the window.

        PRD: "It is never annualised and never accrued: it is the signed sum of
        the `amount_cents` of the trust's unreversed ledger entries whose
        `entry_type` is `RENT_RECEIPT` or `DEBT_SERVICE` and whose `occurred_at`
        lies inside the half-open window from `period_start` up to but excluding
        `period_end`."

        Design: Difficulty/dual_variant_calc/distribution_provisional_accrual_vs_final_cash_diverge
        """
        deal = setup_operating_with_rent_and_debt()
        declared = declare_distribution(
            deal["trust"]["id"], trust_version(deal["trust"]["id"])
        )

        paid = pay_distribution(declared["id"])

        assert paid["status"] == "PAID"
        assert paid["final_amount_cents"] == (
            CANONICAL_DISTRIBUTION["final_amount_cents"]
        )
        assert paid["final_amount_cents"] != paid["provisional_amount_cents"]

    def test_the_reconciliation_delta_is_the_signed_difference(self):
        """A late rent receipt produces a negative delta on unchanged terms.

        PRD: "The `final_amount_cents` is that gross minus the same reserve
        replenishment, and `reconciliation_delta_cents` is `final_amount_cents`
        minus `provisional_amount_cents`."

        Design: Difficulty/dual_variant_calc/distribution_provisional_accrual_vs_final_cash_diverge
        """
        deal = setup_operating_with_rent_and_debt()
        declared = declare_distribution(
            deal["trust"]["id"], trust_version(deal["trust"]["id"])
        )
        pay_distribution(declared["id"])

        distribution = read_distribution(declared["id"])
        assert distribution["reconciliation_delta_cents"] == (
            CANONICAL_DISTRIBUTION["reconciliation_delta_cents"]
        )
        assert (
            distribution["reconciliation_delta_cents"]
            == distribution["final_amount_cents"]
            - distribution["provisional_amount_cents"]
        )

    def test_payment_moves_the_replenishment_into_the_reserve_bucket(self):
        """The replenishment is the same accrual under both measurements.

        PRD: "first annualise, by multiplying the lease's
        `base_rent_annual_cents` by the trust's `reserve_target_pct` and rounding
        half up to whole cents; then prorate, by multiplying that annual figure by
        the `period_days`, dividing by 365 and rounding half up again."

        Design: Difficulty/dual_variant_calc/distribution_provisional_accrual_vs_final_cash_diverge
        """
        from test_helpers import read_trust

        deal = setup_operating_with_rent_and_debt()
        declared = declare_distribution(
            deal["trust"]["id"], trust_version(deal["trust"]["id"])
        )
        pay_distribution(declared["id"])

        trust = read_trust(deal["trust"]["id"])
        assert trust["reserve_balance_cents"] == (
            CANONICAL_DISTRIBUTION["reserve_balance_after_pay_cents"]
        )
        assert trust["operating_balance_cents"] == 1_098_901


class TestTaxStatementUnitsAtYearEndVersusUnitDaysWeighted:
    def test_units_at_year_end_ignores_when_the_investor_closed(self):
        """A half-unit holding takes half of every trust-level total.

        PRD: "When the investor closed inside the year is ignored completely: an
        investor who closed on the last business day of December receives exactly
        the same share as one who closed in January, provided both hold the same
        units."

        Design: Difficulty/dual_variant_calc/tax_statement_units_at_year_end_vs_unit_days_weighted_diverge
        """
        deal = setup_operating_with_rent_and_debt()

        statement = create_tax_statement(
            deal["trust"]["id"],
            deal["subscription_a"]["id"],
            tax_year=2026,
            allocation_variant="UNITS_AT_YEAR_END",
        )

        expected = CANONICAL_TAX_STATEMENT["UNITS_AT_YEAR_END"]
        assert statement["status"] == "DRAFT"
        assert statement["rental_income_cents"] == expected["rental_income_cents"]
        assert statement["interest_expense_cents"] == expected["interest_expense_cents"]
        assert statement["depreciation_cents"] == expected["depreciation_cents"]
        assert statement["net_taxable_income_cents"] == (
            expected["net_taxable_income_cents"]
        )

    def test_unit_days_weighted_reweights_the_same_trust_totals(self):
        """Unit-days give the earlier closing 32,400 of 45,000 of the year.

        PRD: "The share is this subscription's unit-days divided by the sum of
        unit-days over every `CLOSED` subscription on the trust."

        Design: Difficulty/dual_variant_calc/tax_statement_units_at_year_end_vs_unit_days_weighted_diverge
        """
        deal = setup_operating_with_rent_and_debt()

        statement = create_tax_statement(
            deal["trust"]["id"],
            deal["subscription_a"]["id"],
            tax_year=2026,
            allocation_variant="UNIT_DAYS_WEIGHTED",
        )

        expected = CANONICAL_TAX_STATEMENT["UNIT_DAYS_WEIGHTED"]
        assert statement["rental_income_cents"] == expected["rental_income_cents"]
        assert statement["interest_expense_cents"] == expected["interest_expense_cents"]
        assert statement["depreciation_cents"] == expected["depreciation_cents"]
        assert statement["net_taxable_income_cents"] == (
            expected["net_taxable_income_cents"]
        )

    def test_both_conventions_may_coexist_for_the_same_subscription_and_year(self):
        """Uniqueness includes the convention, so the two sit side by side.

        PRD: "A statement is unique per `trust_id`, `subscription_id`, `tax_year`
        and `allocation_variant` taken together; a second statement for that
        quadruple is refused with `ERR_DUPLICATE_TAX_STATEMENT`."

        Design: Difficulty/dual_variant_calc/tax_statement_units_at_year_end_vs_unit_days_weighted_diverge
        """
        deal = setup_operating_with_rent_and_debt()

        by_units = create_tax_statement(
            deal["trust"]["id"],
            deal["subscription_a"]["id"],
            allocation_variant="UNITS_AT_YEAR_END",
        )
        by_days = create_tax_statement(
            deal["trust"]["id"],
            deal["subscription_a"]["id"],
            allocation_variant="UNIT_DAYS_WEIGHTED",
        )

        assert by_units["id"] != by_days["id"]
        assert (
            by_days["net_taxable_income_cents"]
            != by_units["net_taxable_income_cents"]
        )

    def test_depreciation_prorates_the_stub_holding_period(self):
        """The 2026 allowance is the annual figure cut back to 134 held days.

        PRD: "The trust's depreciation is another pinned two-step rounding: first
        annualise, taking the property's `depreciable_basis_cents` divided by
        thirty-nine and rounded half up; then prorate, multiplying that annual
        allowance by the held days, dividing by 365 and rounding half up."

        Design: Difficulty/dual_variant_calc/tax_statement_units_at_year_end_vs_unit_days_weighted_diverge
        """
        deal = setup_operating_with_rent_and_debt()

        statement = create_tax_statement(
            deal["trust"]["id"],
            deal["subscription_a"]["id"],
            allocation_variant="UNITS_AT_YEAR_END",
        )

        # Trust-level 2026 depreciation is 9,036,881 cents; a 300/600 share of it
        # rounds half up from 4,518,440.5 to 4,518,441.
        assert statement["depreciation_cents"] == 4_518_441
        assert (
            statement["net_taxable_income_cents"]
            == statement["rental_income_cents"]
            - statement["interest_expense_cents"]
            - statement["depreciation_cents"]
        )
