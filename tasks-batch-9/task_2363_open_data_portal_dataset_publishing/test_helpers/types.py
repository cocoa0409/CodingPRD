"""
TypedDict definitions for every Open Data Portal API resource.

Field names are taken verbatim from the PRD. Every persisted resource carries the
four system-managed properties described in PRD §2.4 (`id`, `created_at`,
`updated_at`, `version`), so those are declared on a shared base.

All TypedDicts are ``total=False``: the tests assert on the fields they care
about and never require a response to be exhaustive.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ─── Shared system-managed properties (PRD §2.4) ──────────────────────


class CommonFields(TypedDict, total=False):
    """The four system-managed properties every persisted resource carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


# ─── Registries ───────────────────────────────────────────────────────


class Department(CommonFields, total=False):
    name: str
    code: str
    contact_email: str
    credits_issued_units: float
    credit_balance_units: float
    credits_escrowed_units: float
    credits_consumed_units: float
    breached_dataset_count: int
    stale_dataset_count: int
    remediation_dataset_count: int
    overdue_correction_count: int
    risk_points: int
    compliance_posture: str


class DepartmentScorecard(TypedDict, total=False):
    """Computed read: posture arithmetic and credit reconciliation (PRD §3.1)."""

    department_id: str
    compliance_posture: str
    risk_points: int
    breached_dataset_count: int
    stale_dataset_count: int
    remediation_dataset_count: int
    overdue_correction_count: int
    credits_issued_units: float
    credit_balance_units: float
    credits_escrowed_units: float
    credits_consumed_units: float
    credit_ledger_balanced: bool


class LicenseTerm(CommonFields, total=False):
    code: str
    name: str
    attribution_required: bool
    commercial_use_allowed: bool
    share_alike: bool
    attribution_text_template: Optional[str]
    reuse_permission_class: str
    retired: bool


class IngestRunner(CommonFields, total=False):
    name: str
    cooldown_minutes: int
    status: str
    armed_window_count: int


# ─── The dataset and its inline collections ───────────────────────────


class UsageEpoch(TypedDict, total=False):
    """Inline member of ``Dataset.usage_epochs`` (PRD §2.4)."""

    epoch_index: int
    api_call_count: int
    download_count: int
    recorded_at: str


class ShowcaseApp(TypedDict, total=False):
    """Inline member of ``Dataset.showcase_apps`` (PRD §2.4)."""

    label: str
    name: str
    url: str
    submitter_member_id: str
    status: str
    decided_at: Optional[str]


class Dataset(CommonFields, total=False):
    department_id: str
    title: str
    slug: str
    description: str
    update_frequency: str
    column_count: int
    sensitivity_class: str
    public_demand_score: float
    policy_value_score: float
    observed_demand_score: float
    engagement_index: float
    priority_score: float
    priority_score_variant: str
    priority_tier: str
    publication_status: str
    currency_status: str
    aggregation_geography: Optional[str]
    public_access_suspended: bool
    high_value_committed: bool
    live_row_count: int
    version_index_high_water: int
    days_overdue: int
    staleness_alert_count: int
    last_published_at: Optional[str]
    next_due_at: Optional[str]
    last_staleness_alert_at: Optional[str]
    remediation_opened_at: Optional[str]
    embargo_until_utc: Optional[str]
    usage_epochs: List[UsageEpoch]
    showcase_apps: List[ShowcaseApp]


class DatasetAnalytics(TypedDict, total=False):
    """Computed read exposed by the per-dataset analytics capability (PRD §3.8)."""

    dataset_id: str
    engagement_index: float
    observed_demand_score: float
    priority_score: float
    priority_score_variant: str
    priority_tier: str
    priority_score_as_declared: float
    priority_score_as_observed: float
    usage_epoch_count: int
    approved_showcase_count: int
    open_issue_count: int
    currency_status: str
    days_overdue: int
    next_due_at: Optional[str]


# ─── Gating artefacts ─────────────────────────────────────────────────


class MetadataRecord(CommonFields, total=False):
    dataset_id: str
    license_id: str
    data_dictionary_field_count: int
    provenance_detail_lines: int
    contact_email: str
    declared_update_frequency: str
    attribution_element_count: int
    component_contributions: List[float]
    completeness_score: float
    status: str
    returned_reason: Optional[str]


class PrivacyAssessment(CommonFields, total=False):
    dataset_id: str
    declared_quasi_identifier_count: int
    declared_smallest_cell_size: int
    verified_smallest_cell_size: Optional[int]
    population_size: int
    screening_risk_score: Optional[float]
    clearance_risk_score: Optional[float]
    risk_score: Optional[float]
    k_anonymity_k: int
    aggregation_required: bool
    min_aggregation_geography: str
    assessor_user_id: str
    decided_by_user_id: Optional[str]
    block_reason: Optional[str]
    status: str


# ─── Automation ───────────────────────────────────────────────────────


class PublicationPipeline(CommonFields, total=False):
    dataset_id: str
    runner_id: str
    cadence: str
    window_start_minute: int
    window_duration_minutes: int
    window_end_minute: int
    alert_email: str
    escrow_required_units: float
    escrowed_credit_units: float
    consecutive_failure_count: int
    suspend_reason: Optional[str]
    superseded_pipeline_id: Optional[str]
    status: str


class PipelineRun(CommonFields, total=False):
    pipeline_id: str
    scheduled_for_utc: str
    started_at: Optional[str]
    finished_at: Optional[str]
    rows_ingested: int
    alert_dispatched: bool
    failure_code: Optional[str]
    skip_reason: Optional[str]
    consecutive_failure_index: int
    compute_credits: float
    alert_credits: float
    subtotal_credits: float
    reliability_discount_pct: float
    discount_credits: float
    total_charge_credits: float
    escrow_drawn_units: float
    balance_drawn_units: float
    status: str


class DatasetVersion(CommonFields, total=False):
    dataset_id: str
    version_index: int
    version_label: str
    change_type: str
    row_count: int
    notes: Optional[str]
    source_run_id: Optional[str]
    correction_issue_id: Optional[str]
    supersedes_version_id: Optional[str]
    published_at: str
    superseded_at: Optional[str]
    retracted_at: Optional[str]
    status: str


# ─── Community ────────────────────────────────────────────────────────


class CommunityMember(CommonFields, total=False):
    email: str
    display_name: str
    organization: Optional[str]
    accepted_issue_count: int
    rejected_issue_count: int
    approved_showcase_count: int
    decay_epochs: int
    reputation_score: float
    vote_weight: int
    last_credited_at: str
    status: str


class QualityIssue(CommonFields, total=False):
    dataset_id: str
    reporter_member_id: str
    severity: str
    category: str
    description: str
    triage_due_at: str
    triaged_at: Optional[str]
    accepted_at: Optional[str]
    correction_due_at: Optional[str]
    triage_breached: bool
    correction_breached: bool
    reject_reason: Optional[str]
    resolution_version_id: Optional[str]
    status: str


class RequestVote(TypedDict, total=False):
    """Inline member of ``DatasetRequest.votes`` (PRD §2.4)."""

    member_id: str
    weight: int
    cast_at: str


class DatasetRequest(CommonFields, total=False):
    requester_member_id: str
    title: str
    rationale: str
    votes: List[RequestVote]
    weighted_vote_total: int
    demand_signal: float
    linked_dataset_id: Optional[str]
    decision_note: Optional[str]
    status: str


# ─── Operational capabilities ─────────────────────────────────────────


class SweepReport(TypedDict, total=False):
    """What the portal sweep reports it did (PRD §3.9)."""

    datasets_recomputed: int
    currency_transitions: int
    staleness_alerts_emitted: int
    issues_triage_breached: int
    issues_correction_breached: int
    departments_recomputed: int
    postures_changed: int


class ClockState(TypedDict, total=False):
    current_utc: str


JsonDict = Dict[str, Any]

__all__ = [
    "CommonFields",
    "Department",
    "DepartmentScorecard",
    "LicenseTerm",
    "IngestRunner",
    "UsageEpoch",
    "ShowcaseApp",
    "Dataset",
    "DatasetAnalytics",
    "MetadataRecord",
    "PrivacyAssessment",
    "PublicationPipeline",
    "PipelineRun",
    "DatasetVersion",
    "CommunityMember",
    "QualityIssue",
    "RequestVote",
    "DatasetRequest",
    "SweepReport",
    "ClockState",
    "JsonDict",
]
