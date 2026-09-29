"""Exact landings: one hundredth of a point, an empty split, and a rounded tie.

Three different metrics are probed exactly on their thresholds.  A tier is
earned on two inclusive floors at once; a fee pool is conserved when the set of
members entitled to it is empty; and an evidence threshold is compared against
the rounded weighted score rather than the raw weighted sum.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_errors import ERR_EVIDENCE_SCORE_BELOW_THRESHOLD
from test_helpers.constants import TIER_1, TIER_2
from test_helpers.fixtures import (
    activate_contract,
    build_priced_setup,
    create_contract,
    create_distribution,
    create_evidence_review,
    distribute_distribution,
    finalize_measurement,
    measure,
    open_measurement,
    open_requalification,
    read_commitment,
    read_contract,
    read_distribution,
    read_evidence_review,
    read_measurement,
    read_member,
    set_clock,
    submit_distributor_file,
    terminate_commitment,
)
from test_helpers.test_users import (
    CLINICAL_REVIEWER_2,
    clinical_reviewer_2_headers,
    clinical_reviewer_headers,
)


@pytest.fixture
def exact_floor_setup(api):
    """A DRAFT measurement whose two readings straddle the 90.00 compliance floor.

    The loaded statement carries 5000 on-contract units at 9000 cents each and
    500 unmatched units at 10000 cents each; the partially loaded statement adds
    500 leakage units at 10010 cents each next to one rejected zero-quantity
    line.  The volume floor of 5000 units is met exactly under both readings.
    """
    setup = build_priced_setup(
        api,
        member_overrides={
            "item_master": [
                f.item_master_row("MI-1"),
                f.item_master_row("MI-9", "Unlisted suture kit"),
            ]
        },
    )
    commitment_id = setup["commitment"]["id"]
    file_a = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 5000, 9000, "2026-08-05"),
            f.purchase_line_row("MI-9", 500, 10000, "2026-08-06"),
        ],
        distributor_code="D-A",
    )
    file_b = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 500, 10010, "2026-08-07"),
            f.purchase_line_row("MI-1", 0, 9000, "2026-08-08"),
        ],
        distributor_code="D-B",
    )
    open_requalification(api, commitment_id)
    measurement = open_measurement(api, commitment_id)
    setup.update({"file_a": file_a, "file_b": file_b, "measurement": measurement})
    return setup


@pytest.fixture
def terminated_before_distribution_setup(api, per_line_fee_setup):
    """The 70-cent accrual of a commitment that has since been TERMINATED."""
    terminate_commitment(api, per_line_fee_setup["commitment"]["id"])
    distribution = create_distribution(api, per_line_fee_setup["contract"]["id"])
    per_line_fee_setup["distribution"] = distribution
    return per_line_fee_setup


@pytest.fixture
def borderline_dossier_setup(api):
    """A DRAFT contract gated on clinical review, behind a 6.99 dossier."""
    set_clock(api)
    contract = create_contract(
        api,
        contract_code="C-CONV",
        supplier_name="Northline Ortho",
        category_code="CAT-ORTHO",
        requires_clinical_review=True,
    )
    review = create_evidence_review(api, contract["id"], 6.99, 6.99, 6.99, "Borderline dossier.")
    return {"contract": contract, "review": review}


class TestRequalificationAtExactFloors:
    """90.00 percent and 5000 units, both floors met to the digit."""

    def test_the_preliminary_reading_misses_the_top_rung_by_one_hundredth_of_a_point(
        self, api, exact_floor_setup
    ):
        """PRD §3.8: "`total_category_spend_cents` is then the denominator the variant
        actually used: always `on_contract_spend_cents` plus `leakage_spend_cents`, plus
        `unmatched_spend_cents` only if the variant counts unmatched spend."
        PRD §3.8: "All the sums are exact integer cents and the percentage is computed
        **once** from the unrounded integer sums — never by averaging per-file
        percentages."
        PRD §3.8: "The two axes are evaluated jointly, not separately: a member may
        clear the volume floor of a rich tier and miss its compliance floor, or the
        reverse, and it then falls back to the best tier where **both** hold — not to
        the nearer of the two."

        Design: Difficulty/boundary_precision_check/requalification_at_exact_compliance_and_volume_floors
        """
        preliminary = measure(api, exact_floor_setup["measurement"]["id"])

        assert preliminary["on_contract_spend_cents"] == 45000000
        assert preliminary["leakage_spend_cents"] == 5005000
        assert preliminary["total_category_spend_cents"] == 50005000
        assert preliminary["basis_empty"] is False
        a.assert_pct(preliminary["compliance_pct"], 89.99)
        assert preliminary["measured_volume_units"] == 5000
        assert preliminary["qualified_tier_code"] == TIER_1

    def test_the_final_reading_lands_on_both_floors_exactly_and_qualifies(
        self, api, exact_floor_setup
    ):
        """PRD §3.8: "A ladder entry is *eligible* when the measured compliance
        percentage is at least that entry's `min_compliance_pct` **and** the measured
        volume is at least that entry's `min_committed_volume_units`."
        PRD §3.8: "Both comparisons are inclusive, so landing exactly on a threshold
        qualifies; compliance is compared at two decimal places against a two-decimal
        minimum, and volume is an integer comparison."
        PRD §3.8: "**Hop 1.** Every money and volume field is recomputed under the
        final variant, `preliminary_compliance_pct` is preserved, `computed_variant`
        becomes `FINAL`, `qualified_tier_code` is derived from the final figures,
        `status` becomes `FINAL`, and the measurement's `version` increments by one."

        Design: Difficulty/boundary_precision_check/requalification_at_exact_compliance_and_volume_floors
        """
        measurement_id = exact_floor_setup["measurement"]["id"]
        measure(api, measurement_id)

        finalize_measurement(api, measurement_id)

        final = read_measurement(api, measurement_id)
        assert final["status"] == "FINAL"
        assert final["computed_variant"] == "FINAL"
        assert final["on_contract_spend_cents"] == 45000000
        assert final["unmatched_spend_cents"] == 5000000
        assert final["leakage_spend_cents"] == 0
        assert final["total_category_spend_cents"] == 50000000
        a.assert_pct(final["compliance_pct"], 90.00)
        a.assert_pct(final["preliminary_compliance_pct"], 89.99)
        assert final["measured_volume_units"] == 5000
        assert final["qualified_tier_code"] == TIER_2

    def test_the_exact_landing_retiers_the_commitment_to_the_top_rung(
        self, api, exact_floor_setup
    ):
        """PRD §3.8: "**Hop 2**, caused by hop 1. The commitment's
        `last_final_compliance_pct` is set to the final `compliance_pct`, its
        `current_tier_code` is overwritten with the measurement's
        `qualified_tier_code`, its `requalification_round` increments by one, and its
        `election_status` returns from `REQUAL_REVIEW` to `ACTIVE`, closing the
        requalification cycle."

        Design: Difficulty/boundary_precision_check/requalification_at_exact_compliance_and_volume_floors
        """
        setup = exact_floor_setup
        measure(api, setup["measurement"]["id"])

        finalize_measurement(api, setup["measurement"]["id"])

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["current_tier_code"] == TIER_2
        a.assert_pct(commitment["last_final_compliance_pct"], 90.00)
        assert commitment["requalification_round"] == 1
        assert commitment["election_status"] == "ACTIVE"


class TestDistributionWithNoEligibleMember:
    """The degenerate edge of the waterfall: 0 plus 42 plus 28 is 70."""

    def test_the_accrual_survives_the_termination_and_keys_the_zero_holdback_rung(
        self, api, terminated_before_distribution_setup
    ):
        """PRD §3.9: "`accrued_fee_cents` is computed at the moment of creation and is
        never recomputed by any later transition."
        PRD §3.9: "The server takes the ladder entry with the greatest
        `min_gross_pool_cents` that is less than or equal to `gross_pool_cents` and
        writes its `holdback_bps` into `holdback_bps_applied`; if no entry qualifies,
        `holdback_bps_applied` is 0."
        PRD §3.9: "The empty-basis branch is worth stating in the same numbers. A
        `gross_pool_cents` of 70 with a `holdback_bps_applied` of 0 and a
        `member_share_bps` of 6000 gives a `member_pool_cents` of 42."

        Design: Difficulty/boundary_precision_check/distribution_with_empty_eligible_member_set
        """
        setup = terminated_before_distribution_setup
        assert setup["distribution"]["accrued_fee_cents"] == 70

        distribute_distribution(api, setup["distribution"]["id"])

        settled = read_distribution(api, setup["distribution"]["id"])
        assert settled["basis"] == "ACCRUAL"
        assert settled["gross_pool_cents"] == 70
        assert settled["holdback_bps_applied"] == 0
        assert settled["holdback_cents"] == 0
        assert settled["net_pool_cents"] == 70
        assert settled["member_pool_cents"] == 42

    def test_the_whole_member_pool_lands_undistributed_when_nobody_is_eligible(
        self, api, terminated_before_distribution_setup
    ):
        """PRD §3.9: "The member pool is split among the contract's *eligible*
        commitments: those whose `election_status` is `ACTIVE`, whose `lop_status` is
        `COUNTERSIGNED`, whose `leakage_flag` is false, and whose
        `ytd_on_contract_spend_cents` is strictly greater than 0."
        PRD §3.9: "When the eligible set is empty, or the total weight is 0,
        `member_shares` stays an empty array, `member_share_total_cents` is 0, and the
        whole `member_pool_cents` lands in `undistributed_cents`."
        PRD §3.9: "If no commitment is eligible, `member_shares` is empty,
        `member_share_total_cents` is 0, `undistributed_cents` is 42, and
        `gpo_retained_cents` is 28 — and 0 plus 42 plus 28 is 70, the gross pool."

        Design: Difficulty/boundary_precision_check/distribution_with_empty_eligible_member_set
        """
        setup = terminated_before_distribution_setup

        distribute_distribution(api, setup["distribution"]["id"])

        settled = read_distribution(api, setup["distribution"]["id"])
        assert settled["member_shares"] == []
        assert settled["member_share_total_cents"] == 0
        assert settled["undistributed_cents"] == 42
        assert settled["gpo_retained_cents"] == 28
        a.assert_waterfall_conserved(settled)

    def test_no_member_is_credited_and_the_row_still_completes(
        self, api, terminated_before_distribution_setup
    ):
        """PRD §3.9: "Every eligible member's `fee_credit_balance_cents` is then
        credited by that member's `share_cents`, incrementing each member's `version` by
        one, the distribution's `status` becomes `DISTRIBUTED`, and its `version`
        increments by one."
        PRD §3.9: "The identity `member_share_total_cents` plus `undistributed_cents`
        plus `gpo_retained_cents` equals `gross_pool_cents` holds on every distributed
        row."

        Design: Difficulty/boundary_precision_check/distribution_with_empty_eligible_member_set
        """
        setup = terminated_before_distribution_setup

        distributed = distribute_distribution(api, setup["distribution"]["id"])

        assert distributed["status"] == "DISTRIBUTED"
        assert read_member(api, setup["member"]["id"])["fee_credit_balance_cents"] == 0


class TestEvidenceEndorsementAtTheExactThreshold:
    """The comparison reads the rounded weighted score, not the raw weighted sum."""

    def test_a_dossier_one_hundredth_below_the_threshold_is_refused_endorsement(
        self, api, borderline_dossier_setup
    ):
        """PRD §3.2: "From the weighted score the server derives
        `conversion_recommendation`: it is `CONVERT` when the weighted score is at least
        7.00 — the threshold is **inclusive**, so a weighted score of exactly 7.00
        recommends conversion — and `DO_NOT_CONVERT` otherwise."
        PRD §3.2: "And the dossier's `weighted_score` must be at least 7.00, or the
        request fails with `ERR_EVIDENCE_SCORE_BELOW_THRESHOLD`."

        Design: Difficulty/boundary_precision_check/evidence_endorse_at_exact_score_threshold
        """
        review = borderline_dossier_setup["review"]
        a.assert_score(review["weighted_score"], 6.99)
        assert review["conversion_recommendation"] == "DO_NOT_CONVERT"

        validate_error(
            api.endorse_review(review["id"], {}, headers=clinical_reviewer_2_headers()),
            ERR_EVIDENCE_SCORE_BELOW_THRESHOLD,
            409,
        )

        after = read_evidence_review(api, review["id"])
        assert after["status"] == "UNDER_REVIEW"
        a.assert_score(after["weighted_score"], 6.99)

    def test_a_rescore_whose_unrounded_sum_is_below_the_threshold_rounds_onto_it(
        self, api, borderline_dossier_setup
    ):
        """PRD §3.2: "In arithmetic terms, the efficacy score is multiplied by 0.40, the
        safety score by 0.35, and the supply-resilience score by 0.25; those three
        products are added together **unrounded**, and the single resulting sum is then
        rounded half up to exactly two decimal places, once."
        PRD §3.2: "Scores can be revised in place while the dossier is `UNDER_REVIEW` or
        `REVISION_REQUESTED`: the revising reviewer submits all three of
        `clinical_efficacy_score`, `safety_score` and `supply_resilience_score`, which
        replace the stored values, and `weighted_score` and `conversion_recommendation`
        are recomputed under the same weighting."
        PRD §3.2: "A score revision increments the dossier's `version` by one and does
        not change its `status`."
        PRD §2.5: "Every division in this specification is performed in exact decimal
        arithmetic and rounded **half up** — a value exactly at the midpoint rounds away
        from zero, so 8508.5 cents becomes 8509 cents and 7.0050 becomes 7.01."

        Design: Difficulty/boundary_precision_check/evidence_endorse_at_exact_score_threshold
        """
        review = borderline_dossier_setup["review"]
        assert review["version"] == 1

        revised = validate_success(
            api.patch_review_scores(
                review["id"],
                f.scores_payload(7.00, 6.90, 7.12),
                headers=clinical_reviewer_headers(),
            ),
            200,
        )

        a.assert_score(revised["weighted_score"], 7.00)
        assert revised["conversion_recommendation"] == "CONVERT"
        assert revised["status"] == "UNDER_REVIEW"
        assert revised["version"] == 2

    def test_the_rounded_threshold_score_endorses_and_opens_the_conversion_gate(
        self, api, borderline_dossier_setup
    ):
        """PRD §3.2: "An accepted endorsement sets `status` to `ENDORSED`, records
        `endorsed_by_user_id` as the endorsing reviewer's `X-User-ID`, and then reaches
        across to the parent contract: `evidence_endorsed` is recomputed and the
        contract's `version` increments by one."
        PRD §3.1: "when `requires_clinical_review` is true it additionally demands that
        `evidence_endorsed` be true and that at least one evidence review naming this
        contract be in `ENDORSED` status with a `conversion_recommendation` of `CONVERT`;
        failing that, the attempt returns `ERR_CLINICAL_REVIEW_NOT_ENDORSED`."

        Design: Difficulty/boundary_precision_check/evidence_endorse_at_exact_score_threshold
        """
        setup = borderline_dossier_setup
        validate_success(
            api.patch_review_scores(
                setup["review"]["id"],
                f.scores_payload(7.00, 6.90, 7.12),
                headers=clinical_reviewer_headers(),
            ),
            200,
        )

        endorsed = validate_success(
            api.endorse_review(
                setup["review"]["id"], {}, headers=clinical_reviewer_2_headers()
            ),
            200,
        )

        assert endorsed["status"] == "ENDORSED"
        assert endorsed["endorsed_by_user_id"] == CLINICAL_REVIEWER_2
        assert read_contract(api, setup["contract"]["id"])["evidence_endorsed"] is True

        activated = activate_contract(api, setup["contract"]["id"])
        assert activated["status"] == "ACTIVE"
