"""The retraining urgency snapshot and its single-pass tier selection."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    assert_deployment_state,
    assert_drift_outcome,
    assert_skew_outcome,
    assert_urgency_snapshot,
)
from test_helpers.api_client import ApiClient
from test_helpers.fixtures import (
    build_stack,
    close_window,
    create_drift_report,
    create_skew_check,
    record_window,
    set_clock,
)
from test_helpers.test_users import MLE_1

_TRAINING_STATS = {
    "amount": {"mean": 0.8000},
    "tenure_days": {"mean": 30.0000},
    "zscore": {"mean": 1.0000},
}
_SERVING_STATS = {
    "amount": {"mean": 0.9200},
    "tenure_days": {"mean": 30.0000},
    "zscore": {"mean": 1.0000},
}


def _breach_with_warn_skew(api: ApiClient) -> tuple:
    """A WARN skew check and a WARN drift breach 56 whole days after approval."""
    stack = build_stack(api, ramps=1)
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="DISTRIBUTION",
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
        observed_bin_proportions=[0.10, 0.15, 0.20, 0.25, 0.30],
    )
    skew = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        dict(_TRAINING_STATS),
        dict(_SERVING_STATS),
    )
    set_clock(api, "2026-09-26T00:00:00Z")
    close_window(api, window["id"])
    report = create_drift_report(
        api, window["id"], MLE_1, baseline_mode="TRAINING_BASELINE"
    )
    triggers = get_success_data(
        api.list_retraining_triggers(MLE_1, {"drift_report_id": report["id"]})
    )
    assert len(triggers) == 1, f"expected one trigger, got {len(triggers)}"
    return stack, skew, report, triggers[0]


def test_base_urgency_sums_drift_skew_and_staleness(api):
    """The base urgency adds the three contributions and rounds once.

    PRD 3.6: the drift contribution is "120 multiplied by the drift index of the
    most recent breaching report", the skew contribution is "80 multiplied by
    the amount by which the latest skew ratio exceeds 1.0, floored at 0", and
    the staleness contribution is "0.5 for every whole day since the version's
    approved_at". The sum is rounded to two decimals as base_urgency.

    Design: Difficulty/combinatorial_formula/retraining_urgency_tier_selected_from_base_urgency_only
    """
    _, skew, report, trigger = _breach_with_warn_skew(api)

    assert_skew_outcome(
        skew, max_skew_ratio=1.1500, status="WARN", max_skew_feature="amount"
    )
    assert_drift_outcome(
        report, drift_index=0.1354, severity="WARN", status="BREACHED"
    )
    assert trigger["skew_check_id"] == skew["id"]
    assert_urgency_snapshot(trigger, base_urgency=56.25)


def test_escalation_tier_is_selected_from_the_base_urgency_only(api):
    """The tier is chosen once, from the base, never from the total.

    PRD 3.6: "the escalation tier is selected from the base urgency alone", and
    the total urgency is "the base multiplied by one plus the tier bonus
    expressed as a percentage, rounded to two decimals and capped at 100.00". A
    base of 56.25 selects the 25 per cent tier and lands on 70.31, which is
    below the 75.00 CRITICAL band floor.

    Design: Difficulty/combinatorial_formula/retraining_urgency_tier_selected_from_base_urgency_only
    """
    _, _, _, trigger = _breach_with_warn_skew(api)

    assert_urgency_snapshot(
        trigger,
        base_urgency=56.25,
        escalation_tier_bonus_pct=25,
        total_urgency=70.31,
        priority_band="HIGH",
    )
    assert trigger["total_urgency"] != 78.75
    assert trigger["priority_band"] != "CRITICAL"


def test_the_snapshot_records_the_retrain_flag_and_its_staleness_horizon(api):
    """The trigger row also carries the retrain flag and the stale horizon.

    PRD 3.6: "retrain_required is true when the total urgency is 45.00 or
    above", a newly raised trigger starts in PROPOSED, and "stale_after is the
    raising instant plus 90 whole days". PRD 3.6 also drives the WARN cascade's
    health hop, moving a HEALTHY deployment to DEGRADED.

    Design: Difficulty/combinatorial_formula/retraining_urgency_tier_selected_from_base_urgency_only
    """
    stack, _, _, trigger = _breach_with_warn_skew(api)

    assert_urgency_snapshot(
        trigger, retrain_required=True, stale_after="2026-12-25T00:00:00Z"
    )
    assert trigger["status"] == "PROPOSED"

    model = get_success_data(api.get_model(stack.model_id, MLE_1))
    assert model["open_retraining_trigger_count"] == 1

    deployment = get_success_data(api.get_deployment(stack.deployment_id, MLE_1))
    assert_deployment_state(deployment, health_state="DEGRADED")
