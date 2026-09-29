"""Typed shapes for every persisted resource and for the response envelope.

These mirror the field names the PRD declares, exactly. They are used for
editor support and for the field-presence assertions in ``assertions.py``;
nothing here changes runtime behaviour.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    total_count: int
    has_more: bool
    limit: int
    offset: int


class ErrorPayload(TypedDict):
    error_id: str
    message: str


# ---------------------------------------------------------------------------
# Common system-managed fields
# ---------------------------------------------------------------------------


class VersionedResource(TypedDict):
    """The four system-managed fields carried by ten of the eleven resources."""

    id: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


class Account(VersionedResource):
    external_handle: str
    region_code: str
    tier: str
    strike_points: int
    standing: str
    lifetime_removed_count: int
    appeal_credits_remaining: int


# ---------------------------------------------------------------------------
# ContentItem
# ---------------------------------------------------------------------------


class ContentItem(VersionedResource):
    account_id: str
    language: str
    media_kind: str
    graphic_weight: int
    posted_at: str
    visibility_status: str
    review_status: str
    open_case_count: int
    reinstated_at: Optional[str]


# ---------------------------------------------------------------------------
# PolicyCategory
# ---------------------------------------------------------------------------


class PolicyCategory(VersionedResource):
    code: str
    name: str
    parent_category_id: Optional[str]
    severity_tier: str
    specialty: str
    status: str
    active_version_id: Optional[str]


# ---------------------------------------------------------------------------
# PolicyVersion
# ---------------------------------------------------------------------------


class PolicyVersion(VersionedResource):
    policy_category_id: str
    version_label: str
    status: str
    auto_action_threshold: float
    review_floor: float
    enforcement_action: str
    appeal_window_hours: int
    review_sla_minutes: int
    requires_recertification: bool
    authored_by_user_id: str
    activated_by_user_id: Optional[str]
    activated_at: Optional[str]
    supersedes_version_id: Optional[str]
    backtest_sample_size: int
    backtest_divergence_rate: Optional[float]
    backtest_completed_at: Optional[str]


# ---------------------------------------------------------------------------
# ReviewQueue
# ---------------------------------------------------------------------------


class ReviewQueue(VersionedResource):
    name: str
    policy_category_id: str
    language: str
    specialty: str
    open_case_count: int
    unassigned_case_count: int


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------


class Reviewer(VersionedResource):
    display_name: str
    languages: List[str]
    specialties: List[str]
    role_class: str
    status: str
    utc_offset_minutes: int
    shift_start_local_hour: int
    shift_end_local_hour: int
    max_concurrent_cases: int
    daily_exposure_cap_points: int
    certified_policy_version_ids: List[str]
    pending_retraining_version_ids: List[str]
    open_case_count: int
    exposure_points_today: int
    audited_count: int
    agree_count: int
    appealed_count: int
    upheld_appeal_count: int
    accuracy_score_audit_only: Optional[float]
    accuracy_score_blended: Optional[float]
    wellness_breaks_taken: int
    wellness_break_start: Optional[str]
    wellness_break_end: Optional[str]


# ---------------------------------------------------------------------------
# DetectionSignal - the one resource with neither updated_at nor version
# ---------------------------------------------------------------------------


class DetectionSignal(TypedDict):
    id: str
    created_at: str
    content_item_id: str
    policy_category_code: str
    classifier_id: str
    classifier_confidence: float
    effective_confidence: float
    disposition: str
    resulting_case_id: Optional[str]
    pinned_policy_version_label: Optional[str]


# ---------------------------------------------------------------------------
# ModerationCase
# ---------------------------------------------------------------------------


class ModerationCase(VersionedResource):
    content_item_id: str
    policy_version_id: str
    detection_signal_id: Optional[str]
    queue_id: Optional[str]
    origin: str
    status: str
    escalation_tier: int
    escalation_reason: Optional[str]
    assigned_reviewer_id: Optional[str]
    reassignment_count: int
    requires_recertified_review: bool
    exposure_points_charged: int
    sla_due_at: Optional[str]
    sla_breached: bool
    decision_source: Optional[str]
    decision_outcome: Optional[str]
    decided_by_reviewer_id: Optional[str]
    decided_at: Optional[str]
    strike_points_applied: int
    appeal_deadline_at: Optional[str]
    is_overturned: bool
    legal_jurisdiction: Optional[str]
    legal_reference: Optional[str]


# ---------------------------------------------------------------------------
# Appeal
# ---------------------------------------------------------------------------


class Appeal(VersionedResource):
    case_id: str
    account_id: str
    grounds_text: str
    status: str
    filed_at: str
    independent_reviewer_id: Optional[str]
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    reinstated_content: bool


# ---------------------------------------------------------------------------
# AuditSample
# ---------------------------------------------------------------------------


class AuditSample(VersionedResource):
    case_id: str
    auditor_reviewer_id: str
    sampling_reason: str
    status: str
    verdict: Optional[str]
    correct_outcome: Optional[str]
    audited_at: Optional[str]
    dispute_note: Optional[str]
    disputed_at: Optional[str]
    counts_toward_accuracy: bool


# ---------------------------------------------------------------------------
# TransparencyReport
# ---------------------------------------------------------------------------


class CategoryRate(TypedDict):
    category_code: str
    appealed: int
    overturned: int
    rate: float


class TransparencyReport(VersionedResource):
    period_start: str
    period_end: str
    status: str
    variant: Optional[str]
    computed_at: Optional[str]
    published_at: Optional[str]
    enforcement_volume: int
    removal_volume: int
    age_gate_volume: int
    warn_volume: int
    overturn_adjusted_volume: int
    appeal_count: int
    appeal_overturn_rate: float
    legal_request_count: int
    legal_grant_rate: float
    category_rate_breakdown: List[CategoryRate]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


class ClockState(TypedDict):
    current_utc: str


JsonDict = Dict[str, Any]
