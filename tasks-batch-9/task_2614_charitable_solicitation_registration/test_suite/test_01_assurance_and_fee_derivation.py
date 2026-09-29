"""Assurance requirements and filing fees derived from one statement.

Every filing stands on a financial statement, but what that statement obliges
the charity to produce, and what the state charges to accept the packet, are
both derived per jurisdiction.
"""

import pytest

from test_helpers import (
    create_financial_statement,
    create_organization,
    open_filing,
    seed_california_profile,
    seed_state_profile,
)


def _two_basis_scenario():
    """One statement, two jurisdictions measuring two different metrics."""
    seed_california_profile()
    seed_state_profile(
        "NY",
        assurance_basis="CONTRIBUTIONS_ONLY",
        review_threshold_cents=25_000_000,
        audit_threshold_cents=100_000_000,
        online_presence_counts=False,
        online_surcharge_cents=0,
        per_contract_fee_cents=0,
        base_filing_fee_cents=2_500,
        filing_fee_cap_cents=30_000,
    )
    organization = create_organization(domicile_state_code="CA")
    statement = create_financial_statement(
        organization,
        total_revenue_cents=26_000_000,
        contributions_cents=20_000_000,
    )
    return organization, statement


class TestAssuranceBasisDivergence:
    """One statement, two states, two different assurance requirements."""

    def test_same_statement_requires_review_in_gross_revenue_state_and_none_in_contributions_only_state(
        self,
    ):
        """PRD §3.2: "Under the `CONTRIBUTIONS_ONLY` basis the measured metric is
        the statement's `contributions_cents`, which excludes
        `government_grant_cents` and every other non-contribution dollar. Under
        the `GROSS_REVENUE` basis the measured metric is `total_revenue_cents`,
        which includes government grants and program revenue. The metric is then
        laddered: when it is at or above `audit_threshold_cents` the requirement
        is `AUDIT`; otherwise when it is at or above `review_threshold_cents` the
        requirement is `REVIEW`; otherwise it is `NONE`."

        Design: Difficulty/dual_variant_calc/assurance_basis_divergence_ca_review_vs_ny_none
        """
        organization, statement = _two_basis_scenario()

        california = open_filing(organization["id"], statement["id"], "CA")
        new_york = open_filing(organization["id"], statement["id"], "NY")

        assert california["required_financial_attestation"] == "REVIEW", (
            "26,000,000 gross revenue is at or above California's 20,000,000 "
            f"review threshold, got {california['required_financial_attestation']}"
        )
        assert new_york["required_financial_attestation"] == "NONE", (
            "20,000,000 of contributions is below New York's 25,000,000 review "
            f"threshold, got {new_york['required_financial_attestation']}"
        )
        assert (
            california["financial_statement_id"]
            == new_york["financial_statement_id"]
            == statement["id"]
        ), "Both filings must rest on the very same statement row"

    def test_divergent_bases_do_not_disturb_the_shared_statements_own_figures(self):
        """PRD §3.2: "`functional_expense_total_cents` is the sum of the program,
        fundraising and management expense amounts. `program_ratio` is the
        program expense divided by that functional expense total, rounded half up
        to four decimal places". PRD §3.3: "When `registration_type` is `INITIAL`,
        the raw amount is multiplied by 1.5 — an initial filing costs half again
        what a renewal costs — and the product is rounded half up to whole cents".

        Design: Difficulty/dual_variant_calc/assurance_basis_divergence_ca_review_vs_ny_none
        """
        organization, statement = _two_basis_scenario()

        california = open_filing(organization["id"], statement["id"], "CA")
        new_york = open_filing(organization["id"], statement["id"], "NY")

        assert statement["functional_expense_total_cents"] == 24_000_000, (
            "18,000,000 + 4,000,000 + 2,000,000 of functional expense, got "
            f"{statement['functional_expense_total_cents']}"
        )
        assert statement["program_ratio"] == pytest.approx(0.75, abs=0.01), (
            f"18,000,000 / 24,000,000 is 0.75, got {statement['program_ratio']}"
        )
        assert california["filing_fee_cents"] == 24_000, (
            "15,000 tier base plus 1,000 online surcharge, multiplied by 1.5 for "
            f"an initial filing, got {california['filing_fee_cents']}"
        )
        assert new_york["filing_fee_cents"] == 22_500, (
            "New York adds no online surcharge, so 15,000 multiplied by 1.5, got "
            f"{new_york['filing_fee_cents']}"
        )


class TestAssuranceThresholdBoundary:
    """The assurance ladder's comparisons are inclusive at the threshold."""

    def _three_statements(self):
        seed_california_profile()
        organization = create_organization()
        low = create_financial_statement(
            organization,
            fiscal_year=2024,
            total_revenue_cents=19_999_999,
            contributions_cents=1_000_000,
            assurance_level="AUDIT",
        )
        at = create_financial_statement(
            organization,
            fiscal_year=2025,
            total_revenue_cents=20_000_000,
            contributions_cents=1_000_000,
            assurance_level="AUDIT",
        )
        audit = create_financial_statement(
            organization,
            fiscal_year=2026,
            total_revenue_cents=200_000_000,
            contributions_cents=1_000_000,
            assurance_level="AUDIT",
        )
        return organization, low, at, audit

    def test_one_cent_below_the_review_threshold_requires_no_attestation_and_exactly_at_it_requires_review(
        self,
    ):
        """PRD §3.2: "The metric is then laddered: when it is at or above
        `audit_threshold_cents` the requirement is `AUDIT`; otherwise when it is
        at or above `review_threshold_cents` the requirement is `REVIEW`;
        otherwise it is `NONE`. Both comparisons are inclusive at the threshold."

        Design: Difficulty/boundary_precision_check/assurance_threshold_exact_boundary_on_gross_revenue_basis
        """
        organization, low, at, _audit = self._three_statements()

        below = open_filing(
            organization["id"],
            low["id"],
            "CA",
            fiscal_year=2024,
            coverage_start="2023-07-01T00:00:00Z",
            coverage_end="2024-07-01T00:00:00Z",
        )
        exactly_at = open_filing(
            organization["id"],
            at["id"],
            "CA",
            fiscal_year=2025,
            coverage_start="2024-07-01T00:00:00Z",
            coverage_end="2025-07-01T00:00:00Z",
        )

        assert below["required_financial_attestation"] == "NONE", (
            "19,999,999 is one cent below the 20,000,000 review threshold, got "
            f"{below['required_financial_attestation']}"
        )
        assert exactly_at["required_financial_attestation"] == "REVIEW", (
            "20,000,000 sits exactly on the inclusive review threshold, got "
            f"{exactly_at['required_financial_attestation']}"
        )

    def test_exactly_at_the_audit_threshold_requires_audit(self):
        """PRD §3.2: "when it is at or above `audit_threshold_cents` the
        requirement is `AUDIT`". The requirement is derived from the state's
        threshold, not copied from the statement: "The assurance requirement
        itself is derived from exactly two rows — the statement named by
        `financial_statement_id`, read regardless of its `statement_status`, and
        the single state profile for the filing's `state_code`".

        Design: Difficulty/boundary_precision_check/assurance_threshold_exact_boundary_on_gross_revenue_basis
        """
        organization, _low, _at, audit = self._three_statements()

        filing = open_filing(
            organization["id"],
            audit["id"],
            "CA",
            fiscal_year=2026,
            coverage_start="2025-07-01T00:00:00Z",
            coverage_end="2026-07-01T00:00:00Z",
        )

        assert filing["required_financial_attestation"] == "AUDIT", (
            "200,000,000 sits exactly on the inclusive audit threshold, got "
            f"{filing['required_financial_attestation']}"
        )
        assert filing["status"] == "DRAFT", (
            f"A newly opened filing lands in DRAFT, got {filing['status']}"
        )

    def test_a_thousand_dollar_supporter_base_prices_both_boundary_filings_identically(
        self,
    ):
        """PRD §3.3: "The first component is a tier selected on the supporting
        statement's `contributions_cents`: public support below $25,000 selects a
        base of $25.00". The fee turns on contributions, not on the revenue
        figure the assurance ladder measures.

        Design: Difficulty/boundary_precision_check/assurance_threshold_exact_boundary_on_gross_revenue_basis
        """
        organization, low, at, _audit = self._three_statements()

        below = open_filing(
            organization["id"],
            low["id"],
            "CA",
            fiscal_year=2024,
            coverage_start="2023-07-01T00:00:00Z",
            coverage_end="2024-07-01T00:00:00Z",
        )
        exactly_at = open_filing(
            organization["id"],
            at["id"],
            "CA",
            fiscal_year=2025,
            coverage_start="2024-07-01T00:00:00Z",
            coverage_end="2025-07-01T00:00:00Z",
        )

        assert below["filing_fee_cents"] == 5_250, (
            "2,500 tier base plus 1,000 online surcharge, multiplied by 1.5, got "
            f"{below['filing_fee_cents']}"
        )
        assert exactly_at["filing_fee_cents"] == 5_250, (
            "The same 1,000,000 of contributions selects the same tier, got "
            f"{exactly_at['filing_fee_cents']}"
        )


class TestFilingFeeClampOrder:
    """The cap is applied after the initial-filing multiplier, never before."""

    def _two_tier_scenario(self):
        seed_california_profile()
        organization = create_organization()
        tier_four = create_financial_statement(
            organization,
            fiscal_year=2026,
            total_revenue_cents=50_000_000,
            contributions_cents=50_000_000,
            program_expense_cents=40_000_000,
            fundraising_expense_cents=6_000_000,
            management_expense_cents=4_000_000,
        )
        tier_three = create_financial_statement(
            organization,
            fiscal_year=2025,
            total_revenue_cents=26_000_000,
            contributions_cents=20_000_000,
        )
        return organization, tier_four, tier_three

    def test_initial_filing_fee_is_capped_only_after_the_multiplier_has_been_applied(
        self,
    ):
        """PRD §3.3: "When `registration_type` is `INITIAL`, the raw amount is
        multiplied by 1.5 — an initial filing costs half again what a renewal
        costs — and the product is rounded half up to whole cents; a renewal
        skips the multiplier entirely. Finally the amount is clamped between the
        state's two bounds: take the larger of the amount and
        `base_filing_fee_cents` (default 2,500 cents), then take the smaller of
        that result and `filing_fee_cap_cents` (default 30,000 cents). The order
        matters whenever the cap binds — clamping before applying the multiplier
        would produce a different fee."

        Design: Difficulty/combinatorial_formula/filing_fee_clamp_applied_after_initial_multiplier_ca
        """
        organization, tier_four, _tier_three = self._two_tier_scenario()

        initial = open_filing(
            organization["id"],
            tier_four["id"],
            "CA",
            "INITIAL",
            coverage_start="2025-07-01T00:00:00Z",
            coverage_end="2026-07-01T00:00:00Z",
        )

        assert initial["filing_fee_cents"] == 30_000, (
            "40,000 tier base plus 1,000 surcharge is 41,000; 61,500 after the "
            "1.5 multiplier; clamped down to the 30,000 cap, got "
            f"{initial['filing_fee_cents']}"
        )
        assert initial["required_financial_attestation"] == "REVIEW", (
            "50,000,000 of gross revenue is above the review threshold, got "
            f"{initial['required_financial_attestation']}"
        )
        assert initial["renewal_due_date"] == "2026-11-14T00:00:00.000Z", (
            "A June fiscal year end in 2026 plus four months and fifteen days, "
            f"got {initial['renewal_due_date']}"
        )

    def test_renewal_on_the_same_charity_skips_the_multiplier_entirely(self):
        """PRD §3.3: "a renewal skips the multiplier entirely". The tier itself is
        "selected on the supporting statement's `contributions_cents`", and the
        state's `online_surcharge_cents` "is added only when **both** the
        organization's `has_online_donation_page` and the state's
        `online_presence_counts` are true".

        Design: Difficulty/combinatorial_formula/filing_fee_clamp_applied_after_initial_multiplier_ca
        """
        organization, _tier_four, tier_three = self._two_tier_scenario()

        renewal = open_filing(
            organization["id"],
            tier_three["id"],
            "CA",
            "RENEWAL",
            fiscal_year=2025,
            coverage_start="2024-07-01T00:00:00Z",
            coverage_end="2025-07-01T00:00:00Z",
        )

        assert renewal["filing_fee_cents"] == 16_000, (
            "15,000 tier base plus 1,000 surcharge with no multiplier, got "
            f"{renewal['filing_fee_cents']}"
        )
        assert renewal["renewal_due_date"] == "2025-11-14T00:00:00.000Z", (
            "A June fiscal year end in 2025 plus four months and fifteen days, "
            f"got {renewal['renewal_due_date']}"
        )
