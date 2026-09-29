"""
TypedDict shapes for every resource of the Win-Loss Intelligence API.

Per the PRD, `id`, `created_at`, `updated_at` and `version` are carried by every
resource with exactly one deliberate exception: an `InterviewResponse` row
"carries only `id` and `created_at` — both `updated_at` and `version` are absent
from it entirely." `InterviewResponseDict` therefore omits both fields.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int


class ProgramDict(CommonFields, total=False):
    name: str
    fiscal_quarter: str
    incentive_budget_usd: float
    interview_incentive_cap_usd: float
    min_deal_value_usd: float
    required_question_keys: List[str]
    max_open_interviews_per_analyst: int
    independence_mode: str
    status: str
    posture: str
    guide_version: int
    incentive_committed_usd: float
    incentive_paid_usd: float


class CompetitorDict(CommonFields, total=False):
    program_id: str
    name: str
    tier: str
    status: str
    published_battlecard_count: int
    ratified_loss_count: int
    win_rate_vs: Optional[float]


class DealDict(CommonFields, total=False):
    program_id: str
    crm_deal_ref: str
    outcome: str
    acr_usd: float
    close_date: str
    segment: str
    sales_rep_user_ref: str
    primary_competitor_id: Optional[str]
    research_status: str
    attribution_status: str
    interview_coverage_count: int
    sampling_frame_id: Optional[str]
    stratum: Optional[str]
    selection_rank_score: Optional[float]


class AnalystDict(CommonFields, total=False):
    program_id: str
    full_name: str
    linked_user_ref: str
    employment_type: str
    certified_until: str
    sales_org_member: bool
    status: str
    open_interview_count: int
    committed_minutes: int


class BuyerContactDict(CommonFields, total=False):
    deal_id: str
    email: str
    full_name: str
    title_band: str
    incentive_eligibility: str
    consent_status: str
    completed_interview_count: int
    last_completed_interview_end_at: Optional[str]


class SamplingFrameDict(CommonFields, total=False):
    program_id: str
    label: str
    window_start: str
    window_end: str
    quota_won: int
    quota_lost: int
    quota_no_decision: int
    selection_basis: str
    status: str
    open_won_slots: int
    open_lost_slots: int
    open_no_decision_slots: int
    selected_won_count: int
    selected_lost_count: int
    selected_no_decision_count: int
    coverage_ratio: float


class InterviewDict(CommonFields, total=False):
    deal_id: str
    buyer_contact_id: str
    analyst_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    status: str
    incentive_status: str
    incentive_provisional_usd: Optional[float]
    incentive_final_usd: Optional[float]
    coverage_complete: bool
    reschedule_count: int
    guide_version_pinned: int
    required_question_keys_pinned: List[str]
    cancel_reason: Optional[str]


class InterviewResponseDict(TypedDict, total=False):
    """Append-only evidence: only `id` and `created_at` are system-managed here."""

    id: str
    created_at: str
    interview_id: str
    question_key: str
    verbatim_text: str
    recorded_at: str
    rating: Optional[int]
    competitor_name_verbatim: Optional[str]


class LossReasonDict(CommonFields, total=False):
    program_id: str
    code: str
    label: str
    parent_reason_id: Optional[str]
    depth: int
    is_leaf: bool
    status: str
    ratified_attribution_count: int


class LossAttributionDict(CommonFields, total=False):
    deal_id: str
    primary_reason_id: str
    secondary_reason_id: Optional[str]
    weight_primary: float
    weight_secondary: float
    status: str
    authored_by_analyst_id: str
    ratified_by_analyst_id: Optional[str]
    confidence_score: float


class BattlecardDict(CommonFields, total=False):
    competitor_id: str
    title: str
    version_label: str
    status: str
    risk_index_pre: float
    risk_index_final: float
    approved_claim_count: int
    conditional_claim_count: int
    rejected_claim_count: int
    corroborated_claim_count: int
    adoption_rate: float
    assigned_count: int
    trained_count: int
    published_at: Optional[str]
    reopen_count: int
    reopen_reason: Optional[str]


class BattlecardClaimDict(CommonFields, total=False):
    battlecard_id: str
    claim_text: str
    claim_type: str
    evidence_response_ids: List[str]
    substantiation_score: float
    substantiation_level: str
    risk_class: str
    legal_status: str
    conditions_note: Optional[str]
    decided_at: Optional[str]


class EnablementAssignmentDict(CommonFields, total=False):
    battlecard_id: str
    sales_rep_user_ref: str
    due_at: str
    assigned_at: str
    status: str
    attempt_count: int
    quiz_score: Optional[int]
    completed_at: Optional[str]


class ProductGapDict(CommonFields, total=False):
    program_id: str
    source_response_id: str
    additional_response_ids: List[str]
    gap_summary: str
    derived_competitor_id: Optional[str]
    linked_deal_count: int
    affected_acr_usd: float
    impact_score: float
    roadmap_priority_band: str
    status: str
    roadmap_epic_ref: Optional[str]


class TrendRowDict(TypedDict, total=False):
    root_reason_id: str
    root_reason_code: str
    weighted_total: float
    share: float


class TrendSegmentDict(TypedDict, total=False):
    segment: str
    segment_total: float
    rows: List[TrendRowDict]


class LossTrendsDict(TypedDict, total=False):
    basis: str
    window_start: str
    window_end: str
    attribution_count: int
    segments: List[TrendSegmentDict]


class EnablementSweepDict(TypedDict, total=False):
    expired_count: int
    expired_assignment_ids: List[str]
    recomputed_battlecard_ids: List[str]


class ClockDict(TypedDict, total=False):
    current_utc: str


Payload = Dict[str, Any]
Headers = Dict[str, str]
