"""Domain types for the Dubbing & Localization Media API.

Entity TypedDicts, status enums and the role enum. Every one of the fourteen
resource types carries id, created_at, updated_at and version (PRD 2.4).
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PRODUCTION_COORDINATOR = "ProductionCoordinator"
    ADAPTOR = "Adaptor"
    NATIVE_REVIEWER = "NativeReviewer"
    CASTING_DIRECTOR = "CastingDirector"
    VOICE_TALENT_USER = "VoiceTalentUser"
    MIX_ENGINEER = "MixEngineer"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ContentRating(str, Enum):
    GENERAL = "GENERAL"
    TEEN = "TEEN"
    MATURE = "MATURE"


class CutStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class StemLayout(str, Enum):
    STEREO_ME = "STEREO_ME"
    FIVE_ONE_ME = "FIVE_ONE_ME"


class UnionStatus(str, Enum):
    UNION = "UNION"
    NON_UNION = "NON_UNION"


class VoiceTalentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StudioStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


class PriorityTier(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"
    RUSH = "RUSH"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCRIPT_IN_PROGRESS = "SCRIPT_IN_PROGRESS"
    CASTING = "CASTING"
    RECORDING = "RECORDING"
    MIXING = "MIXING"
    QC = "QC"
    DELIVERED = "DELIVERED"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class AdaptationStatus(str, Enum):
    DRAFT = "DRAFT"
    TRANSLATED = "TRANSLATED"
    ADAPTED = "ADAPTED"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"


class CastingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    HOLD_REQUESTED = "HOLD_REQUESTED"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RECORDED = "RECORDED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"


class PaymentDimension(str, Enum):
    """CastingAssignment.payment_status — the second, independent dimension."""

    UNBILLED = "UNBILLED"
    ACCRUED = "ACCRUED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class UsageVariant(str, Enum):
    BUYOUT = "BUYOUT"
    RESIDUAL = "RESIDUAL"


class SessionStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class WaitlistedReason(str, Enum):
    STUDIO_SLOT_CONFLICT = "STUDIO_SLOT_CONFLICT"
    STUDIO_DAILY_CAPACITY = "STUDIO_DAILY_CAPACITY"


class MixJobStatus(str, Enum):
    QUEUED = "QUEUED"
    STEM_CHECKED = "STEM_CHECKED"
    MIXED = "MIXED"
    CONFORMED = "CONFORMED"
    SUPERSEDED = "SUPERSEDED"


class QualityReviewStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    PASSED = "PASSED"
    FAILED_RETAKE = "FAILED_RETAKE"


class ReviewDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RetakeItemStatus(str, Enum):
    OPEN = "OPEN"
    RECORDED = "RECORDED"
    WAIVED = "WAIVED"


class DefectCategory(str, Enum):
    LIPSYNC = "LIPSYNC"
    PERFORMANCE = "PERFORMANCE"
    AUDIO = "AUDIO"
    TRANSLATION = "TRANSLATION"


class TalentPaymentStatus(str, Enum):
    ACCRUED = "ACCRUED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class OnConflict(str, Enum):
    REJECT = "REJECT"
    WAITLIST = "WAITLIST"


class HoldResponse(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class AdaptationReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


TERRITORIES = ["US", "CA", "UK", "DE", "FR", "JP", "BR", "AU", "ROW"]


# --------------------------------------------------------------------------
# Entity TypedDicts — all fourteen carry the four common properties (PRD 2.4)
# --------------------------------------------------------------------------
class Title(TypedDict):
    id: str
    title_code: str
    source_language: str
    runtime_seconds: int
    content_rating: str
    cut_count: int
    created_at: str
    updated_at: str
    version: int


class Cut(TypedDict):
    id: str
    title_id: str
    derived_from_cut_id: Optional[str]
    cut_code: str
    loop_count: int
    runtime_seconds: int
    conform_delta_seconds: int
    lineage_depth: int
    derived_cut_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Character(TypedDict):
    id: str
    title_id: str
    character_code: str
    loop_count: int
    is_principal: bool
    screen_time_seconds: int
    created_at: str
    updated_at: str
    version: int


class PlatformSpec(TypedDict):
    id: str
    platform_code: str
    loudness_target_lufs: float
    stem_layout: str
    max_lipsync_deviation_ms: int
    min_fidelity_score: float
    qc_pass_threshold: float
    metadata_fields_required: List[str]
    created_at: str
    updated_at: str
    version: int


class VoiceTalent(TypedDict):
    id: str
    full_name: str
    language_code: str
    union_status: str
    base_rate_cents_per_hour: int
    licensed_territories: List[str]
    max_daily_recorded_minutes: int
    held_minutes: int
    recorded_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Studio(TypedDict):
    id: str
    name: str
    territory: str
    hourly_rate_cents: int
    turnaround_buffer_minutes: int
    daily_capacity_minutes: int
    booked_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LocalizationOrder(TypedDict):
    id: str
    cut_id: str
    platform_spec_id: str
    target_language: str
    territory: str
    priority_tier: str
    budget_cap_cents: int
    status: str
    committed_cents: int
    released_cents: int
    gross_accrued_cents: int
    retake_cycles: int
    metadata_locale_fields: Dict[str, Any]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScriptAdaptation(TypedDict):
    id: str
    order_id: str
    status: str
    revision_round: int
    adapted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    declared_loop_count: int
    measured_sync_deviation_ms_total: int
    lines_over_deviation: int
    provisional_fidelity_score: Optional[float]
    final_fidelity_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CastingAssignment(TypedDict):
    id: str
    order_id: str
    character_id: str
    talent_id: str
    casting_status: str
    payment_status: str
    usage_variant: str
    agreed_rate_cents_per_hour: int
    superseded_by_id: Optional[str]
    recorded_minutes: int
    retake_minutes: int
    created_at: str
    updated_at: str
    version: int


class RecordingSession(TypedDict):
    id: str
    order_id: str
    studio_id: str
    casting_assignment_id: str
    status: str
    start_utc: str
    end_utc: str
    duration_minutes: int
    is_retake: bool
    session_cost_cents: int
    waitlisted_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MixJob(TypedDict):
    id: str
    order_id: str
    status: str
    stem_layout: str
    me_stem_present: bool
    loudness_lufs: Optional[float]
    mix_round: int
    conformance_index: Optional[float]
    created_at: str
    updated_at: str
    version: int


class QualityReview(TypedDict):
    id: str
    order_id: str
    mix_job_id: str
    status: str
    round_number: int
    reviewer_user_id: Optional[str]
    sampled_loop_count: int
    defect_count: int
    pass_rate: Optional[float]
    decision: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetakeItem(TypedDict):
    id: str
    quality_review_id: str
    casting_assignment_id: str
    loop_ref: str
    defect_category: str
    estimated_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TalentPayment(TypedDict):
    id: str
    casting_assignment_id: str
    talent_id: str
    variant: str
    territory_scope: List[str]
    base_fee_cents: int
    usage_fee_cents: int
    total_fee_cents: int
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
