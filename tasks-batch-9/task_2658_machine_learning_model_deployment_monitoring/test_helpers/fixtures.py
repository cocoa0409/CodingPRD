"""Setup builders and pytest fixtures.

The harness restarts the service and empties its store before every single
test, so nothing here may assume pre-existing rows: every fixture builds the
state it needs from scratch, and it does so only through endpoints the PRD
declares. The builders are plain functions first and fixtures second, because a
test that needs a second, slightly different serving stack can call the builder
directly instead of contorting a fixture.

Tiers, from cheapest to richest:
  1. transport and the logical clock
  2. one row of a single family
  3. an approved artifact version on an open cluster
  4. a deployment carrying traffic
  5. composites: closed windows, breached drift, scheduled evaluations
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_DEFAULT, FEATURE_HASH_V1
from .test_users import (
    ADMIN_1,
    APPROVER_1,
    MLE_1,
    RELIABILITY_1,
    STEWARD_1,
)


# ─── Tier 1: transport and clock ───


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the service under test."""
    return ApiClient()


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Advance the monotonic logical clock, which only PlatformAdmin may do."""
    return get_success_data(api.set_clock(f.build_clock_payload(current_utc), ADMIN_1))


@pytest.fixture
def clock_at_default() -> str:
    """The clock's startup reading, asserted rather than assumed by callers."""
    return CLOCK_DEFAULT


# ─── Tier 2: single rows ───


def create_model(api: ApiClient, headers: Dict[str, str] = MLE_1, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_model(f.build_model_payload(**overrides), headers)
    )


def create_draft_dataset(
    api: ApiClient, headers: Dict[str, str] = MLE_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_training_dataset(
            f.build_training_dataset_payload(**overrides), headers
        )
    )


def create_approved_dataset(
    api: ApiClient,
    registrar: Dict[str, str] = MLE_1,
    decider: Dict[str, str] = STEWARD_1,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register, submit and approve a snapshot in one call.

    The registrar and the decider are deliberately different operators, because
    PRD §2.10 forbids the snapshot's registrar from deciding it.
    """
    dataset = create_draft_dataset(api, registrar, **overrides)
    get_success_data(api.submit_training_dataset(dataset["id"], registrar))
    return get_success_data(
        api.decide_training_dataset(
            dataset["id"], f.build_dataset_decision_payload("APPROVE"), decider
        )
    )


def create_serving_endpoint(
    api: ApiClient, headers: Dict[str, str] = ADMIN_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_serving_endpoint(
            f.build_serving_endpoint_payload(**overrides), headers
        )
    )


def read_endpoint_version(api: ApiClient, endpoint_id: str) -> int:
    """Re-read a cluster's `version` for the stale-version token of PRD §2.6."""
    return get_success_data(api.get_serving_endpoint(endpoint_id, ADMIN_1))["version"]


def read_model_version_token(api: ApiClient, model_id: str) -> int:
    """Re-read a registry entry's `version` for the token of PRD §2.6."""
    return get_success_data(api.get_model(model_id, MLE_1))["version"]


# ─── Tier 3: an approved artifact version ───


def register_version(
    api: ApiClient,
    model_id: str,
    dataset_id: str,
    headers: Dict[str, str] = MLE_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_model_version(
            f.build_model_version_payload(model_id, dataset_id, **overrides), headers
        )
    )


def approve_version(
    api: ApiClient,
    version_id: str,
    submitter: Dict[str, str] = MLE_1,
    approver: Dict[str, str] = APPROVER_1,
) -> Dict[str, Any]:
    """Walk DRAFT to PENDING_REVIEW to APPROVED with distinct operators.

    PRD §2.10 forbids the version's submitter from deciding it, so the submitter
    and the approver must be different identifiers.
    """
    get_success_data(api.submit_version_for_review(version_id, submitter))
    return get_success_data(
        api.decide_model_version(
            version_id, f.build_version_decision_payload("APPROVE"), approver
        )
    )


def create_approved_version(
    api: ApiClient,
    model_id: str,
    dataset_id: str,
    submitter: Dict[str, str] = MLE_1,
    approver: Dict[str, str] = APPROVER_1,
    **overrides: Any,
) -> Dict[str, Any]:
    version = register_version(api, model_id, dataset_id, submitter, **overrides)
    return approve_version(api, version["id"], submitter, approver)


# ─── Tier 4: deployments carrying traffic ───


def create_deployment(
    api: ApiClient,
    version_id: str,
    endpoint_id: str,
    headers: Dict[str, str] = RELIABILITY_1,
    **overrides: Any,
) -> Dict[str, Any]:
    token = read_endpoint_version(api, endpoint_id)
    return get_success_data(
        api.create_deployment(
            f.build_deployment_payload(version_id, endpoint_id, token, **overrides),
            headers,
        )
    )


def ramp(api: ApiClient, deployment_id: str, times: int = 1) -> Dict[str, Any]:
    """Ramp a deployment a fixed number of times, asserting each step lands."""
    data: Dict[str, Any] = {}
    for _ in range(times):
        data = get_success_data(api.ramp_deployment(deployment_id, RELIABILITY_1))
    return data


def rollout(api: ApiClient, deployment_id: str, action: str) -> Dict[str, Any]:
    return get_success_data(
        api.rollout_action(
            deployment_id, f.build_rollout_action_payload(action), RELIABILITY_1
        )
    )


# ─── The canonical serving stack ───


@dataclass
class Stack:
    """A registry entry, an approved snapshot, an approved version, an open
    cluster and one deployment on it."""

    model_id: str
    dataset_id: str
    version_id: str
    endpoint_id: str
    deployment_id: str
    model: Dict[str, Any] = field(default_factory=dict)
    dataset: Dict[str, Any] = field(default_factory=dict)
    version: Dict[str, Any] = field(default_factory=dict)
    endpoint: Dict[str, Any] = field(default_factory=dict)
    deployment: Dict[str, Any] = field(default_factory=dict)


def build_stack(
    api: ApiClient,
    *,
    pattern: str = "REALTIME",
    max_traffic_pct: float = 100.00,
    deploy_cooldown_minutes: int = 30,
    feature_hash: str = FEATURE_HASH_V1,
    evaluation_sample_quota: int = 5000,
    baseline_accuracy: float = 0.82,
    baseline_positive_rate: float = 0.30,
    baseline_p95_latency_ms: int = 200,
    revalidation_interval_days: int = 90,
    fallback_strategy: str = "PREVIOUS_CHAMPION",
    serve_from: str = "2026-08-01T00:00:00Z",
    serve_until: str = "2026-08-31T00:00:00Z",
    baseline_bin_proportions: Optional[List[float]] = None,
    ramps: int = 0,
) -> Stack:
    """Build the whole chain a serving deployment needs, in PRD order."""
    model = create_model(
        api, MLE_1, revalidation_interval_days=revalidation_interval_days
    )
    dataset_kwargs: Dict[str, Any] = {
        "feature_hash": feature_hash,
        "baseline_positive_rate": baseline_positive_rate,
    }
    if baseline_bin_proportions is not None:
        dataset_kwargs["baseline_bin_proportions"] = list(baseline_bin_proportions)
    dataset = create_approved_dataset(api, MLE_1, STEWARD_1, **dataset_kwargs)
    version = create_approved_version(
        api,
        model["id"],
        dataset["id"],
        feature_spec_hash=feature_hash,
        baseline_accuracy=baseline_accuracy,
        baseline_positive_rate=baseline_positive_rate,
        baseline_p95_latency_ms=baseline_p95_latency_ms,
        evaluation_sample_quota=evaluation_sample_quota,
    )
    endpoint = create_serving_endpoint(
        api,
        ADMIN_1,
        serving_feature_spec_hash=feature_hash,
        max_traffic_pct=max_traffic_pct,
        deploy_cooldown_minutes=deploy_cooldown_minutes,
    )
    deployment = create_deployment(
        api,
        version["id"],
        endpoint["id"],
        pattern=pattern,
        serve_from=serve_from,
        serve_until=serve_until,
        fallback_strategy=fallback_strategy,
    )
    if ramps:
        deployment = ramp(api, deployment["id"], ramps)
    return Stack(
        model_id=model["id"],
        dataset_id=dataset["id"],
        version_id=version["id"],
        endpoint_id=endpoint["id"],
        deployment_id=deployment["id"],
        model=model,
        dataset=dataset,
        version=version,
        endpoint=endpoint,
        deployment=deployment,
    )


def add_version_and_deployment(
    api: ApiClient,
    stack: Stack,
    *,
    semver: str = "1.1.0",
    artifact_digest: str = "sha256:bbb",
    pattern: str = "SHADOW",
    parent_version_id: Optional[str] = None,
    endpoint_id: Optional[str] = None,
    baseline_accuracy: float = 0.85,
    baseline_p95_latency_ms: int = 180,
    evaluation_sample_quota: int = 5000,
    serve_from: str = "2026-08-01T00:00:00Z",
    serve_until: str = "2026-08-31T00:00:00Z",
    fallback_strategy: str = "PREVIOUS_CHAMPION",
    ramps: int = 0,
) -> Dict[str, Any]:
    """Add a second approved version on the same snapshot plus a deployment.

    Returns a mapping with the new `version_id` and `deployment_id`.
    """
    overrides: Dict[str, Any] = {
        "semver": semver,
        "artifact_digest": artifact_digest,
        "feature_spec_hash": stack.version["feature_spec_hash"],
        "baseline_accuracy": baseline_accuracy,
        "baseline_positive_rate": stack.version["baseline_positive_rate"],
        "baseline_p95_latency_ms": baseline_p95_latency_ms,
        "evaluation_sample_quota": evaluation_sample_quota,
    }
    if parent_version_id is not None:
        overrides["parent_version_id"] = parent_version_id
    version = create_approved_version(
        api, stack.model_id, stack.dataset_id, MLE_1, APPROVER_1, **overrides
    )
    deployment = create_deployment(
        api,
        version["id"],
        stack.endpoint_id if endpoint_id is None else endpoint_id,
        pattern=pattern,
        serve_from=serve_from,
        serve_until=serve_until,
        fallback_strategy=fallback_strategy,
    )
    if ramps:
        deployment = ramp(api, deployment["id"], ramps)
    return {
        "version_id": version["id"],
        "deployment_id": deployment["id"],
        "version": version,
        "deployment": deployment,
    }


# ─── Tier 5: observation, drift, skew and evaluation composites ───


def record_window(
    api: ApiClient,
    deployment_id: str,
    version_id: str,
    headers: Dict[str, str] = MLE_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_monitoring_window(
            f.build_monitoring_window_payload(deployment_id, version_id, **overrides),
            headers,
        )
    )


def close_window(api: ApiClient, window_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_monitoring_window(window_id, MLE_1))


def record_and_close_window(
    api: ApiClient,
    deployment_id: str,
    version_id: str,
    clock_after: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record a window, advance the clock past its end, then close it."""
    window = record_window(api, deployment_id, version_id, MLE_1, **overrides)
    if clock_after is not None:
        set_clock(api, clock_after)
    return close_window(api, window["id"])


def create_drift_report(
    api: ApiClient, window_id: str, headers: Dict[str, str] = MLE_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_drift_report(
            f.build_drift_report_payload(window_id, **overrides), headers
        )
    )


def create_skew_check(
    api: ApiClient,
    version_id: str,
    deployment_id: str,
    training: Optional[Dict[str, Any]] = None,
    serving: Optional[Dict[str, Any]] = None,
    headers: Dict[str, str] = MLE_1,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_skew_check(
            f.build_skew_check_payload(version_id, deployment_id, training, serving),
            headers,
        )
    )


def only_trigger(api: ApiClient, model_id: str) -> Dict[str, Any]:
    """Read the single retraining trigger raised for a registry entry."""
    response = api.list_retraining_triggers(MLE_1, {"model_id": model_id})
    rows = get_success_data(response)
    assert len(rows) == 1, f"expected exactly one trigger, got {len(rows)}"
    return rows[0]


def only_incident(api: ApiClient, deployment_id: str) -> Dict[str, Any]:
    response = api.list_prediction_incidents(MLE_1, {"deployment_id": deployment_id})
    rows = get_success_data(response)
    assert len(rows) == 1, f"expected exactly one incident, got {len(rows)}"
    return rows[0]


def ledger_rows(
    api: ApiClient, deployment_id: str, reason: Optional[str] = None
) -> List[Dict[str, Any]]:
    params = {"limit": 100}
    if reason is not None:
        params["reason"] = reason
    return get_success_data(
        api.list_deployment_ramp_steps(deployment_id, RELIABILITY_1, params)
    )


def create_incident(
    api: ApiClient, deployment_id: str, headers: Dict[str, str] = RELIABILITY_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_prediction_incident(
            f.build_incident_payload(deployment_id, **overrides), headers
        )
    )


def incident_action(
    api: ApiClient, incident_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.incident_action(
            incident_id,
            f.build_incident_action_payload(action, **overrides),
            RELIABILITY_1,
        )
    )


def schedule_evaluation(
    api: ApiClient,
    model_id: str,
    champion_deployment_id: str,
    challenger_deployment_id: str,
    headers: Dict[str, str] = RELIABILITY_1,
    **overrides: Any,
) -> Dict[str, Any]:
    token = read_model_version_token(api, model_id)
    return get_success_data(
        api.schedule_challenger_evaluation(
            model_id,
            f.build_evaluation_payload(
                champion_deployment_id,
                challenger_deployment_id,
                token,
                **overrides,
            ),
            headers,
        )
    )


@dataclass
class EvaluationArms:
    """A LIVE realtime champion and a serving shadow challenger on one entry."""

    stack: Stack
    champion_deployment_id: str
    champion_version_id: str
    challenger_deployment_id: str
    challenger_version_id: str
    challenger_endpoint_id: str = ""


def build_evaluation_arms(
    api: ApiClient,
    *,
    challenger_quota: int = 5000,
    challenger_ramps: int = 1,
) -> EvaluationArms:
    """Drive a realtime deployment to LIVE and put a shadow challenger beside it.

    The realtime arm walks its five checkpoints so that its rollout_state is
    exactly LIVE, which PRD §3.7 requires of the champion arm; the shadow arm
    only needs to be in the serving set. A LIVE realtime arm holds the whole
    first cluster, so the challenger gets a cluster of its own.
    """
    stack = build_stack(api, pattern="REALTIME")
    ramp(api, stack.deployment_id, 6)
    second_endpoint = create_serving_endpoint(
        api,
        ADMIN_1,
        serving_feature_spec_hash=stack.endpoint["serving_feature_spec_hash"],
    )
    challenger = add_version_and_deployment(
        api,
        stack,
        pattern="SHADOW",
        parent_version_id=stack.version_id,
        endpoint_id=second_endpoint["id"],
        evaluation_sample_quota=challenger_quota,
        ramps=challenger_ramps,
    )
    return EvaluationArms(
        stack=stack,
        champion_deployment_id=stack.deployment_id,
        champion_version_id=stack.version_id,
        challenger_deployment_id=challenger["deployment_id"],
        challenger_version_id=challenger["version_id"],
        challenger_endpoint_id=second_endpoint["id"],
    )


# ─── Composite fixtures ───


@pytest.fixture
def model(api: ApiClient) -> Dict[str, Any]:
    return create_model(api)


@pytest.fixture
def draft_dataset(api: ApiClient) -> Dict[str, Any]:
    return create_draft_dataset(api)


@pytest.fixture
def approved_dataset(api: ApiClient) -> Dict[str, Any]:
    return create_approved_dataset(api)


@pytest.fixture
def open_endpoint(api: ApiClient) -> Dict[str, Any]:
    return create_serving_endpoint(api)


@pytest.fixture
def approved_version(api: ApiClient, model: Dict[str, Any], approved_dataset: Dict[str, Any]) -> Dict[str, Any]:
    return create_approved_version(api, model["id"], approved_dataset["id"])


@pytest.fixture
def pending_stack(api: ApiClient) -> Stack:
    """A realtime deployment sitting in PENDING on an open cluster."""
    return build_stack(api)


@pytest.fixture
def ramping_stack(api: ApiClient) -> Stack:
    """A realtime deployment that has taken its first ramp step to 5.00."""
    return build_stack(api, ramps=1)


@pytest.fixture
def live_stack(api: ApiClient) -> Stack:
    """A realtime deployment walked all the way to LIVE at 100.00."""
    return build_stack(api, ramps=6)


@pytest.fixture
def evaluation_arms(api: ApiClient) -> EvaluationArms:
    return build_evaluation_arms(api)
