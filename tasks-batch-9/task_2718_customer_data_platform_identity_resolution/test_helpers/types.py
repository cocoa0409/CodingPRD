"""Typed shapes for the resources the API returns.

Every resource carries the four common fields id, created_at, updated_at and
version. Numeric fields are typed int or float because the PRD requires every
numeric to be emitted as a JSON number, never as a string.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


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


class ClockState(TypedDict):
    current_utc: str


class SourceSystem(CommonFields, total=False):
    code: str
    display_name: str
    channel_type: str
    trust_tier: int
    dq_scoring_mode: str
    pii_completeness_floor: float
    status: str
    dq_window_start_at: Optional[str]
    submitted_record_total: int
    valid_record_total: int
    dq_pass_rate: float
    quarantine_count: int
    last_reinstated_at: Optional[str]


class RawRecord(TypedDict, total=False):
    external_id: str
    email_raw: Optional[str]
    phone_raw: Optional[str]
    loyalty_number: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    postal_code: Optional[str]
    address_line: Optional[str]
    event_timestamp: str
    consent_signals: List[Dict[str, Any]]


class IngestBatch(CommonFields, total=False):
    source_system_id: str
    batch_label: str
    records: List[RawRecord]
    record_count: int
    valid_record_count: Optional[int]
    invalid_record_count: Optional[int]
    dq_score: Optional[float]
    dq_failure_breakdown: Optional[Dict[str, int]]
    status: str
    retry_round: int
    rejection_reason: Optional[str]
    validated_at: Optional[str]
    promoted_at: Optional[str]
    new_profile_count: int
    matched_deterministic_count: int
    matched_probabilistic_count: int


class Profile(CommonFields, total=False):
    origin_batch_id: Optional[str]
    primary_source_system_id: Optional[str]
    household_id: Optional[str]
    merged_into_profile_id: Optional[str]
    email_norm: Optional[str]
    phone_norm: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    postal_code: Optional[str]
    address_hash: Optional[str]
    loyalty_number: Optional[str]
    loyalty_tier: str
    lifetime_value_cents: int
    channel_engagement_score: float
    inferred_health_interest: Optional[str]
    inferred_ethnicity_affinity: Optional[str]
    precise_geolocation_grid: Optional[str]
    resolution_status: str
    privacy_status: str
    activatable_channels: List[str]
    source_record_count: int
    contributing_source_system_codes: List[str]
    consent_record_count: int
    last_activity_at: Optional[str]


class ChannelResolution(TypedDict, total=False):
    channel: str
    activatable: bool
    reason: str
    precedence_rank: Optional[int]
    consent_record_id: Optional[str]


class ConsentState(TypedDict, total=False):
    profile_id: str
    evaluated_at: str
    activatable_channels: List[str]
    channel_engagement_score: float
    channels: List[ChannelResolution]


class Household(CommonFields, total=False):
    address_hash: str
    sequence_no: int
    member_count: int
    status: str
    dominant_last_name: Optional[str]
    combined_lifetime_value_cents: int


class MatchRule(CommonFields, total=False):
    code: str
    rule_kind: str
    deterministic_key: Optional[str]
    missing_identifier_policy: str
    auto_merge_threshold: float
    review_floor: float
    min_precision: float
    status: str
    confirmed_count: int
    rejected_count: int
    precision_estimate: float


class Evidence(TypedDict, total=False):
    email_similarity: Optional[float]
    phone_similarity: Optional[float]
    name_similarity: Optional[float]
    address_similarity: Optional[float]


class IdentityLink(CommonFields, total=False):
    left_profile_id: str
    right_profile_id: str
    match_rule_id: str
    survivor_profile_id: Optional[str]
    evidence: Evidence
    match_method: str
    confidence: float
    status: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    void_reason: Optional[str]


class ConsentRecord(CommonFields, total=False):
    profile_id: str
    source_system_id: str
    channel: str
    purpose: str
    consent_state: str
    captured_at: str
    expires_at: Optional[str]
    status: str
    precedence_rank: int


class SuppressionEntry(CommonFields, total=False):
    profile_id: str
    deletion_request_id: Optional[str]
    entry_type: str
    reason_code: str
    effective_at: str
    expires_at: Optional[str]
    status: str
    created_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    released_at: Optional[str]


class SegmentCriterion(TypedDict, total=False):
    attribute: str
    operator: str
    value: Any


class Segment(CommonFields, total=False):
    name: str
    criteria: List[SegmentCriterion]
    uses_sensitive_attributes: bool
    governance_justification: Optional[str]
    governance_valid_days: int
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    sensitive_use_approved: bool
    approved_at: Optional[str]
    governance_expires_at: Optional[str]
    rejection_count: int
    member_count: int
    active_activation_count: int


class Destination(CommonFields, total=False):
    code: str
    platform_kind: str
    channel: str
    hashing_algorithm: str
    match_rate_basis: str
    min_match_rate: float
    min_audience_size: int
    daily_hash_quota: int
    remaining_daily_hash_quota: int
    quota_reset_on: str
    cooldown_minutes: int
    max_concurrent_activations: int
    sensitive_attribute_permitted: bool
    deletion_ack_sla_hours: int
    status: str
    underperforming_activation_count: int


class AttributedConversion(TypedDict, total=False):
    profile_id: str
    converted_at: str
    revenue_cents: int


class Activation(CommonFields, total=False):
    segment_id: str
    destination_id: str
    window_start_at: str
    window_end_at: str
    status: str
    candidate_count: int
    audience_size: int
    suppressed_count: int
    dispatched_hash_count: int
    unusable_hash_count: int
    vendor_matched_count: int
    gross_match_rate: Optional[float]
    net_match_rate: Optional[float]
    effective_match_rate: Optional[float]
    attributed_conversion_count: int
    attributed_conversions: List[AttributedConversion]
    dispatched_at: Optional[str]
    paused_reason: Optional[str]
    terminated_at: Optional[str]


class SegmentPerformance(TypedDict, total=False):
    segment_id: str
    attribution_basis: str
    member_count: int
    conversion_count: int
    unique_converter_count: int
    attributed_revenue_cents: int
    revenue_per_member_cents: int


class SegmentOverlap(TypedDict, total=False):
    segment_id: str
    other_segment_id: str
    segment_member_count: int
    other_segment_member_count: int
    overlap_count: int
    union_count: int
    jaccard_index: float
    containment_in_other: float
    containment_of_other: float


class DeletionRequest(CommonFields, total=False):
    profile_id: str
    request_origin: str
    requester_reference: str
    status: str
    total_vendor_task_count: int
    pending_vendor_task_count: int
    acknowledged_vendor_task_count: int
    failed_vendor_task_count: int
    timed_out_vendor_task_count: int
    propagated_at: Optional[str]
    verified_at: Optional[str]
    blocked_reason: Optional[str]


class VendorDeletionTask(CommonFields, total=False):
    deletion_request_id: str
    destination_id: str
    status: str
    dispatched_at: Optional[str]
    ack_deadline_at: Optional[str]
    acknowledged_at: Optional[str]
    deletion_evidence_reference: Optional[str]
    acknowledged_record_count: Optional[int]
    attempt_count: int


class RetentionRun(TypedDict, total=False):
    run_at: str
    expired_consent_record_count: int
    expired_suppression_entry_count: int
    timed_out_vendor_task_count: int
    partially_verified_deletion_request_count: int
    governance_expired_segment_count: int
    paused_activation_count: int
    quota_reset_destination_count: int
