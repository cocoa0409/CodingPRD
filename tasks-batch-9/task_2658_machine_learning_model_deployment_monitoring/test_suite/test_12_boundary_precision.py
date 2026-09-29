"""Metrics sitting exactly on a threshold, and one unit below it."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_deployment_state,
    assert_drift_outcome,
    assert_health_score,
    assert_promotion_outcome,
    assert_skew_outcome,
    assert_two_dp,
    assert_urgency_snapshot,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_NO_LABELED_PREDICTIONS
from test_helpers.factories import build_conclude_payload
from test_helpers.fixtures import (
    Stack,
    build_evaluation_arms,
    build_stack,
    close_window,
    create_drift_report,
    create_skew_check,
    ramp,
    record_window,
    schedule_evaluation,
    set_clock,
)
from test_helpers.test_users import MLE_1, RELIABILITY_1

_TRAINING = {
    "amount": {"mean": 0.8000},
    "tenure_days": {"mean": 30.0000},
    "zscore": {"mean": 1.0000},
}


def _serving(amount_mean: float) -> dict:
    """Serving means whose only moving part is the `amount` feature."""
    return {
        "amount": {"mean": amount_mean},
        "tenure_days": {"mean": 31.5000},
        "zscore": {"mean": 1.0000},
    }


def _check(api: ApiClient, stack: Stack, amount_mean: float) -> dict:
    return create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        _TRAINING,
        _serving(amount_mean),
    )


def test_the_block_threshold_is_reached_but_not_crossed(api):
    """1.2500 blocks and 1.2499 only warns.

    PRD 3.6: the skew ratio is "rounded half up to 4 decimals" and the check
    "fails with status FAIL_SKEW when the maximum ratio is 1.2500 or above and
    warns when it is 1.1000 or above", so both comparisons include their
    threshold. A serving mean of 0.9999 gives 1.249875, which rounds to 1.2499.

    Design: Difficulty/boundary_precision_check/skew_ratio_exactly_at_block_threshold_on_skew_checks
    """
    stack = build_stack(api, ramps=1)

    at_threshold = _check(api, stack, 1.0000)
    assert_skew_outcome(
        at_threshold,
        max_skew_ratio=1.2500,
        max_skew_feature="amount",
        status="FAIL_SKEW",
    )
    assert at_threshold["missing_features"] == []

    just_below = _check(api, stack, 0.9999)
    assert_skew_outcome(just_below, max_skew_ratio=1.2499, status="WARN")
    assert just_below["status"] != "FAIL_SKEW"


def test_the_warn_threshold_is_reached_but_not_crossed(api):
    """1.1000 warns and 1.0999 passes.

    PRD 3.6 puts the warn comparison at "1.1000 or above" and takes the maximum
    ratio "across every feature present in both maps", so the winning feature is
    still `amount` at 1.0999 against `tenure_days` at 1.0500.

    Design: Difficulty/boundary_precision_check/skew_ratio_exactly_at_block_threshold_on_skew_checks
    """
    stack = build_stack(api, ramps=1)

    at_warn = _check(api, stack, 0.8800)
    assert_skew_outcome(at_warn, max_skew_ratio=1.1000, status="WARN")

    just_below_warn = _check(api, stack, 0.8799)
    assert_skew_outcome(
        just_below_warn,
        max_skew_ratio=1.0999,
        max_skew_feature="amount",
        status="PASS",
    )


def test_only_the_failing_check_raises_a_trigger_on_a_tier_floor(api):
    """The raised urgency lands exactly on an escalation tier floor.

    PRD 3.6 raises a retraining trigger from a skew check only when it is
    FAIL_SKEW. PRD 3.6's urgency arithmetic gives 80 times the excess of the
    ratio over 1.0 with no drift and no staleness, and the escalation table is
    read with "at or above" floors, so 20.00 takes the floor-20 tier rather than
    the tier below it.

    Design: Difficulty/boundary_precision_check/skew_ratio_exactly_at_block_threshold_on_skew_checks
    """
    stack = build_stack(api, ramps=1)
    at_threshold = _check(api, stack, 1.0000)
    just_below = _check(api, stack, 0.9999)

    raised = get_success_data(
        api.list_retraining_triggers(MLE_1, {"skew_check_id": at_threshold["id"]})
    )
    assert len(raised) == 1
    trigger = raised[0]
    assert trigger["skew_check_id"] == at_threshold["id"]
    assert trigger["drift_report_id"] is None
    assert_urgency_snapshot(
        trigger,
        base_urgency=20.00,
        escalation_tier_bonus_pct=10,
        total_urgency=22.00,
        priority_band="LOW",
        retrain_required=False,
    )

    silent = get_success_data(
        api.list_retraining_triggers(MLE_1, {"skew_check_id": just_below["id"]})
    )
    assert silent == [], "a WARN skew check raises no retraining trigger"


def test_the_most_recent_check_is_the_one_the_ramp_gate_reads(api):
    """A later PASS check supersedes an earlier FAIL_SKEW one.

    PRD 3.4 gates a ramp on "the most recent skew check for the deployment,
    ordered by checked_at descending and then created_at descending", so a
    superseded failure no longer blocks.

    Design: Difficulty/boundary_precision_check/skew_ratio_exactly_at_block_threshold_on_skew_checks
    """
    stack = build_stack(api, ramps=1)
    _check(api, stack, 1.0000)
    _check(api, stack, 0.9999)
    _check(api, stack, 0.8800)
    passing = _check(api, stack, 0.8799)
    assert passing["status"] == "PASS"

    stepped = ramp(api, stack.deployment_id)
    assert_deployment_state(stepped, traffic_pct=15.00, ramp_step_index=2)


# ─── Zero, one and exactly the minimum labelled predictions ───


def _mature_collecting_evaluation(api: ApiClient) -> tuple:
    """A COLLECTING evaluation reserving 1,000 samples, past its end instant."""
    arms = build_evaluation_arms(api)
    evaluation = schedule_evaluation(
        api,
        arms.stack.model_id,
        arms.champion_deployment_id,
        arms.challenger_deployment_id,
        RELIABILITY_1,
    )
    get_success_data(
        api.start_challenger_evaluation(evaluation["id"], RELIABILITY_1)
    )
    reserved = get_success_data(
        api.get_model_version(arms.challenger_version_id, RELIABILITY_1)
    )
    assert_version_state(reserved, evaluation_sample_budget=4000)
    set_clock(api, "2026-08-20T00:00:00Z")
    return arms, evaluation


def test_zero_labelled_predictions_is_rejected_and_moves_nothing(api):
    """Zero is not folded into the insufficient-labels verdict.

    PRD 3.7: concluding is "rejected with ERR_NO_LABELED_PREDICTIONS when
    labeled_prediction_count is 0 — a verdict on zero labelled predictions is not
    a verdict", and PRD 2.7 makes that a 422 at the very end of the ladder. A
    rejected request writes nothing, so the reservation is still held.

    Design: Difficulty/boundary_precision_check/conclude_at_zero_one_and_exactly_min_labeled_predictions
    """
    arms, evaluation = _mature_collecting_evaluation(api)

    refused = api.conclude_challenger_evaluation(
        evaluation["id"], build_conclude_payload(0), RELIABILITY_1
    )
    validate_error(refused, ERR_NO_LABELED_PREDICTIONS)

    unchanged = get_success_data(
        api.get_challenger_evaluation(evaluation["id"], RELIABILITY_1)
    )
    assert_promotion_outcome(unchanged, status="COLLECTING", criteria_failures=[])
    assert unchanged["promotion_score"] is None
    version = get_success_data(
        api.get_model_version(arms.challenger_version_id, RELIABILITY_1)
    )
    assert_version_state(version, evaluation_sample_budget=4000)


def test_one_label_is_legal_and_exactly_the_minimum_promotes(api):
    """One label is a verdict; one thousand labels is a sufficient one.

    PRD 3.7 accepts a "labeled_prediction_count of at least 0" and records
    INSUFFICIENT_LABELS when the count is "below 1,000", so 1 is a legal input
    that still fails the criterion while exactly 1,000 satisfies it. With the
    label criterion met and a score above the minimum the fork reaches PROMOTED,
    which PRD 3.7 says writes the champion pointer and its promotion instant.

    Design: Difficulty/boundary_precision_check/conclude_at_zero_one_and_exactly_min_labeled_predictions
    """
    arms, evaluation = _mature_collecting_evaluation(api)
    evaluation_id = evaluation["id"]

    one_label = get_success_data(
        api.conclude_challenger_evaluation(
            evaluation_id, build_conclude_payload(1), RELIABILITY_1
        )
    )
    assert_promotion_outcome(
        one_label,
        status="INCONCLUSIVE",
        criteria_failures=["INSUFFICIENT_LABELS"],
        promotion_score=0.0437,
    )

    extended = get_success_data(
        api.extend_challenger_evaluation(evaluation_id, RELIABILITY_1)
    )
    assert extended["evaluation_ends_at"] == "2026-08-22T00:00:00Z"
    assert extended["reserved_samples"] == 1500

    set_clock(api, "2026-08-23T00:00:00Z")
    at_minimum = get_success_data(
        api.conclude_challenger_evaluation(
            evaluation_id, build_conclude_payload(1000), RELIABILITY_1
        )
    )
    assert_promotion_outcome(
        at_minimum, status="PROMOTED", criteria_failures=[]
    )

    model = get_success_data(api.get_model(arms.stack.model_id, RELIABILITY_1))
    assert model["champion_version_id"] == arms.challenger_version_id
    assert model["champion_promoted_at"] == "2026-08-23T00:00:00Z"


# ─── A final health score exactly at the recovery minimum ───

_LATENCY_JUST_OVER = 251
_LATENCY_AT_THRESHOLD = 250


def _degraded_at_fifteen(api: ApiClient) -> Stack:
    """A deployment RAMPING at 15.00 whose health a WARN breach has degraded."""
    stack = build_stack(api, ramps=2)
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="DISTRIBUTION",
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
        prediction_count=8000,
        labeled_prediction_count=4000,
        correct_labeled_count=3400,
        positive_rate=0.30,
        p95_latency_ms=200,
        observed_bin_proportions=[0.10, 0.15, 0.20, 0.25, 0.30],
    )
    set_clock(api, "2026-08-03T00:00:00Z")
    close_window(api, window["id"])
    report = create_drift_report(
        api, window["id"], MLE_1, baseline_mode="TRAINING_BASELINE"
    )
    assert_drift_outcome(report, drift_index=0.1354, severity="WARN")
    deployment = get_success_data(api.get_deployment(stack.deployment_id, MLE_1))
    assert_deployment_state(
        deployment, rollout_state="RAMPING", health_state="DEGRADED"
    )
    return stack


def _performance_window(
    api: ApiClient,
    stack: Stack,
    window_start: str,
    window_end: str,
    p95_latency_ms: int,
) -> dict:
    """A fully labelled window whose only moving part is the tail latency."""
    return record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="PERFORMANCE",
        window_start=window_start,
        window_end=window_end,
        prediction_count=10000,
        labeled_prediction_count=10000,
        correct_labeled_count=8000,
        positive_rate=0.34,
        p95_latency_ms=p95_latency_ms,
        observed_bin_proportions=[0.20, 0.20, 0.20, 0.20, 0.20],
    )


def test_a_score_just_below_the_recovery_minimum_leaves_health_degraded(api):
    """One millisecond of tail latency costs the recovery.

    PRD 3.5 recovers a DEGRADED deployment only when the FINAL score is "80.00 or
    above", and PRD 3.5's arithmetic scales the latency term by the ratio of the
    baseline tail latency to the observed one. Because the window is fully
    labelled the imputation term is zero, so the PROVISIONAL and FINAL variants
    agree.

    Design: Difficulty/boundary_precision_check/health_recovery_exactly_at_minimum_score_on_window_close
    """
    stack = _degraded_at_fifteen(api)

    window = _performance_window(
        api,
        stack,
        "2026-08-03T06:00:00Z",
        "2026-08-03T12:00:00Z",
        _LATENCY_JUST_OVER,
    )
    assert_health_score(window, health_score=79.92, variant="PROVISIONAL")

    set_clock(api, "2026-08-04T00:00:00Z")
    closed = close_window(api, window["id"])
    assert_health_score(
        closed, health_score=79.92, variant="FINAL", baseline_delta_pct=-2.08
    )

    deployment = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(
        deployment,
        rollout_state="RAMPING",
        health_state="DEGRADED",
        traffic_pct=15.00,
    )


def test_a_score_exactly_at_the_recovery_minimum_restores_health(api):
    """80.00 recovers because the comparison includes its threshold.

    PRD 3.5 recovers on "80.00 or above" and rejects a close with
    ERR_WINDOW_NOT_ENDED only "unless window_end is at or before the logical
    clock's present value", so a window ending exactly now may be closed. The
    recovery touches the health dimension alone.

    Design: Difficulty/boundary_precision_check/health_recovery_exactly_at_minimum_score_on_window_close
    """
    stack = _degraded_at_fifteen(api)
    just_below = _performance_window(
        api,
        stack,
        "2026-08-03T06:00:00Z",
        "2026-08-03T12:00:00Z",
        _LATENCY_JUST_OVER,
    )
    set_clock(api, "2026-08-04T00:00:00Z")
    close_window(api, just_below["id"])

    at_threshold = _performance_window(
        api,
        stack,
        "2026-08-03T18:00:00Z",
        "2026-08-04T00:00:00Z",
        _LATENCY_AT_THRESHOLD,
    )
    assert_health_score(at_threshold, health_score=80.00, variant="PROVISIONAL")

    closed = close_window(api, at_threshold["id"])
    assert_health_score(closed, health_score=80.00, variant="FINAL")

    deployment = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(
        deployment,
        rollout_state="RAMPING",
        health_state="HEALTHY",
        traffic_pct=15.00,
    )
    assert_two_dp(
        deployment["health_score_final"], 80.00, "health_score_final"
    )
    assert_two_dp(
        deployment["health_score_provisional"], 80.00, "health_score_provisional"
    )
