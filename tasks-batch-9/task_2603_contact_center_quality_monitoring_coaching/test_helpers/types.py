"""Domain types for the Contact Center Quality Monitoring & Coaching API.

Entity shapes and enum member sets are transcribed from the PRD: the thirteen
resource types of section 2.4, the status vocabularies of section 3, and the
five role names of section 2.1.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

# --------------------------------------------------------------------------
# Roles (PRD 2.1): "The five roles are `QualityManager`, `QualityEvaluator`,
# `Agent`, `Supervisor` and `ComplianceAuditor`."
# --------------------------------------------------------------------------
Role = Literal[
    "QualityManager",
    "QualityEvaluator",
    "Agent",
    "Supervisor",
    "ComplianceAuditor",
]

ROLE_QUALITY_MANAGER = "QualityManager"
ROLE_QUALITY_EVALUATOR = "QualityEvaluator"
ROLE_AGENT = "Agent"
ROLE_SUPERVISOR = "Supervisor"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"

ALL_ROLES: List[str] = [
    ROLE_QUALITY_MANAGER,
    ROLE_QUALITY_EVALUATOR,
    ROLE_AGENT,
    ROLE_SUPERVISOR,
    ROLE_COMPLIANCE_AUDITOR,
]

# --------------------------------------------------------------------------
# Status vocabularies
# --------------------------------------------------------------------------
FormStatus = Literal["DRAFT", "ACTIVE", "RETIRED"]
AutoFailPolicy = Literal["ZERO_TOTAL", "COMPLIANCE_SECTION_ZERO"]
Channel = Literal["VOICE", "CHAT", "EMAIL"]
ConsentStatus = Literal["PENDING", "VERIFIED", "DENIED", "NOT_REQUIRED"]
ConsentOutcome = Literal["VERIFIED", "DENIED", "NOT_REQUIRED"]
DisclosureCode = Literal["RECORDING", "MINI_MIRANDA", "RATE_CHANGE", "THIRD_PARTY"]
FlaggedCategory = Literal[
    "PROFANITY", "NO_DISCLOSURE", "ESCALATION_REQUEST", "CONSENT_OBJECTION"
]
ScanStatus = Literal["CURRENT", "SUPERSEDED"]
PriorityTier = Literal["P1", "P2", "P3"]
PlanStatus = Literal["DRAFT", "OPEN", "CLOSED"]
SelectionStatus = Literal["SELECTED", "ASSIGNED", "EVALUATED", "EXCLUDED"]
SelectionSource = Literal["RANDOM", "TARGETED", "CUSTOMER_FLAGGED"]
ExclusionReason = Literal[
    "CONSENT_DENIED", "DUPLICATE_INTERACTION", "EVALUATOR_UNAVAILABLE", "PLAN_CLOSED_SWEEP"
]
ReviewStatus = Literal["DRAFT", "SUBMITTED", "FINALIZED", "REOPENED"]
FeedbackStatus = Literal["PENDING", "DELIVERED", "ACKNOWLEDGED", "DISPUTED"]
ComplianceResult = Literal["NOT_EVALUATED", "PASS", "FAIL"]
Agreement = Literal["AGREE", "DISAGREE"]
CalibrationStatus = Literal["CALIBRATED", "PROBATION", "SUSPENDED"]
SessionStatus = Literal["OPEN", "SCORING", "CLOSED_ALIGNED", "CLOSED_VARIANT", "VOID"]
Alignment = Literal["ALIGNED", "MINOR_VARIANCE", "MAJOR_VARIANCE"]
DisputeStatus = Literal[
    "SUBMITTED", "UNDER_REVIEW", "NEEDS_MORE_INFO", "UPHELD", "REJECTED"
]
DisputeOutcome = Literal["UPHELD", "REJECTED", "NEEDS_MORE_INFO"]
CoachingPlanStatus = Literal[
    "ASSIGNED", "IN_PROGRESS", "COMPLETED", "ESCALATED", "VOIDED"
]
CoachingTier = Literal["T1", "T2", "T3"]
CoachingState = Literal["NONE", "REQUIRED", "ACTIVE", "CLEARED"]

FORM_STATUSES: List[str] = ["DRAFT", "ACTIVE", "RETIRED"]
CHANNELS: List[str] = ["VOICE", "CHAT", "EMAIL"]
CONSENT_STATUSES: List[str] = ["PENDING", "VERIFIED", "DENIED", "NOT_REQUIRED"]
DISCLOSURE_CODES: List[str] = ["RECORDING", "MINI_MIRANDA", "RATE_CHANGE", "THIRD_PARTY"]
FLAGGED_CATEGORIES: List[str] = [
    "PROFANITY", "NO_DISCLOSURE", "ESCALATION_REQUEST", "CONSENT_OBJECTION"
]
PLAN_STATUSES: List[str] = ["DRAFT", "OPEN", "CLOSED"]
SELECTION_STATUSES: List[str] = ["SELECTED", "ASSIGNED", "EVALUATED", "EXCLUDED"]
SELECTION_SOURCES: List[str] = ["RANDOM", "TARGETED", "CUSTOMER_FLAGGED"]
EXCLUSION_REASONS: List[str] = [
    "CONSENT_DENIED", "DUPLICATE_INTERACTION", "EVALUATOR_UNAVAILABLE", "PLAN_CLOSED_SWEEP"
]
REVIEW_STATUSES: List[str] = ["DRAFT", "SUBMITTED", "FINALIZED", "REOPENED"]
FEEDBACK_STATUSES: List[str] = ["PENDING", "DELIVERED", "ACKNOWLEDGED", "DISPUTED"]
COMPLIANCE_RESULTS: List[str] = ["NOT_EVALUATED", "PASS", "FAIL"]
CALIBRATION_STATUSES: List[str] = ["CALIBRATED", "PROBATION", "SUSPENDED"]
SESSION_STATUSES: List[str] = [
    "OPEN", "SCORING", "CLOSED_ALIGNED", "CLOSED_VARIANT", "VOID"
]
ALIGNMENTS: List[str] = ["ALIGNED", "MINOR_VARIANCE", "MAJOR_VARIANCE"]
DISPUTE_STATUSES: List[str] = [
    "SUBMITTED", "UNDER_REVIEW", "NEEDS_MORE_INFO", "UPHELD", "REJECTED"
]
COACHING_PLAN_STATUSES: List[str] = [
    "ASSIGNED", "IN_PROGRESS", "COMPLETED", "ESCALATED", "VOIDED"
]
COACHING_TIERS: List[str] = ["T1", "T2", "T3"]
COACHING_STATES: List[str] = ["NONE", "REQUIRED", "ACTIVE", "CLEARED"]


# --------------------------------------------------------------------------
# Entity shapes.  Twelve of the thirteen resource types carry the standard
# system-managed properties `id`, `created_at`, `updated_at` and `version`
# (PRD 2.4); the calibration submission carries only `id` and `created_at`.
# --------------------------------------------------------------------------
class SystemFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class EvaluationForm(TypedDict, total=False):
    id: str
    name: str
    version_label: str
    status: FormStatus
    auto_fail_policy: AutoFailPolicy
    min_compliance_item_score: int
    behavior_weight_total: float
    compliance_behavior_count: int
    guidance_version: int
    activated_at: Optional[str]
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FormBehavior(TypedDict, total=False):
    id: str
    form_id: str
    code: str
    label: str
    weight_pct: float
    guidance_text: str
    compliance_critical: bool
    auto_fail_on_violation: bool
    max_points: int
    allows_not_applicable: bool
    guidance_version: int
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    external_ref: str
    full_name: str
    team_code: str
    hire_date: str
    quality_index_rolling: Optional[float]
    quality_index_period: Optional[float]
    open_compliance_findings: int
    consecutive_passing_evaluations: int
    coaching_state: CoachingState
    recognition_points: int
    created_at: str
    updated_at: str
    version: int


class Evaluator(TypedDict, total=False):
    id: str
    full_name: str
    max_open_assignments: int
    calibration_status: CalibrationStatus
    open_assignment_count: int
    last_deviation_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Interaction(TypedDict, total=False):
    id: str
    agent_id: str
    channel: Channel
    started_at: str
    ended_at: str
    duration_seconds: int
    required_disclosures: List[str]
    captured_disclosures: List[str]
    customer_flagged: bool
    csat_score: Optional[int]
    repeat_contact_within_72h: bool
    recording_consent_status: ConsentStatus
    compliance_hold: bool
    sampled_count: int
    created_at: str
    updated_at: str
    version: int


class AnalyticsScan(TypedDict, total=False):
    id: str
    interaction_id: str
    silence_pct: float
    sentiment_delta: float
    flagged_categories: List[str]
    risk_score: float
    priority_tier: PriorityTier
    status: ScanStatus
    created_at: str
    updated_at: str
    version: int


class SamplePlan(TypedDict, total=False):
    id: str
    form_id: str
    period_start: str
    period_end: str
    per_agent_target_volume: int
    source_mix: Dict[str, int]
    status: PlanStatus
    pinned_form_guidance_version: Optional[int]
    selections_count: int
    excluded_count: int
    targeted_reserved_count: int
    targeted_reserve_by_agent: Dict[str, int]
    agent_volume_attainment: Dict[str, Any]
    created_at: str
    updated_at: str
    version: int


class SampleSelection(TypedDict, total=False):
    id: str
    plan_id: str
    interaction_id: str
    agent_id: str
    source: SelectionSource
    status: SelectionStatus
    assigned_evaluator_id: Optional[str]
    review_window_start: Optional[str]
    review_window_end: Optional[str]
    exclusion_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict, total=False):
    id: str
    selection_id: str
    evaluator_id: str
    form_id: str
    agent_id: str
    pinned_guidance_version: int
    item_scores: Dict[str, Any]
    weighted_score: Optional[float]
    raw_weighted_score: Optional[float]
    adjusted_weighted_score: Optional[float]
    auto_fail_triggered: bool
    compliance_result: ComplianceResult
    review_status: ReviewStatus
    feedback_status: FeedbackStatus
    submitted_at: Optional[str]
    feedback_delivered_at: Optional[str]
    agreement: Optional[Agreement]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    evaluation_id: str
    agent_id: str
    disputed_behavior_codes: List[str]
    rationale: str
    status: DisputeStatus
    reviewer_evaluator_id: Optional[str]
    round_count: int
    adjusted_item_scores: Optional[Dict[str, Any]]
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CalibrationSession(TypedDict, total=False):
    id: str
    form_id: str
    interaction_id: str
    scheduled_start: str
    scheduled_end: str
    benchmark_item_scores: Dict[str, Any]
    benchmark_weighted_score: Optional[float]
    status: SessionStatus
    participant_count: int
    variance_pct: Optional[float]
    mean_abs_deviation: Optional[float]
    guidance_updates_applied: int
    created_at: str
    updated_at: str
    version: int


class CalibrationSubmission(TypedDict, total=False):
    """Immutable: carries only `id` and `created_at` among the system fields."""

    id: str
    session_id: str
    evaluator_id: str
    item_scores: Dict[str, Any]
    weighted_score: Optional[float]
    deviation_pct: Optional[float]
    alignment: Optional[Alignment]
    created_at: str


class CoachingPlan(TypedDict, total=False):
    id: str
    agent_id: str
    source_evaluation_id: str
    assigned_supervisor_id: str
    target_score: float
    deficit_pct: float
    coaching_tier: CoachingTier
    escalation_tier: CoachingTier
    required_session_count: int
    completed_session_count: int
    due_at: str
    status: CoachingPlanStatus
    escalation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualitySummary(TypedDict, total=False):
    quality_index_rolling: Optional[float]
    quality_index_period: Optional[float]
    evaluations_considered: int
    paired_sample_size: int
    csat_gap_paired: Optional[float]
    csat_gap_all: Optional[float]
    repeat_contact_rate: Optional[float]
