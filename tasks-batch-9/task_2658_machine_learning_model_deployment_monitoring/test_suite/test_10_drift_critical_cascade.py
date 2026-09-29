"""The five-hop cascade a critical drift breach opens."""

from typing import List

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_allocated_traffic,
    assert_deployment_state,
    assert_drift_outcome,
    assert_urgency_snapshot,
)
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_HEALTH_CRITICAL_BLOCKED,
    ERR_OPEN_INCIDENT_BLOCKS_ACTION,
)
from test_helpers.factories import build_rollout_action_payload
from test_helpers.fixtures import (
    build_stack,
    close_window,
    create_drift_report,
    record_window,
    set_clock,
)
from test_helpers.test_users import MLE_1, RELIABILITY_1

_CRITICAL_OBSERVED = [0.05, 0.10, 0.15, 0.25, 0.45]
_WARN_OBSERVED = [0.10, 0.15, 0.20, 0.25, 0.30]


def _breach(api: ApiClient, observed: List[float]) -> tuple:
    """Score one closed DISTRIBUTION window against the frozen snapshot."""
    stack = build_stack(api, ramps=2)
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="DISTRIBUTION",
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
        observed_bin_proportions=list(observed),
    )
    set_clock(api, "2026-08-03T00:00:00Z")
    close_window(api, window["id"])
    report = create_drift_report(
        api,
        window["id"],
        MLE_1,
        drift_kind="CONCEPT_DRIFT",
        baseline_mode="TRAINING_BASELINE",
    )
    return stack, report


def test_a_critical_drift_report_raises_a_critical_urgency_trigger(api):
    """Hops one and two: the breach scores CRITICAL and proposes a retraining.

    PRD 3.6: "a drift index of 0.25 or above is CRITICAL", a WARN or CRITICAL
    report "moves to BREACHED", and the first cascade hop "raises a retraining
    trigger in PROPOSED". With no skew check on the deployment the skew
    contribution is exactly zero, leaving the drift and staleness contributions.

    Design: Difficulty/transitive_cascade/drift_report_critical_cascade_depth_five
    """
    stack, report = _breach(api, _CRITICAL_OBSERVED)

    assert_drift_outcome(
        report, drift_index=0.5055, severity="CRITICAL", status="BREACHED"
    )

    triggers = get_success_data(
        api.list_retraining_triggers(MLE_1, {"drift_report_id": report["id"]})
    )
    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger["skew_check_id"] is None
    assert trigger["status"] == "PROPOSED"
    assert_urgency_snapshot(
        trigger,
        base_urgency=61.66,
        escalation_tier_bonus_pct=25,
        total_urgency=77.08,
        priority_band="CRITICAL",
        retrain_required=True,
        stale_after="2026-11-01T00:00:00Z",
    )

    model = get_success_data(api.get_model(stack.model_id, MLE_1))
    assert model["open_retraining_trigger_count"] == 1


def test_a_critical_breach_holds_the_rollout_and_opens_a_drift_incident(api):
    """Hops three, four and five, all inside the one request.

    PRD 3.6: a CRITICAL breach takes the health_state "to CRITICAL", then "a
    RAMPING deployment is moved to HELD", and finally "an incident is opened with
    status OPEN, source DRIFT and severity SEV2". Holding the rollout moves no
    traffic, so the cluster's allocated total is unchanged.

    Design: Difficulty/transitive_cascade/drift_report_critical_cascade_depth_five
    """
    stack, report = _breach(api, _CRITICAL_OBSERVED)

    deployment = get_success_data(api.get_deployment(stack.deployment_id, MLE_1))
    assert_deployment_state(
        deployment,
        health_state="CRITICAL",
        rollout_state="HELD",
        traffic_pct=15.00,
    )

    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 15.00)

    incidents = get_success_data(
        api.list_prediction_incidents(
            RELIABILITY_1, {"deployment_id": stack.deployment_id, "source": "DRIFT"}
        )
    )
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["severity"] == "SEV2"
    assert incident["status"] == "OPEN"
    assert incident["drift_report_id"] == report["id"]
    assert incident["model_version_id"] == stack.version_id
    assert incident["fallback_engaged"] is False
    assert incident["recurrence_count"] == 0


def test_health_critical_outranks_the_open_incident_when_resuming(api):
    """Two ramp preconditions fail together and the earlier one answers.

    PRD 2.7 orders the safety band by listing ERR_HEALTH_CRITICAL_BLOCKED before
    ERR_OPEN_INCIDENT_BLOCKS_ACTION, and PRD 3.4 makes RESUME re-run the ramp
    preconditions. The cascade leaves both conditions true at once.

    Design: Difficulty/transitive_cascade/drift_report_critical_cascade_depth_five
    """
    stack, _ = _breach(api, _CRITICAL_OBSERVED)

    refused = api.rollout_action(
        stack.deployment_id,
        build_rollout_action_payload("RESUME"),
        RELIABILITY_1,
    )
    validate_error(refused, ERR_HEALTH_CRITICAL_BLOCKED)
    assert refused.json()["data"]["error_id"] != ERR_OPEN_INCIDENT_BLOCKS_ACTION


def test_a_warn_breach_stops_after_the_health_hop(api):
    """The cascade's depth is decided by the severity, not by the endpoint.

    PRD 3.6 gates the fourth and fifth hops on a CRITICAL severity: the rollout
    hold and the opened incident are described as CRITICAL-only, while a WARN
    breach reaches only "HEALTHY to DEGRADED".

    Design: Difficulty/transitive_cascade/drift_report_critical_cascade_depth_five
    """
    stack, report = _breach(api, _WARN_OBSERVED)

    assert_drift_outcome(
        report, drift_index=0.1354, severity="WARN", status="BREACHED"
    )

    deployment = get_success_data(api.get_deployment(stack.deployment_id, MLE_1))
    assert_deployment_state(
        deployment,
        health_state="DEGRADED",
        rollout_state="RAMPING",
        traffic_pct=15.00,
    )

    incidents = get_success_data(
        api.list_prediction_incidents(
            RELIABILITY_1, {"deployment_id": stack.deployment_id}
        )
    )
    assert incidents == [], "a WARN breach opens no incident"
