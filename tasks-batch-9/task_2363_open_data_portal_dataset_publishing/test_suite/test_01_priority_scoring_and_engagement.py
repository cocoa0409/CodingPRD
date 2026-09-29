"""
Prioritisation: engagement measurement, the declared/observed demand variants and
the single half-up rounding of the finished weighted sum.
"""

from test_helpers import (
    ANONYMOUS_HEADERS,
    assert_money,
    assert_priority,
    assert_two_decimals,
    fixtures,
    validate_success,
)

# Three epochs whose positional weighting lands engagement on a clean 33.12.
DIVERGENCE_EPOCHS = [
    {"epoch_index": 1, "api_call_count": 1000, "download_count": 200},
    {"epoch_index": 2, "api_call_count": 2000, "download_count": 500},
    {"epoch_index": 3, "api_call_count": 3000, "download_count": 1000},
]

# Three epochs whose weighted terms sum to 48.8550 — a true third-decimal tie.
HALF_UP_EPOCHS = [
    {"epoch_index": 1, "api_call_count": 1125, "download_count": 500},
    {"epoch_index": 2, "api_call_count": 2000, "download_count": 500},
    {"epoch_index": 3, "api_call_count": 3000, "download_count": 1000},
]


def test_engagement_index_weights_the_top_three_epochs_positionally(api):
    """Engagement is measured from the three newest epochs under fixed positional weights.

    The PRD: "Those values are then combined positionally, with the highest-indexed
    epoch weighted 0.50, the next 0.30 and the next 0.20." and "The weighted total is
    divided by 50, rounded half up to two decimal places once, and capped at 100.00,
    giving `engagement_index`; `observed_demand_score` is set to the same value."

    With epoch values 680, 1400 and 2200 the weighted total is 1656, and 1656 / 50 is
    33.12, which both `engagement_index` and `observed_demand_score` must carry.

    Design: Difficulty/dual_variant_calc/priority_score_declared_vs_observed_divergence_after_publish
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    fixtures.report_usage_epochs(ctx["dataset_id"], DIVERGENCE_EPOCHS, api=api)

    analytics = validate_success(
        api.get_dataset_analytics(ctx["dataset_id"], ANONYMOUS_HEADERS)
    )

    assert_money(analytics["engagement_index"], 33.12, "engagement_index")
    assert_money(analytics["observed_demand_score"], 33.12, "observed_demand_score")
    assert analytics["usage_epoch_count"] == 3, (
        f"Expected 3 recorded epochs, got {analytics['usage_epoch_count']}"
    )


def test_published_dataset_scores_on_observed_demand_not_declared_demand(api):
    """After publication the demand term switches to the measured figure.

    The PRD: "Once the dataset's `publication_status` is `PUBLISHED` or
    `UNDER_REMEDIATION`, the demand term becomes the measured `observed_demand_score`
    and the variant is `AS_OBSERVED`." Both variants are exposed side by side, so the
    divergence is directly observable: the declared reading is 0.45 x 92.00 plus 0.35 x
    96.00 = 75.00, while the observed reading is 0.45 x 33.12 plus 0.35 x 96.00 =
    48.50. The dataset is `PUBLISHED`, so 48.50 is the score that governs, the variant
    is `AS_OBSERVED`, and the tier falls to `TIER_3` rather than staying at `TIER_1`.

    Design: Difficulty/dual_variant_calc/priority_score_declared_vs_observed_divergence_after_publish
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    fixtures.report_usage_epochs(ctx["dataset_id"], DIVERGENCE_EPOCHS, api=api)

    analytics = validate_success(
        api.get_dataset_analytics(ctx["dataset_id"], ANONYMOUS_HEADERS)
    )

    assert_money(analytics["priority_score_as_declared"], 75.00, "priority_score_as_declared")
    assert_money(analytics["priority_score_as_observed"], 48.50, "priority_score_as_observed")
    assert_priority(
        analytics,
        priority_score=48.50,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )
    divergence = float(analytics["priority_score_as_declared"]) - float(
        analytics["priority_score_as_observed"]
    )
    assert_money(divergence, 26.50, "declared-minus-observed divergence")


def test_dataset_row_carries_the_observed_score_recomputed_by_usage_reporting(api):
    """The stored dataset row is re-scored by usage reporting, not only the computed read.

    The PRD: "Recording an epoch recomputes `engagement_index` and
    `observed_demand_score`, then recomputes `priority_score` under the variant that
    the dataset's current `publication_status` selects". The dataset itself must
    therefore mirror the observed reading of 48.50 at `TIER_3`, with the measured
    engagement of 33.12 persisted on the row.

    Design: Difficulty/dual_variant_calc/priority_score_declared_vs_observed_divergence_after_publish
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    dataset = fixtures.report_usage_epochs(ctx["dataset_id"], DIVERGENCE_EPOCHS, api=api)

    assert_money(dataset["engagement_index"], 33.12, "engagement_index")
    assert_money(dataset["observed_demand_score"], 33.12, "observed_demand_score")
    assert_priority(
        dataset,
        priority_score=48.50,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )

    reread = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_priority(reread, priority_score=48.50, priority_tier="TIER_3")


def test_priority_sum_rounds_half_up_once_at_the_third_decimal(api):
    """A weighted sum of exactly 48.8550 must round half up to 48.86.

    The PRD: "The three weighted terms are then added together and the finished sum is
    rounded half up to two decimal places exactly once, never term by term, giving
    `priority_score`." and "The priority score is rounded once, applied to the finished
    weighted sum and never to the individual weighted terms." Engagement here is
    1695 / 50 = 33.90, so the demand term is 15.2550 and the policy term is 33.6000;
    truncating or rounding the terms first would yield 48.85.

    Design: Difficulty/boundary_precision_check/priority_score_half_up_at_third_decimal
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    fixtures.report_usage_epochs(ctx["dataset_id"], HALF_UP_EPOCHS, api=api)

    analytics = validate_success(
        api.get_dataset_analytics(ctx["dataset_id"], ANONYMOUS_HEADERS)
    )

    assert_money(analytics["engagement_index"], 33.90, "engagement_index")
    assert_money(analytics["priority_score_as_observed"], 48.86, "priority_score_as_observed")
    assert_priority(
        analytics,
        priority_score=48.86,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )
    assert_two_decimals(analytics["priority_score"], "priority_score")


def test_half_up_priority_is_persisted_on_the_dataset_with_every_epoch_counted(api):
    """The rounded-once figure is the one stored on the dataset row.

    The PRD: "From that score, `priority_tier` follows on inclusive thresholds:
    `TIER_1` at 75.00 or above, `TIER_2` at 50.00 or above, and `TIER_3` otherwise."
    48.86 sits below 50.00, so the dataset lands in `TIER_3` even though its declared
    reading would have been `TIER_1`, and all three epochs stay recorded against it.

    Design: Difficulty/boundary_precision_check/priority_score_half_up_at_third_decimal
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    dataset = fixtures.report_usage_epochs(ctx["dataset_id"], HALF_UP_EPOCHS, api=api)

    assert_money(dataset["priority_score"], 48.86, "priority_score")
    assert_priority(dataset, priority_score_variant="AS_OBSERVED", priority_tier="TIER_3")
    assert len(dataset["usage_epochs"]) == 3, (
        f"Expected three usage epochs on the dataset, got {len(dataset['usage_epochs'])}"
    )

    analytics = fixtures.read_analytics(ctx["dataset_id"], api=api)
    assert analytics["usage_epoch_count"] == 3, (
        f"Expected usage_epoch_count 3, got {analytics['usage_epoch_count']}"
    )
