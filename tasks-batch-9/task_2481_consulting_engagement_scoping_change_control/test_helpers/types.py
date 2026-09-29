"""Typed shapes of the API resources, transcribed from the PRD narratives.

Every family except ``SatisfactionAssessment`` carries the full audit set of
``id``, ``created_at``, ``updated_at`` and ``version`` (PRD 2.4). A satisfaction
assessment is immutable and therefore carries only ``id`` and ``created_at``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class AuditedResource(TypedDict):
    """The audit properties every family but SatisfactionAssessment carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Client(AuditedResource, total=False):
    name: str
    client_code: str
    industry_code: str
    decision_process: str
    stated_budget_authority_cents: int
    adverse_party_codes: List[str]
    status: str
    completed_engagement_count: int
    at_risk_engagement_count: int


class Consultant(AuditedResource, total=False):
    name: str
    grade: str
    practice_code: str
    cost_rate_cents_per_hour: int
    quality_reviewer_certified: bool
    active_lead_deliverable_count: int


class Opportunity(AuditedResource, total=False):
    client_id: str
    owner_partner_consultant_id: str
    scoping_manager_consultant_id: str
    requested_practice_code: str
    estimated_value_cents: int
    stated_budget_cents: int
    verified_budget_cents: Optional[int]
    decision_maker_identified: bool
    target_start_date: str
    target_end_date: str
    objective_summary: str
    origin_engagement_id: Optional[str]
    status: str
    conflict_status: str
    screened_adverse_party_codes: List[str]
    assumptions: List[str]
    exclusions: List[str]
    client_responsibilities: List[str]
    qualification_score_intake: float
    qualification_score_verified: Optional[float]
    total_estimated_hours: Optional[float]
    scope_discount_pct: Optional[float]
    baseline_effort_cost_cents: Optional[int]
    longest_dependency_chain: Optional[int]
    baselined_at: Optional[str]


class Deliverable(AuditedResource, total=False):
    opportunity_id: str
    name: str
    primary_grade: str
    effort_hours_estimate: float
    completion_weight_pct: float
    acceptance_criteria: str
    planned_start_date: str
    planned_end_date: str
    depends_on_deliverable_id: Optional[str]
    status: str
    prior_status: Optional[str]
    hours_consumed: float
    lead_consultant_id: Optional[str]
    line_cost_cents: Optional[int]


class Sow(AuditedResource, total=False):
    opportunity_id: str
    pricing_model: str
    acceptance_summary: str
    target_bonus_cents: Optional[int]
    supersedes_sow_id: Optional[str]
    status: str
    revision_round: int
    risk_score: int
    risk_premium_pct: float
    pinned_scope_discount_pct: float
    baseline_effort_cost_cents: int
    quoted_fee_cents: int
    fixed_component_cents: int
    at_risk_component_cents: int
    not_to_exceed_cents: Optional[int]
    signature_name: Optional[str]
    signed_at: Optional[str]


class Engagement(AuditedResource, total=False):
    sow_id: str
    opportunity_id: str
    client_id: str
    lead_partner_consultant_id: str
    engagement_manager_consultant_id: Optional[str]
    pricing_model: str
    original_fee_cents: int
    contracted_fee_cents: int
    contracted_hours: float
    not_to_exceed_cents: Optional[int]
    pinned_scope_discount_pct: float
    pinned_risk_premium_pct: float
    planned_start_date: str
    planned_end_date: str
    delivery_state: str
    economics_state: str
    approved_hours_burned: float
    burned_cost_cents: int
    cumulative_change_pct: float
    suspended_deliverable_count: int
    schedule_relief_days: int
    leadership_review_required: bool
    closed_at: Optional[str]


class EconomicsView(TypedDict):
    """The read-only computed view of PRD 3.7 - six keys and nothing else."""

    hours_burn_pct: float
    completion_pct: float
    progress_variance_pct: float
    projected_cost_cents: int
    projected_margin_pct: float
    economics_state: str


class ChangeRequest(AuditedResource, total=False):
    engagement_id: str
    origin: str
    summary: str
    added_hours: float
    added_grade: str
    requested_schedule_days: int
    supersedes_change_request_id: Optional[str]
    status: str
    requested_by_consultant_id: str
    leadership_approver_consultant_id: Optional[str]
    routing: Optional[str]
    gross_delta_cents: Optional[int]
    fee_delta_cents: Optional[int]
    cumulative_change_pct_at_assessment: Optional[float]
    approved_at: Optional[str]
    rescinded_at: Optional[str]


class TimeEntry(AuditedResource, total=False):
    engagement_id: str
    deliverable_id: str
    consultant_id: str
    week_ending_date: str
    hours: float
    billable: bool
    status: str
    cost_cents: int
    billed_value_cents: int
    reversal_reason: Optional[str]


class QualityReview(AuditedResource, total=False):
    engagement_id: str
    reviewer_consultant_id: str
    checkpoint_type: str
    window_start_date: str
    window_end_date: str
    status: str
    outcome: Optional[str]
    findings_severity: str
    note: Optional[str]


class RiskEscalation(AuditedResource, total=False):
    engagement_id: str
    source: str
    source_quality_review_id: Optional[str]
    severity: str
    opened_reason: str
    status: str
    leadership_response: Optional[str]
    resolved_at: Optional[str]


class SatisfactionAssessment(TypedDict, total=False):
    """Immutable: only ``id`` and ``created_at`` audit properties (PRD 2.4)."""

    id: str
    created_at: str
    engagement_id: str
    delivery_score: int
    value_score: int
    communication_score: int
    would_refer: bool
    comments: Optional[str]
    csat_score: float


JsonDict = Dict[str, Any]
