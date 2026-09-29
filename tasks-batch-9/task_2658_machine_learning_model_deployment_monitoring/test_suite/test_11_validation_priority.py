"""Pairs of rules that one request violates at once, and which one answers."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_allocated_traffic,
    assert_deployment_state,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_DATASET_NOT_APPROVED,
    ERR_DUPLICATE_OPEN_WINDOW,
    ERR_ENDPOINT_CAPACITY_EXHAUSTED,
    ERR_INVALID_STATE,
    ERR_MONITORING_WINDOW_OVERLAP,
    ERR_OPEN_INCIDENT_BLOCKS_ACTION,
)
from test_helpers.factories import (
    build_dataset_decision_payload,
    build_monitoring_window_payload,
    build_version_decision_payload,
)
from test_helpers.fixtures import (
    build_stack,
    close_window,
    create_draft_dataset,
    create_incident,
    create_model,
    incident_action,
    ledger_rows,
    record_window,
    register_version,
    set_clock,
)
from test_helpers.test_users import (
    APPROVER_1,
    MLE_1,
    RELIABILITY_1,
    STEWARD_1,
    USER_MLE_1,
)

# ─── State (409) versus business referential (422) on a version decision ───


def _draft_version_on_a_rejected_snapshot(api: ApiClient) -> dict:
    dataset = create_draft_dataset(api)
    get_success_data(api.submit_training_dataset(dataset["id"], MLE_1))
    rejected = get_success_data(
        api.decide_training_dataset(
            dataset["id"], build_dataset_decision_payload("REJECT"), STEWARD_1
        )
    )
    assert rejected["approval_state"] == "REJECTED"
    model = create_model(api)
    version = register_version(api, model["id"], dataset["id"])
    assert version["approval_state"] == "DRAFT"
    assert version["doc_completeness_pct"] == 80.00
    assert version["reproducibility_score"] == 100.00
    return version


def test_an_undeclared_transition_outranks_the_snapshot_gate(api):
    """A missing transition answers before the dependency is even consulted.

    PRD 2.7 puts the state band — "ERR_TERMINAL_STATE before ERR_INVALID_STATE"
    — ahead of the safety and referential bands that carry
    ERR_DATASET_NOT_APPROVED. No APPROVE transition is declared out of DRAFT in
    PRD 3.3, so that is the violation reported.

    Design: Difficulty/priority_pair_validation_conflict/state_priority_15_beats_referential_priority_40_on_version_approve
    """
    version = _draft_version_on_a_rejected_snapshot(api)

    refused = api.decide_model_version(
        version["id"], build_version_decision_payload("APPROVE"), APPROVER_1
    )
    validate_error(refused, ERR_INVALID_STATE)

    unchanged = get_success_data(api.get_model_version(version["id"], APPROVER_1))
    assert_version_state(unchanged, approval_state="DRAFT")
    assert unchanged["decided_by_user_id"] is None


def test_repairing_the_state_exposes_the_snapshot_gate_underneath(api):
    """The outranked violation was real all along.

    PRD 3.3: approving a version requires that "the referenced training-data
    snapshot is itself APPROVED, and otherwise the request is rejected with
    ERR_DATASET_NOT_APPROVED". Submitting the version for review removes only the
    state violation.

    Design: Difficulty/priority_pair_validation_conflict/state_priority_15_beats_referential_priority_40_on_version_approve
    """
    version = _draft_version_on_a_rejected_snapshot(api)

    submitted = get_success_data(
        api.submit_version_for_review(version["id"], MLE_1)
    )
    assert_version_state(submitted, approval_state="PENDING_REVIEW")
    assert submitted["submitted_by_user_id"] == USER_MLE_1

    refused = api.decide_model_version(
        version["id"], build_version_decision_payload("APPROVE"), APPROVER_1
    )
    validate_error(refused, ERR_DATASET_NOT_APPROVED)

    unchanged = get_success_data(api.get_model_version(version["id"], APPROVER_1))
    assert_version_state(
        unchanged, approval_state="PENDING_REVIEW", revalidation_due_at=None
    )
    assert unchanged["approved_at"] is None


# ─── Business safety (422) versus business fiscal (409) on a ramp ───


def _exhausted_cluster_with_an_open_incident(api: ApiClient) -> tuple:
    stack = build_stack(api, max_traffic_pct=40.00, ramps=3)
    incident = create_incident(api, stack.deployment_id)
    assert incident["status"] == "OPEN"
    return stack, incident


def test_an_open_incident_outranks_the_exhausted_cluster(api):
    """The safety refusal answers before the capacity refusal.

    PRD 2.7 places the safety band, which carries
    ERR_OPEN_INCIDENT_BLOCKS_ACTION, ahead of the capacity checks that come
    "last" and carry ERR_ENDPOINT_CAPACITY_EXHAUSTED. PRD 3.4 blocks a ramp while
    an incident on the deployment is OPEN, MITIGATING or ESCALATED.

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_33_beats_fiscal_priority_70_on_ramp
    """
    stack, incident = _exhausted_cluster_with_an_open_incident(api)

    refused = api.ramp_deployment(stack.deployment_id, RELIABILITY_1)
    validate_error(refused, ERR_OPEN_INCIDENT_BLOCKS_ACTION)
    assert refused.json()["data"]["error_id"] != ERR_ENDPOINT_CAPACITY_EXHAUSTED

    engaged = incident_action(api, incident["id"], "ENGAGE_FALLBACK")
    assert engaged["status"] == "MITIGATING"
    assert engaged["fallback_engaged"] is True
    assert engaged["fallback_strategy_used"] == "PREVIOUS_CHAMPION"

    still_refused = api.ramp_deployment(stack.deployment_id, RELIABILITY_1)
    validate_error(still_refused, ERR_OPEN_INCIDENT_BLOCKS_ACTION)


def test_monitoring_does_not_block_and_reveals_the_capacity_refusal(api):
    """MONITORING is deliberately outside the blocking set.

    PRD 3.4 lists the blocking incident statuses as OPEN, MITIGATING and
    ESCALATED, and PRD 3.8 has MONITOR move a MITIGATING incident to MONITORING.
    With the safety rule satisfied the identical ramp call reaches the capacity
    check and refuses a granted delta of exactly zero.

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_33_beats_fiscal_priority_70_on_ramp
    """
    stack, incident = _exhausted_cluster_with_an_open_incident(api)
    incident_action(api, incident["id"], "ENGAGE_FALLBACK")
    monitoring = incident_action(api, incident["id"], "MONITOR")
    assert monitoring["status"] == "MONITORING"

    refused = api.ramp_deployment(stack.deployment_id, RELIABILITY_1)
    validate_error(refused, ERR_ENDPOINT_CAPACITY_EXHAUSTED)

    deployment = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(deployment, traffic_pct=35.00, ramp_step_index=3)
    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 35.00)
    assert len(ledger_rows(api, stack.deployment_id)) == 3


# ─── Uniqueness (409) versus interval geometry (409) on an observation window ───

_OVERLAPPING = {
    "window_kind": "PERFORMANCE",
    "window_start": "2026-08-02T03:00:00Z",
    "window_end": "2026-08-02T09:00:00Z",
    "prediction_count": 9000,
    "labeled_prediction_count": 4500,
    "correct_labeled_count": 3800,
    "positive_rate": 0.31,
    "p95_latency_ms": 210,
    "observed_bin_proportions": [0.20, 0.20, 0.20, 0.20, 0.20],
}


def _open_incumbent_window(api: ApiClient) -> tuple:
    stack = build_stack(api, ramps=1)
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )
    assert window["status"] == "OPEN"
    assert window["window_kind"] == "PERFORMANCE"
    return stack, window


def test_a_second_open_window_of_a_kind_outranks_the_overlap_rule(api):
    """The uniqueness refusal answers before the geometry refusal.

    PRD 2.7 orders the state band's ERR_DUPLICATE_OPEN_WINDOW ahead of the
    temporal band, and calls the case out explicitly: "a duplicate open window
    that also overlaps answers ERR_DUPLICATE_OPEN_WINDOW". Both codes carry HTTP
    409, so only the error identifier distinguishes them.

    Design: Difficulty/priority_pair_validation_conflict/constraint_priority_53_beats_temporal_priority_62_on_monitoring_window
    """
    stack, _ = _open_incumbent_window(api)

    refused = api.create_monitoring_window(
        build_monitoring_window_payload(
            stack.deployment_id, stack.version_id, **_OVERLAPPING
        ),
        RELIABILITY_1,
    )
    validate_error(refused, ERR_DUPLICATE_OPEN_WINDOW)
    assert refused.json()["data"]["error_id"] != ERR_MONITORING_WINDOW_OVERLAP


def test_closing_the_incumbent_exposes_the_overlap_rule_underneath(api):
    """With the incumbent closed the same body hits the geometry rule.

    PRD 3.5: "two fully-closed windows of the same kind on the same deployment
    may not intersect at all, and an attempt to record one that does is rejected
    with ERR_MONITORING_WINDOW_OVERLAP"; both rules are scoped to the deployment
    and the window kind, so the same interval under another kind is accepted.

    Design: Difficulty/priority_pair_validation_conflict/constraint_priority_53_beats_temporal_priority_62_on_monitoring_window
    """
    stack, window = _open_incumbent_window(api)
    set_clock(api, "2026-08-03T00:00:00Z")
    closed = close_window(api, window["id"])
    assert closed["status"] == "CLOSED"
    assert closed["health_score_variant"] == "FINAL"

    refused = api.create_monitoring_window(
        build_monitoring_window_payload(
            stack.deployment_id, stack.version_id, **_OVERLAPPING
        ),
        RELIABILITY_1,
    )
    validate_error(refused, ERR_MONITORING_WINDOW_OVERLAP)

    other_kind = dict(_OVERLAPPING, window_kind="DISTRIBUTION")
    accepted = get_success_data(
        api.create_monitoring_window(
            build_monitoring_window_payload(
                stack.deployment_id, stack.version_id, **other_kind
            ),
            RELIABILITY_1,
        )
    )
    assert accepted["window_kind"] == "DISTRIBUTION"
    assert accepted["status"] == "OPEN"

    rows = get_success_data(
        api.list_monitoring_windows(
            RELIABILITY_1, {"deployment_id": stack.deployment_id}
        )
    )
    assert len(rows) == 2
