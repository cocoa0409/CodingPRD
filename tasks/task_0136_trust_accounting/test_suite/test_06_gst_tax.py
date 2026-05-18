"""Generation-skipping transfer tax — PRD §3.6."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    GST_EXEMPTION_LIMIT,
    GST_TAX_RATE,
    add_asset,
    add_beneficiary,
    api_client,
    approve_distribution,
    execute_distribution,
    propose_distribution,
    re_get_trust,
    setup_active_trust_with_principal,
    setup_exemption_almost_consumed_trust,
    validate_error,
    validate_success,
)


# ===========================================================================
# Non-skip beneficiary — PRD §3.6
# ===========================================================================
class TestGstNonSkip:

    def test_non_skip_distribution_not_taxable(self, api):
        """PRD §3.6: "If the beneficiary is not a skip person, the
        taxable portion is zero."

        Claim: distribution to a CHILD beneficiary -> gst_taxable=
        false, gst_tax_amount==0.00 after approval.
        """
        scenario = setup_active_trust_with_principal(
            principal_amount=100_000.00,
            beneficiary_relation_class="CHILD",
            beneficiary_birth_date="2000-01-01",
        )
        dist = propose_distribution(
            scenario.trust, scenario.beneficiary,
            scenario.primary_trustee_headers,
            amount_principal=10_000.00,
            distribution_type="DISCRETIONARY",
        )
        dist = approve_distribution(
            scenario.trust, dist, scenario.second_trustee_headers,
        )
        assert dist["gst_taxable"] is False
        assert dist["gst_tax_amount"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# Skip beneficiary, exemption fully consumed — PRD §3.6
# ===========================================================================
class TestGstSkipBeyondExemption:

    def test_skip_distribution_beyond_remaining_exemption_taxed(
        self, api,
    ):
        """PRD §3.6: "If the beneficiary is a skip person, the
        taxable portion is the total amount minus the remaining
        exemption, floored at zero. The distribution is gst_taxable
        exactly when the beneficiary is a skip person and the
        taxable portion is strictly greater than zero."

        Claim: skip-person distribution that fully exceeds remaining
        exemption is taxed at 40% on the taxable portion.

        Scenario: gst_exemption_used = 13,500,000 (110k of exemption
        left); distribute 1,000,000 to GRANDCHILD ->
        taxable_portion = 1,000,000 - 110,000 = 890,000;
        gst_tax_amount = 890,000 * 0.40 = 356,000.00.
        """
        scenario, skip = setup_exemption_almost_consumed_trust(
            pre_consumed=13_500_000.00,
        )
        # Add another $1M principal for the actual taxable
        # distribution.
        add_asset(
            scenario.trust,
            book_value=1_000_000.00,
            classification="PRINCIPAL",
            asset_class="CASH",
            headers=scenario.grantor_headers,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        dist = propose_distribution(
            scenario.trust, skip,
            scenario.primary_trustee_headers,
            amount_principal=1_000_000.00,
            distribution_type="DISCRETIONARY",
        )
        dist = approve_distribution(
            scenario.trust, dist, scenario.second_trustee_headers,
        )
        assert dist["gst_taxable"] is True
        # taxable = 1_000_000 - 110_000 = 890_000; tax = 0.40 *
        # 890_000 = 356_000.00.
        assert dist["gst_tax_amount"] == pytest.approx(
            356_000.00, abs=0.01,
        )

    def test_skip_total_exactly_equals_remaining_not_taxable(
        self, api,
    ):
        """PRD §3.6: "if the total amount equals the remaining
        exemption, the taxable portion is zero and gst_taxable is
        false".

        Claim: GRANDCHILD distribution whose total exactly equals
        the remaining exemption -> gst_taxable=false, tax=0.
        """
        scenario, skip = setup_exemption_almost_consumed_trust(
            pre_consumed=13_609_999.00,
        )
        # Remaining = 13_610_000 - 13_609_999 = 1.00. Distribute
        # exactly 1.00 principal.
        dist = propose_distribution(
            scenario.trust, skip,
            scenario.primary_trustee_headers,
            amount_principal=1.00,
            distribution_type="DISCRETIONARY",
        )
        dist = approve_distribution(
            scenario.trust, dist, scenario.second_trustee_headers,
        )
        assert dist["gst_taxable"] is False
        assert dist["gst_tax_amount"] == pytest.approx(0.00, abs=0.01)

    def test_skip_total_exceeds_remaining_by_one_cent_taxable(
        self, api,
    ):
        """PRD §3.6: "if the total amount exceeds the remaining
        exemption by even 0.01, the taxable portion is 0.01 and
        gst_taxable is true."

        Claim: GRANDCHILD distribution 0.01 over remaining exemption
        -> gst_taxable=true, tax = 0.01 * 0.40 = 0.00 rounded
        half-up to 2dp (i.e., 0.004 rounds to 0.00).
        Actually 0.01 * 0.40 = 0.004 -> round_half_up to 2dp = 0.00.
        Per PRD §2.7 "a value whose discarded fractional remainder is
        exactly 0.005 rounds away from zero (so 0.005 becomes 0.01)".
        0.004 < 0.005, so rounds to 0.00.
        """
        scenario, skip = setup_exemption_almost_consumed_trust(
            pre_consumed=13_609_999.00,
        )
        # Remaining = 1.00. Distribute 1.01 principal -> taxable
        # portion = 0.01.
        dist = propose_distribution(
            scenario.trust, skip,
            scenario.primary_trustee_headers,
            amount_principal=1.01,
            distribution_type="DISCRETIONARY",
        )
        dist = approve_distribution(
            scenario.trust, dist, scenario.second_trustee_headers,
        )
        assert dist["gst_taxable"] is True


# ===========================================================================
# Exemption-then-tax evaluation order — PRD §3.6 (pinned order)
# ===========================================================================
class TestGstEvaluationOrder:

    def test_exemption_consumed_first_then_tax_on_residual(self, api):
        """PRD §3.6: "The pinned order is: first, classify gst_taxable
        using the current gst_exemption_used; second, compute the
        exemption applied as the lesser of the total amount and the
        remaining exemption; third, compute the taxable portion as
        the total amount minus the exemption applied; fourth, compute
        gst_tax_amount as the taxable portion multiplied by 40%,
        rounded half-up to two decimal places."

        PRD §3.6: "On a successful execution, the Trust's
        gst_exemption_used is increased by the exemption applied —
        the minimum of the distribution's total amount and the
        remaining exemption before the execution."

        Claim: with 1.00 of exemption remaining, distributing 10.00
        consumes 1.00 of exemption (gst_exemption_used reaches
        13,610,000), and tax = (10.00 - 1.00) * 0.40 = 3.60.
        """
        scenario, skip = setup_exemption_almost_consumed_trust(
            pre_consumed=13_609_999.00,
        )
        # Top up principal so 10.00 distribution can execute.
        add_asset(
            scenario.trust, book_value=100.00,
            classification="PRINCIPAL", asset_class="CASH",
            headers=scenario.grantor_headers,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        dist = propose_distribution(
            scenario.trust, skip,
            scenario.primary_trustee_headers,
            amount_principal=10.00,
            distribution_type="DISCRETIONARY",
        )
        dist = approve_distribution(
            scenario.trust, dist, scenario.second_trustee_headers,
        )
        # Now execute and check post-execute state.
        dist = execute_distribution(
            scenario.trust, dist, scenario.second_trustee_headers,
        )
        trust_after = re_get_trust(scenario.trust["id"])

        # gst_exemption_used must have advanced by exactly 1.00 (the
        # exemption applied, capped at remaining).
        assert trust_after["gst_exemption_used"] == pytest.approx(
            13_610_000.00, abs=0.01,
        )
        # Tax on residual 9.00 -> 9.00 * 0.40 = 3.60.
        assert dist["gst_tax_amount"] == pytest.approx(3.60, abs=0.01)
        assert dist["gst_taxable"] is True
