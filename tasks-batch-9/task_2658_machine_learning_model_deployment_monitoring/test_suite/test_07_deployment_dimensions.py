"""The two independent state dimensions a deployment carries."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    assert_deployment_state,
    assert_drift_outcome,
    assert_health_score,
    assert_ramp_step_row,
)
from test_helpers.api_client import ApiClient
from test_helpers.fixtures import (
    Stack,
    build_stack,
    close_window,
    create_drift_report,
    ledger_rows,
    ramp,
    record_window,
    rollout,
    set_clock,
)
from test_helpers.test_users import MLE_1, RELIABILITY_1


def _degraded_while_ramping(api: ApiClient) -> Stack:
    """A deployment RAMPING at 15.00 that a WARN drift report has degraded."""
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
    assert_drift_outcome(report, severity="WARN")
    return stack


def test_a_warn_drift_report_moves_only_the_health_dimension(api):
    """A drift breach degrades health and leaves the rollout untouched.

    PRD 3.6: a WARN breach moves the deployment's health_state "from HEALTHY to
    DEGRADED"; the cascade named there touches the rollout dimension only for a
    CRITICAL breach. PRD 3.4 keeps traffic and the ramp step index under the ramp
    and rollout-action endpoints.

    Design: Difficulty/non_linear_state_machine/deployment_parallel_rollout_and_health_dimensions
    """
    stack = _degraded_while_ramping(api)

    deployment = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(
        deployment,
        rollout_state="RAMPING",
        health_state="DEGRADED",
        traffic_pct=15.00,
        ramp_step_index=2,
    )


def test_a_degraded_ramp_halves_with_truncation_and_holds_its_index(api):
    """While DEGRADED the planner halves the raw delta and truncates it.

    PRD 3.4: "when the deployment's health_state is DEGRADED the raw delta is
    halved and the result is truncated toward zero at two decimals", and the step
    index "advances only when the new traffic equals the nominal checkpoint
    exactly". The ledger row records the health state that applied to the step.

    Design: Difficulty/non_linear_state_machine/deployment_parallel_rollout_and_health_dimensions
    """
    stack = _degraded_while_ramping(api)

    stepped = ramp(api, stack.deployment_id)
    assert_deployment_state(
        stepped,
        rollout_state="RAMPING",
        health_state="DEGRADED",
        traffic_pct=25.00,
        ramp_step_index=2,
    )

    rows = ledger_rows(api, stack.deployment_id)
    assert_ramp_step_row(
        rows[-1],
        step_index=2,
        delta_pct=10.00,
        to_traffic_pct=25.00,
        reason="RAMP_STEP",
        health_state_at_step="DEGRADED",
    )


def test_hold_moves_only_the_rollout_dimension(api):
    """HOLD is a pure rollout transition.

    PRD 3.4: HOLD "moves a RAMPING deployment to HELD and changes nothing else —
    no traffic moves and no ledger row is written."

    Design: Difficulty/non_linear_state_machine/deployment_parallel_rollout_and_health_dimensions
    """
    stack = _degraded_while_ramping(api)
    ramp(api, stack.deployment_id)
    before = ledger_rows(api, stack.deployment_id)

    held = rollout(api, stack.deployment_id, "HOLD")

    assert_deployment_state(
        held, rollout_state="HELD", health_state="DEGRADED", traffic_pct=25.00
    )
    assert len(ledger_rows(api, stack.deployment_id)) == len(before)


def test_closing_a_performance_window_recovers_health_while_still_held(api):
    """Health recovers through the window-close endpoint, not the rollout one.

    PRD 3.5: closing a PERFORMANCE window "is the only path by which a DEGRADED
    deployment returns to HEALTHY, and only when the FINAL score is 80.00 or
    above". The rollout dimension is untouched by that close.

    Design: Difficulty/non_linear_state_machine/deployment_parallel_rollout_and_health_dimensions
    """
    stack = _degraded_while_ramping(api)
    ramp(api, stack.deployment_id)
    rollout(api, stack.deployment_id, "HOLD")

    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="PERFORMANCE",
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T12:00:00Z",
        prediction_count=10000,
        labeled_prediction_count=10000,
        correct_labeled_count=8800,
        positive_rate=0.30,
        p95_latency_ms=200,
        observed_bin_proportions=[0.20, 0.20, 0.20, 0.20, 0.20],
    )
    set_clock(api, "2026-08-04T00:00:00Z")
    closed = close_window(api, window["id"])
    assert_health_score(closed, health_score=94.60, variant="FINAL")

    deployment = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(
        deployment, rollout_state="HELD", health_state="HEALTHY", traffic_pct=25.00
    )


def test_after_recovery_the_same_ramp_call_is_no_longer_halved(api):
    """One trigger, two arithmetics, decided by the other dimension.

    PRD 3.4: RESUME "moves a HELD deployment back to RAMPING and re-runs the ramp
    preconditions", and the halving applies only while the health_state is
    DEGRADED. The identical ramp call therefore lands exactly on the nominal
    checkpoint once health has recovered, which is what advances the index.

    Design: Difficulty/non_linear_state_machine/deployment_parallel_rollout_and_health_dimensions
    """
    stack = _degraded_while_ramping(api)
    ramp(api, stack.deployment_id)
    rollout(api, stack.deployment_id, "HOLD")
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="PERFORMANCE",
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T12:00:00Z",
        prediction_count=10000,
        labeled_prediction_count=10000,
        correct_labeled_count=8800,
        positive_rate=0.30,
        p95_latency_ms=200,
        observed_bin_proportions=[0.20, 0.20, 0.20, 0.20, 0.20],
    )
    set_clock(api, "2026-08-04T00:00:00Z")
    close_window(api, window["id"])

    resumed = rollout(api, stack.deployment_id, "RESUME")
    assert_deployment_state(
        resumed, rollout_state="RAMPING", health_state="HEALTHY", traffic_pct=25.00
    )

    stepped = ramp(api, stack.deployment_id)
    assert_deployment_state(
        stepped, traffic_pct=35.00, ramp_step_index=3, health_state="HEALTHY"
    )
