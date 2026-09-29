"""Dual-variant arithmetic: one stored row, two deliberately different readings.

Compliance is measured twice over the same purchase rows — once while the period
may still be receiving files and once at settlement — and an administrative fee
pool is settled either off what was billed or off what was banked.  Both pairs
diverge by construction, and the divergence is what these tests pin down.
"""

from test_helpers import assertions as a
from test_helpers.constants import TIER_0, TIER_2
from test_helpers.fixtures import (
    distribute_distribution,
    finalize_measurement,
    read_commitment,
    read_distribution,
    read_measurement,
    read_member,
)


class TestComplianceVariants:
    """The preliminary and final readings of a single compliance measurement."""

    def test_preliminary_variant_admits_partially_loaded_and_drops_unmatched_spend(
        self, api, dual_variant_setup
    ):
        """PRD §3.8: "It admits files in `LOADED` **and** `PARTIALLY_LOADED` status,
        because a partially loaded file's accepted lines are real purchases."
        PRD §3.8: "It **excludes** `unmatched_spend_cents` from the denominator, on
        the reasoning that an unmatched line has not yet been proven to belong to
        the contract's category and charging it against the member early would
        understate compliance."
        PRD §3.8: "The preliminary variant takes on-contract spend of 47,500,000
        over a denominator of 47,500,000 plus 15,750,000, or 63,250,000, giving
        75.10 percent."
        PRD §3.8: "The measure action drives `DRAFT → PRELIMINARY` — any other
        starting status returns `ERR_INVALID_MEASUREMENT_STATE` — writes the result
        to both `compliance_pct` and `preliminary_compliance_pct`, sets
        `computed_variant` to `PRELIMINARY`, computes `qualified_tier_code` from the
        preliminary figures, and increments the measurement's `version` by one."

        Design: Difficulty/dual_variant_calc/compliance_preliminary_versus_final_same_period
        """
        preliminary = dual_variant_setup["preliminary"]

        assert preliminary["status"] == "PRELIMINARY"
        assert preliminary["computed_variant"] == "PRELIMINARY"
        a.assert_pct(preliminary["compliance_pct"], 75.10)
        a.assert_pct(preliminary["preliminary_compliance_pct"], 75.10)
        assert preliminary["on_contract_spend_cents"] == 47500000
        assert preliminary["leakage_spend_cents"] == 15750000
        assert preliminary["total_category_spend_cents"] == 63250000
        assert preliminary["measured_volume_units"] == 5000
        assert preliminary["basis_empty"] is False
        assert preliminary["qualified_tier_code"] == TIER_0

    def test_preliminary_measurement_moves_no_commitment_field(
        self, api, dual_variant_setup
    ):
        """PRD §3.8: "Crucially, **no commitment field moves**: a preliminary
        measurement never retiers anybody."

        Design: Difficulty/dual_variant_calc/compliance_preliminary_versus_final_same_period
        """
        commitment = read_commitment(api, dual_variant_setup["commitment"]["id"])

        assert commitment["current_tier_code"] == TIER_0
        assert commitment["requalification_round"] == 0
        assert commitment["last_final_compliance_pct"] is None
        assert commitment["election_status"] == "REQUAL_REVIEW"

    def test_final_variant_drops_the_partially_loaded_file_and_counts_unmatched_spend(
        self, api, dual_variant_setup
    ):
        """PRD §3.8: "It admits files in `LOADED` status **only** — a
        `PARTIALLY_LOADED` file is dropped in its entirety, including its accepted
        lines, because a statement with rejected lines is not a settleable
        statement of the period."
        PRD §3.8: "And it **includes** `unmatched_spend_cents` in the denominator,
        because at settlement an unmatched purchase is presumed in-category and
        therefore counts against the member."
        PRD §3.8: "`preliminary_compliance_pct` is preserved unchanged as the audit
        trail while `compliance_pct` is overwritten with the final figure, and
        `computed_variant` becomes `FINAL`."
        PRD §3.8: "The final variant drops the partially loaded file entirely and
        adds the unmatched spend, taking 47,500,000 over 47,500,000 plus 3,000,000,
        or 50,500,000, giving 94.06 percent."

        Design: Difficulty/dual_variant_calc/compliance_preliminary_versus_final_same_period
        """
        measurement_id = dual_variant_setup["measurement"]["id"]

        finalize_measurement(api, measurement_id)

        final = read_measurement(api, measurement_id)
        assert final["status"] == "FINAL"
        assert final["computed_variant"] == "FINAL"
        a.assert_pct(final["preliminary_compliance_pct"], 75.10)
        a.assert_pct(final["compliance_pct"], 94.06)
        assert final["on_contract_spend_cents"] == 47500000
        assert final["leakage_spend_cents"] == 0
        assert final["unmatched_spend_cents"] == 3000000
        assert final["total_category_spend_cents"] == 50500000
        assert final["measured_volume_units"] == 5000
        assert final["basis_empty"] is False

    def test_final_figures_qualify_the_top_rung_the_preliminary_figures_missed(
        self, api, dual_variant_setup
    ):
        """PRD §3.8: "Against a ladder of a default rung at 0 basis points, 0.00
        percent and 0 units; a middle rung at 800 basis points, 80.00 percent and
        2000 units; and a top rung at 1500 basis points, 90.00 percent and 5000
        units — the preliminary figures above, 75.10 percent on 5000 units, qualify
        only the default rung, because 75.10 misses the 80.00 compliance floor even
        though 5000 units clears the top rung's volume floor."
        PRD §3.8: "The final figures, 94.06 percent on 5000 units, sit exactly on
        the top rung's volume floor and clear its compliance floor, so they qualify
        the top rung."

        Design: Difficulty/dual_variant_calc/compliance_preliminary_versus_final_same_period
        """
        measurement_id = dual_variant_setup["measurement"]["id"]
        assert dual_variant_setup["preliminary"]["qualified_tier_code"] == TIER_0

        finalize_measurement(api, measurement_id)

        assert read_measurement(api, measurement_id)["qualified_tier_code"] == TIER_2


class TestFeePoolBasisVariants:
    """The same accrued fee settled on the accrual basis and on the collected basis."""

    def test_accrual_basis_settles_off_the_billed_pool(
        self, api, accrual_and_collected_setup
    ):
        """PRD §3.9: "`gross_pool_cents` is `accrued_fee_cents` when `basis` is
        `ACCRUAL` and `collected_fee_cents` when `basis` is `COLLECTED`."
        PRD §3.9: "Distributing pins `basis` to the contract's `share_basis` so the
        settlement records the rule it was computed under."
        PRD §3.9: "The same contract on the accrual basis with an
        `accrued_fee_cents` of 142,500 yields a `holdback_cents` of 3563, a
        `net_pool_cents` of 138,937 and a `member_pool_cents` of 83,362; on the
        collected basis with a `collected_fee_cents` of 100,200 it yields the 2505 /
        97,695 / 58,617 figures above."

        Design: Difficulty/dual_variant_calc/admin_fee_pool_accrual_basis_versus_collected_basis
        """
        distribution_id = accrual_and_collected_setup["accrual_distribution"]["id"]
        assert accrual_and_collected_setup["accrual_distribution"][
            "accrued_fee_cents"
        ] == 142500

        distribute_distribution(api, distribution_id)

        settled = read_distribution(api, distribution_id)
        assert settled["status"] == "DISTRIBUTED"
        assert settled["basis"] == "ACCRUAL"
        assert settled["gross_pool_cents"] == 142500
        assert settled["holdback_bps_applied"] == 250
        assert settled["holdback_cents"] == 3563
        assert settled["net_pool_cents"] == 138937
        assert settled["member_pool_cents"] == 83362
        assert settled["member_share_total_cents"] == 83362
        assert settled["undistributed_cents"] == 0
        assert settled["gpo_retained_cents"] == 59138
        a.assert_waterfall_conserved(settled)

    def test_collected_basis_settles_off_the_banked_pool(
        self, api, accrual_and_collected_setup
    ):
        """PRD §3.9: "`gross_pool_cents` is `accrued_fee_cents` when `basis` is
        `ACCRUAL` and `collected_fee_cents` when `basis` is `COLLECTED`."
        PRD §3.9: "The same contract on the accrual basis with an
        `accrued_fee_cents` of 142,500 yields a `holdback_cents` of 3563, a
        `net_pool_cents` of 138,937 and a `member_pool_cents` of 83,362; on the
        collected basis with a `collected_fee_cents` of 100,200 it yields the 2505 /
        97,695 / 58,617 figures above."
        PRD §3.9: "`gpo_retained_cents` is `gross_pool_cents` minus
        `member_share_total_cents` minus `undistributed_cents`, which is exactly the
        holdback plus the non-member slice of the net pool."

        Design: Difficulty/dual_variant_calc/admin_fee_pool_accrual_basis_versus_collected_basis
        """
        distribution_id = accrual_and_collected_setup["collected_distribution"]["id"]
        assert accrual_and_collected_setup["collected_distribution"][
            "accrued_fee_cents"
        ] == 142500

        distribute_distribution(api, distribution_id)

        settled = read_distribution(api, distribution_id)
        assert settled["status"] == "DISTRIBUTED"
        assert settled["basis"] == "COLLECTED"
        assert settled["collected_fee_cents"] == 100200
        assert settled["gross_pool_cents"] == 100200
        assert settled["holdback_bps_applied"] == 250
        assert settled["holdback_cents"] == 2505
        assert settled["net_pool_cents"] == 97695
        assert settled["member_pool_cents"] == 58617
        assert settled["member_share_total_cents"] == 58617
        assert settled["undistributed_cents"] == 0
        assert settled["gpo_retained_cents"] == 41583
        a.assert_waterfall_conserved(settled)

    def test_one_member_accumulates_both_bases_into_its_fee_credit_balance(
        self, api, accrual_and_collected_setup
    ):
        """PRD §3.9: "Every eligible member's `fee_credit_balance_cents` is then
        credited by that member's `share_cents`, incrementing each member's
        `version` by one, the distribution's `status` becomes `DISTRIBUTED`, and its
        `version` increments by one."

        Design: Difficulty/dual_variant_calc/admin_fee_pool_accrual_basis_versus_collected_basis
        """
        member_id = accrual_and_collected_setup["member"]["id"]

        distribute_distribution(
            api, accrual_and_collected_setup["accrual_distribution"]["id"]
        )
        distribute_distribution(
            api, accrual_and_collected_setup["collected_distribution"]["id"]
        )

        assert read_member(api, member_id)["fee_credit_balance_cents"] == 141979
