"""The consensus index: its two mode variants and its band boundaries."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def test_unweighted_mode_counts_every_review_equally():
    """The first manuscript is banded from the plain mean of its two recommendations.

    PRD: "Under the journal's `UNWEIGHTED` mode, the index is the sum of those values divided by the number of reviews in the set, rounded half up to 2 decimal places, so a barely-credible reviewer moves the index exactly as much as an exemplary one."

    Design: Difficulty/dual_variant_calc/consensus_index_unweighted_vs_reliability_weighted_category_flip
    """
    world = fx.setup_consensus_variant_pair()
    decision = world["unweighted_decision"]

    a.assert_fields(
        decision,
        consensus_mode="UNWEIGHTED",
        auto_category="MINOR_REVISION",
        reviews_counted=2,
    )
    a.assert_score_equals(decision["consensus_index"], 3.00, "consensus_index")
    assert fx.get_manuscript(world["m1"]["id"])["status"] == "REVISION_REQUESTED"


def test_reliability_weighted_mode_flips_the_same_recommendation_pair_to_accept():
    """The identical {ACCEPT, MAJOR_REVISION} pair lands in a higher band once weights apply.

    PRD: "Under `RELIABILITY_WEIGHTED` mode, the index is the sum over the set of each review's recommendation value multiplied by that review's frozen `reliability_weight`, divided by the sum of those same weights, rounded half up to 2 decimal places — so the identical set of reviews can land in a different band than it would have unweighted."

    Design: Difficulty/dual_variant_calc/consensus_index_unweighted_vs_reliability_weighted_category_flip
    """
    world = fx.setup_consensus_variant_pair()

    decision = fx.issue_decision(
        world["m2"]["id"],
        world["handling_headers"],
        editorial_note="Reliability-weighted consensus decision",
    )

    a.assert_fields(
        decision,
        consensus_mode="RELIABILITY_WEIGHTED",
        auto_category="ACCEPT",
        reviews_counted=2,
    )
    a.assert_score_equals(decision["consensus_index"], 3.54, "consensus_index")
    assert fx.get_manuscript(world["m2"]["id"])["status"] == "IN_PRODUCTION"


def test_each_review_carries_the_weight_frozen_at_its_own_submission():
    """The weighted index draws on three different frozen weights from two reviewers.

    PRD: "Only the `ROLLING` variant is consulted by this guard, by the reviewer selector's ranking, and by the frozen `reliability_weight`; the `LIFETIME` variant is reported for audit and used for nothing else."

    Design: Difficulty/dual_variant_calc/consensus_index_unweighted_vs_reliability_weighted_category_flip
    """
    world = fx.setup_consensus_variant_pair()

    a.assert_weight_equals(world["review_strong_2"]["reliability_weight"], 1.0000)
    a.assert_weight_equals(world["review_weak_1"]["reliability_weight"], 0.3250)
    a.assert_weight_equals(world["review_weak_2"]["reliability_weight"], 0.3000)
    assert world["review_weak_1"]["days_late"] == 4
    assert world["review_weak_2"]["days_late"] == 4

    weak = fx.get_reviewer(world["weak_reviewer"]["id"])
    a.assert_score_equals(
        weak["reliability_score_rolling"], 30.00, "reliability_score_rolling"
    )
    assert weak["status"] == "PROBATION"


def test_index_of_exactly_two_point_five_zero_resolves_to_minor_revision():
    """The inclusive lower bound puts the boundary value in the higher band.

    PRD: "An index of exactly 2.50 therefore resolves to `MINOR_REVISION`."

    Design: Difficulty/boundary_precision_check/consensus_index_exactly_at_minor_threshold_resolves_minor_revision
    """
    world = fx.setup_decision_pending(
        recommendations=("MINOR_REVISION", "MAJOR_REVISION")
    )

    decision = fx.issue_decision(
        world["manuscript"]["id"],
        world["handling_headers"],
        editorial_note="Boundary consensus decision",
    )

    a.assert_score_equals(decision["consensus_index"], 2.50, "consensus_index")
    a.assert_fields(
        decision,
        auto_category="MINOR_REVISION",
        category="MINOR_REVISION",
        category_source="AUTO",
        reviews_counted=2,
    )
    assert decision["auto_category"] != "MAJOR_REVISION"


def test_boundary_index_is_copied_onto_the_manuscript_with_its_band():
    """The manuscript keeps the boundary index and follows the revision branch.

    PRD: "Regardless of category, the manuscript's `consensus_index_at_last_decision` is set to this decision's `consensus_index`, its `decision_count` rises by 1, and its `version` advances by 1."

    Design: Difficulty/boundary_precision_check/consensus_index_exactly_at_minor_threshold_resolves_minor_revision
    """
    world = fx.setup_decision_pending(
        recommendations=("MINOR_REVISION", "MAJOR_REVISION")
    )

    fx.issue_decision(
        world["manuscript"]["id"],
        world["handling_headers"],
        editorial_note="Boundary consensus decision",
    )

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    assert manuscript["status"] == "REVISION_REQUESTED"
    a.assert_score_equals(
        manuscript["consensus_index_at_last_decision"],
        2.50,
        "consensus_index_at_last_decision",
    )
