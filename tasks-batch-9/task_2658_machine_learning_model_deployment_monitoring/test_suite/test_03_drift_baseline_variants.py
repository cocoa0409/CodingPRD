"""The two expected-distribution variants of the drift index."""

from typing import List, Tuple

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assert_drift_outcome
from test_helpers.api_client import ApiClient
from test_helpers.fixtures import (
    Stack,
    build_stack,
    create_drift_report,
    record_and_close_window,
)
from test_helpers.test_users import MLE_1

# Four non-touching DISTRIBUTION windows; the fourth is the one scored.
# PRD 3.5 permits exactly one OPEN window per deployment per window_kind, so each
# window is closed (after the clock passes its window_end) before the next is
# recorded; recording all four first would trip ERR_DUPLICATE_OPEN_WINDOW.
_WINDOWS: List[Tuple[str, str, List[float]]] = [
    ("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z", [0.12, 0.16, 0.20, 0.24, 0.28]),
    ("2026-08-03T00:00:00Z", "2026-08-03T06:00:00Z", [0.14, 0.16, 0.20, 0.24, 0.26]),
    ("2026-08-04T00:00:00Z", "2026-08-04T06:00:00Z", [0.10, 0.18, 0.20, 0.26, 0.26]),
    ("2026-08-05T00:00:00Z", "2026-08-05T06:00:00Z", [0.10, 0.15, 0.20, 0.25, 0.30]),
]


def _closed_distribution_history(api: ApiClient) -> Tuple[Stack, str]:
    """Four closed DISTRIBUTION windows over one ramping deployment."""
    stack = build_stack(api, ramps=1)
    window_ids = []
    for start, end, observed in _WINDOWS:
        window = record_and_close_window(
            api,
            stack.deployment_id,
            stack.version_id,
            clock_after=end,
            window_kind="DISTRIBUTION",
            window_start=start,
            window_end=end,
            observed_bin_proportions=list(observed),
        )
        window_ids.append(window["id"])
    return stack, window_ids[-1]


def test_rolling_baseline_averages_the_three_most_recent_closed_windows(api):
    """The rolling variant builds its expectation from recent history.

    PRD 3.6: under ROLLING_BASELINE the eligible pool is "the closed
    DISTRIBUTION windows of the same deployment other than the window being
    scored, ranked by window_end descending then created_at descending", and
    "the first three are averaged element-wise". A severity of NONE means "no
    transition follows".

    Design: Difficulty/dual_variant_calc/drift_index_training_baseline_vs_rolling_baseline
    """
    stack, scored_window_id = _closed_distribution_history(api)

    report = create_drift_report(
        api, scored_window_id, MLE_1, baseline_mode="ROLLING_BASELINE"
    )

    assert_drift_outcome(
        report,
        drift_index=0.0094,
        severity="NONE",
        status="COMPUTED",
        effective_baseline_mode="ROLLING_BASELINE",
        windows_used_count=3,
        expected_bin_proportions=[0.1200, 0.1667, 0.2000, 0.2467, 0.2667],
    )
    assert report["baseline_dataset_id"] is None

    triggers = get_success_data(
        api.list_retraining_triggers(MLE_1, {"model_id": stack.model_id})
    )
    assert triggers == [], "a NONE severity must raise no retraining trigger"


def test_training_baseline_scores_the_same_observation_against_the_snapshot(api):
    """The training variant compares against the frozen snapshot instead.

    PRD 3.6: under TRAINING_BASELINE "the expected distribution is the
    referenced training-data snapshot's baseline_bin_proportions", and a
    severity of WARN or CRITICAL moves the report to BREACHED and raises a
    retraining trigger. The identical observed vector therefore lands in a
    different severity band from the rolling variant.

    Design: Difficulty/dual_variant_calc/drift_index_training_baseline_vs_rolling_baseline
    """
    stack, scored_window_id = _closed_distribution_history(api)

    report = create_drift_report(
        api, scored_window_id, MLE_1, baseline_mode="TRAINING_BASELINE"
    )

    assert_drift_outcome(
        report,
        drift_index=0.1354,
        severity="WARN",
        status="BREACHED",
        effective_baseline_mode="TRAINING_BASELINE",
        windows_used_count=0,
        expected_bin_proportions=[0.2000, 0.2000, 0.2000, 0.2000, 0.2000],
    )
    assert report["baseline_dataset_id"] == stack.dataset_id

    triggers = get_success_data(
        api.list_retraining_triggers(MLE_1, {"drift_report_id": report["id"]})
    )
    assert len(triggers) == 1, "a WARN severity raises exactly one trigger"


def test_the_two_variants_disagree_on_the_severity_band(api):
    """One stored observation lands in two different severity bands.

    PRD 3.6: "the drift index is rounded to four decimals once", the bands are
    "0.25 or above is CRITICAL, 0.10 or above is WARN, and anything lower is
    NONE, both comparisons inclusive". Only the variant matters here: both
    reports read the same window's observed_bin_proportions.

    Design: Difficulty/dual_variant_calc/drift_index_training_baseline_vs_rolling_baseline
    """
    _, scored_window_id = _closed_distribution_history(api)

    rolling = create_drift_report(
        api, scored_window_id, MLE_1, baseline_mode="ROLLING_BASELINE"
    )
    training = create_drift_report(
        api, scored_window_id, MLE_1, baseline_mode="TRAINING_BASELINE"
    )

    assert rolling["monitoring_window_id"] == training["monitoring_window_id"]
    assert round(training["drift_index"] - rolling["drift_index"], 4) == 0.1260
    assert rolling["severity"] == "NONE"
    assert training["severity"] == "WARN"
