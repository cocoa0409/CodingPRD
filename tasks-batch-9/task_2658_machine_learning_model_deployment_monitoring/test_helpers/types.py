"""Typed shapes of the thirteen resource families and the two computed reads.

Each TypedDict names exactly the fields the PRD says a read of that family
returns. Twelve families carry the common `created_at`, `updated_at` and
`version` triple; the traffic-ramp ledger row is deliberately append-only and
carries only `id` and `created_at` (PRD §2.4), so its shape omits the other two.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """The system fields every mutable family carries (PRD §2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyFields(TypedDict):
    """The system fields an append-only ledger row carries (PRD §2.4)."""

    id: str
    created_at: str


class ModelRegistryEntry(CommonFields):
    name: str
    task_type: str
    owner_team: str
    revalidation_interval_days: int
    registry_status: str
    registered_by_user_id: str
    champion_version_id: Optional[str]
    champion_promoted_at: Optional[str]
    open_retraining_trigger_count: int


class TrainingDataset(CommonFields):
    name: str
    snapshot_uri: str
    row_count: int
    feature_hash: str
    license_class: str
    baseline_positive_rate: float
    baseline_bin_proportions: List[float]
    pii_review_passed: bool
    approval_state: str
    registered_by_user_id: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    note: Optional[str]
    revocation_reason: Optional[str]
    dependent_version_count: int


class ModelVersion(CommonFields):
    model_id: str
    training_dataset_id: str
    semver: str
    artifact_digest: str
    feature_spec_hash: str
    baseline_accuracy: float
    baseline_positive_rate: float
    baseline_p95_latency_ms: int
    parent_version_id: Optional[str]
    doc_sections: List[str]
    repro_artifacts: List[str]
    doc_completeness_pct: float
    reproducibility_score: float
    evaluation_sample_quota: int
    evaluation_sample_budget: int
    approval_state: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    approved_at: Optional[str]
    revalidation_due_at: Optional[str]
    blocked_reason: Optional[str]


class ServingEndpoint(CommonFields):
    name: str
    region: str
    serving_feature_spec_hash: str
    max_traffic_pct: float
    deploy_cooldown_minutes: int
    allocated_traffic_pct: float
    operational_state: str


class Deployment(CommonFields):
    model_version_id: str
    serving_endpoint_id: str
    pattern: str
    serve_from: str
    serve_until: str
    fallback_strategy: str
    rollout_state: str
    health_state: str
    traffic_pct: float
    target_traffic_pct: float
    ramp_step_index: int
    cumulative_ramp_delta_pct: float
    manual_override_active: bool
    override_traffic_pct: Optional[float]
    health_score_provisional: Optional[float]
    health_score_final: Optional[float]
    rolled_back_at: Optional[str]
    created_by_user_id: str


class TrafficRampStep(AppendOnlyFields):
    """Append-only ledger row: no `updated_at` and no `version` (PRD §2.4)."""

    deployment_id: str
    step_index: int
    from_traffic_pct: float
    to_traffic_pct: float
    delta_pct: float
    reason: str
    health_state_at_step: str
    clock_at_step: str


class MonitoringWindow(CommonFields):
    deployment_id: str
    model_version_id: str
    window_kind: str
    window_start: str
    window_end: str
    prediction_count: int
    labeled_prediction_count: int
    correct_labeled_count: int
    positive_rate: float
    p95_latency_ms: int
    observed_bin_proportions: List[float]
    status: str
    health_score: Optional[float]
    health_score_variant: str
    baseline_delta_pct: Optional[float]
    closed_at: Optional[str]


class DriftReport(CommonFields):
    monitoring_window_id: str
    model_version_id: str
    drift_kind: str
    baseline_mode: str
    effective_baseline_mode: str
    baseline_dataset_id: Optional[str]
    windows_used_count: int
    expected_bin_proportions: List[float]
    drift_index: float
    severity: str
    status: str


class SkewCheck(CommonFields):
    model_version_id: str
    deployment_id: str
    training_dataset_id: str
    training_feature_stats: Dict[str, Any]
    serving_feature_stats: Dict[str, Any]
    missing_features: List[str]
    max_skew_ratio: float
    max_skew_feature: Optional[str]
    status: str
    checked_at: str


class RetrainingTrigger(CommonFields):
    model_id: str
    drift_report_id: Optional[str]
    skew_check_id: Optional[str]
    retrained_version_id: Optional[str]
    base_urgency: float
    escalation_tier_bonus_pct: int
    total_urgency: float
    priority_band: str
    retrain_required: bool
    stale_after: str
    status: str
    acknowledged_by_user_id: Optional[str]
    dismissed_reason: Optional[str]


class ChallengerEvaluation(CommonFields):
    model_id: str
    champion_deployment_id: str
    challenger_deployment_id: str
    challenger_version_id: str
    reserved_samples: int
    evaluation_ends_at: str
    champion_metrics: Dict[str, float]
    challenger_metrics: Dict[str, float]
    metric_lines: Optional[Dict[str, float]]
    promotion_score: Optional[float]
    criteria_failures: List[str]
    labeled_prediction_count: Optional[int]
    extension_count: int
    status: str
    created_by_user_id: str


class PredictionIncident(CommonFields):
    deployment_id: str
    model_version_id: str
    drift_report_id: Optional[str]
    summary: str
    source: str
    severity: str
    status: str
    fallback_engaged: bool
    fallback_strategy_used: Optional[str]
    manual_override_traffic_pct: Optional[float]
    recurrence_count: int
    opened_at: str
    resolved_at: Optional[str]


class RevalidationTask(CommonFields):
    model_version_id: str
    due_at: str
    swept_at: str
    reviewer_user_id: Optional[str]
    findings: Optional[str]
    decided_at: Optional[str]
    status: str


class DeploymentHealthRead(TypedDict):
    """The computed health read of PRD §3.5 — not a stored family."""

    deployment_id: str
    health_state: str
    score_variant: str
    health_score: Optional[float]
    baseline_delta_pct: Optional[float]
    monitoring_window_id: Optional[str]
    prediction_count: Optional[int]
    labeled_prediction_count: Optional[int]


class ClockReading(TypedDict):
    """The logical clock's response shape (PRD §3.9)."""

    current_utc: str
    previous_utc: str


class SweepResult(TypedDict):
    """The revalidation sweep's four counters (PRD §3.9)."""

    evaluated_count: int
    created_count: int
    skipped_existing_count: int
    staled_trigger_count: int
