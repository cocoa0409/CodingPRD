"""Domain types for the Recruitment Marketing & Employer Brand Program API.

Entity shapes, status enums and the role enum, all named exactly as the PRD names them.
Mutable resources carry ``updated_at`` and ``version``; the four immutable event kinds
(channel-preference signals, touchpoints, nurture send-evaluation rows and budget ledger
entries) carry only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------- roles

class UserRole(str, Enum):
    BRAND_PROGRAM_LEAD = "BrandProgramLead"
    PERSONA_RESEARCHER = "PersonaResearcher"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    MEDIA_BUYER = "MediaBuyer"
    COMMUNITY_MANAGER = "CommunityManager"
    RECRUITING_OPS = "RecruitingOps"
    CANDIDATE = "Candidate"
    ANONYMOUS = "Anonymous"


# ------------------------------------------------------------------ status enums

class AttributionModel(str, Enum):
    LINEAR = "LINEAR"
    POSITION_BASED = "POSITION_BASED"


class ChannelType(str, Enum):
    JOB_BOARD = "JOB_BOARD"
    SOCIAL = "SOCIAL"
    PROGRAMMATIC = "PROGRAMMATIC"
    CAREER_SITE = "CAREER_SITE"
    EVENT = "EVENT"
    EMAIL = "EMAIL"


PAYABLE_CHANNEL_TYPES = ["JOB_BOARD", "SOCIAL", "PROGRAMMATIC"]
ORGANIC_CHANNEL_TYPES = ["CAREER_SITE", "EVENT", "EMAIL"]


class PacingStatus(str, Enum):
    PACING_UNKNOWN = "PACING_UNKNOWN"
    ON_TARGET = "ON_TARGET"
    THROTTLED = "THROTTLED"
    IDLE = "IDLE"


class MixMethod(str, Enum):
    SURVEY_WEIGHTED = "SURVEY_WEIGHTED"
    ENGAGEMENT_WEIGHTED = "ENGAGEMENT_WEIGHTED"


class PersonaState(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class PersonaDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


class ContentStatus(str, Enum):
    DRAFT = "DRAFT"
    OPTIMIZED = "OPTIMIZED"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class ComplianceStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class ComplianceDecision(str, Enum):
    CLEAR = "CLEAR"
    FLAG = "FLAG"


class CostTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class FlightState(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    PAUSED_PACING = "PAUSED_PACING"
    SUSPENDED_CONTENT = "SUSPENDED_CONTENT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReleaseReason(str, Enum):
    PACING_THROTTLE = "PACING_THROTTLE"
    COMPLIANCE_SUSPENSION = "COMPLIANCE_SUSPENSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ApplicationStatus(str, Enum):
    STARTED = "STARTED"
    SUBMITTED = "SUBMITTED"
    SCREENED = "SCREENED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"


SUBMITTED_APPLICATION_STATUSES = ["SUBMITTED", "SCREENED", "QUALIFIED", "DISQUALIFIED"]


class TouchType(str, Enum):
    IMPRESSION = "IMPRESSION"
    CLICK = "CLICK"
    ORGANIC_VISIT = "ORGANIC_VISIT"
    EVENT_SCAN = "EVENT_SCAN"
    EMAIL_CLICK = "EMAIL_CLICK"
    REFERRAL = "REFERRAL"


class ConsentStatus(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    SUBSCRIBED = "SUBSCRIBED"
    PAUSED = "PAUSED"
    UNSUBSCRIBED = "UNSUBSCRIBED"


class ConsentAction(str, Enum):
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    UNSUBSCRIBE = "UNSUBSCRIBE"


class CampaignState(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"


class SendOutcome(str, Enum):
    SENT = "SENT"
    SUPPRESSED_CONSENT = "SUPPRESSED_CONSENT"
    SUPPRESSED_FREQUENCY = "SUPPRESSED_FREQUENCY"


class ReviewPlatform(str, Enum):
    GLASSDOOR = "GLASSDOOR"
    INDEED = "INDEED"
    COMPARABLY = "COMPARABLY"


class ReviewState(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    DRAFTING = "DRAFTING"
    LEGAL_REVIEW = "LEGAL_REVIEW"
    RESPONSE_PUBLISHED = "RESPONSE_PUBLISHED"
    CLOSED_NO_RESPONSE = "CLOSED_NO_RESPONSE"


class SlaStatus(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    BREACHED = "BREACHED"


class LegalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class PresenceState(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LedgerBucket(str, Enum):
    FAMILY_DEDICATED = "FAMILY_DEDICATED"
    POOL_JOB_BOARD = "POOL_JOB_BOARD"
    POOL_SOCIAL = "POOL_SOCIAL"
    POOL_PROGRAMMATIC = "POOL_PROGRAMMATIC"
    FLEX_RESERVE = "FLEX_RESERVE"


class LedgerEntryType(str, Enum):
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"


class LedgerSourceType(str, Enum):
    MEDIA_FLIGHT = "MEDIA_FLIGHT"
    EVENT_PRESENCE = "EVENT_PRESENCE"


class LedgerReason(str, Enum):
    FLIGHT_RESERVATION = "FLIGHT_RESERVATION"
    FLIGHT_CANCELLED = "FLIGHT_CANCELLED"
    FLIGHT_COMPLETED = "FLIGHT_COMPLETED"
    FLIGHT_PACING_THROTTLE = "FLIGHT_PACING_THROTTLE"
    FLIGHT_COMPLIANCE_SUSPENSION = "FLIGHT_COMPLIANCE_SUSPENSION"
    EVENT_RESERVATION = "EVENT_RESERVATION"
    EVENT_CANCELLED = "EVENT_CANCELLED"


# --------------------------------------------------------------- entity shapes

class Program(TypedDict):
    id: str
    name: str
    fiscal_year: int
    pool_job_board_cents: int
    pool_social_cents: int
    pool_programmatic_cents: int
    flex_reserve_cents: int
    send_quota_total: int
    attribution_model: str
    committed_budget_cents: int
    available_budget_cents: int
    send_quota_used: int
    brand_health_score: float
    last_attribution_recompute_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JobFamily(TypedDict):
    id: str
    program_id: str
    name: str
    code: str
    cpqa_target_cents: int
    priority_rank: int
    dedicated_budget_cents: int
    reserved_cents: int
    dedicated_available_cents: int
    created_at: str
    updated_at: str
    version: int


class Channel(TypedDict):
    id: str
    program_id: str
    name: str
    channel_type: str
    daily_capacity_cents: int
    min_flight_days: int
    spent_cents: int
    credited_qualified_bp: int
    active_flight_count: int
    pacing_status: str
    idle_since: Optional[str]
    blended_target_cents: Optional[int]
    cpqa_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CandidatePersona(TypedDict):
    id: str
    job_family_id: str
    name: str
    mix_method: str
    research_window_days: int
    state: str
    channel_mix: List[Dict[str, Any]]
    mix_confidence_pct: int
    signal_count: int
    revision_count: int
    drafted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    last_review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable event row — carries only id and created_at beyond its own fields.
class ChannelPreferenceSignal(TypedDict):
    id: str
    persona_id: str
    channel_id: str
    preference_score: int
    sample_size: int
    engagement_events: int
    collected_at: str
    created_at: str


class JobPosting(TypedDict):
    id: str
    job_family_id: str
    title: str
    title_word_count: int
    responsibility_count: int
    benefit_count: int
    pay_range_min_cents: Optional[int]
    pay_range_max_cents: Optional[int]
    eeo_statement_included: bool
    superlative_claim_included: bool
    substantiation_url: Optional[str]
    content_status: str
    compliance_status: str
    optimization_score: int
    apply_start_count: int
    submitted_count: int
    qualified_count: int
    conversion_rate_bp: Optional[int]
    optimized_by_user_id: Optional[str]
    cleared_by_user_id: Optional[str]
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MediaFlight(TypedDict):
    id: str
    channel_id: str
    job_family_id: str
    job_posting_id: str
    start_date: str
    end_date: str
    daily_cap_cents: int
    flight_days: int
    base_gross_cents: int
    cost_tier: str
    volume_discount_cents: int
    platform_fee_cents: int
    total_cost_cents: int
    reserved_cents: int
    spent_cents: int
    qualified_credit_bp: int
    state: str
    release_reason: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    job_posting_id: str
    candidate_email: str
    status: str
    submitted_at: Optional[str]
    screened_at: Optional[str]
    decided_at: Optional[str]
    attributed_credit_bp_total: int
    eligible_touch_count: int
    attribution_model_applied: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable event row — no updated_at, no version.
class Touchpoint(TypedDict):
    id: str
    application_id: str
    channel_id: str
    media_flight_id: Optional[str]
    touch_type: str
    occurred_at: str
    media_cost_cents: int
    credit_bp: int
    created_at: str


class TalentCommunityMember(TypedDict):
    id: str
    program_id: str
    interest_job_family_id: Optional[str]
    email: str
    frequency_cap_per_30d: int
    consent_status: str
    consent_token: str
    sent_count_total: int
    last_sent_at: Optional[str]
    consent_confirmed_at: Optional[str]
    consent_changed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NurtureCampaign(TypedDict):
    id: str
    program_id: str
    job_family_id: Optional[str]
    name: str
    max_sends: int
    state: str
    scheduled_for: Optional[str]
    dispatched_at: Optional[str]
    audience_size: int
    sent_count: int
    suppressed_consent_count: int
    suppressed_frequency_count: int
    created_at: str
    updated_at: str
    version: int


# Immutable event row — no updated_at, no version.
class NurtureSend(TypedDict):
    id: str
    campaign_id: str
    member_id: str
    outcome: str
    sequence_no: int
    evaluated_at: str
    sent_at: Optional[str]
    window_send_count_at_eval: int
    created_at: str


class EmployerReview(TypedDict):
    id: str
    program_id: str
    platform: str
    external_ref: str
    rating: int
    posted_at: str
    response_due_at: str
    state: str
    sla_status: str
    rejection_count: int
    response_body: Optional[str]
    drafted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EventPresence(TypedDict):
    id: str
    program_id: str
    job_family_id: str
    venue_code: str
    start_at: str
    end_at: str
    booth_cost_cents: int
    state: str
    reserved_cents: int
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable event row — no updated_at, no version.
class BudgetLedgerEntry(TypedDict):
    id: str
    program_id: str
    job_family_id: str
    bucket: str
    entry_type: str
    delta_cents: int
    source_type: str
    source_id: str
    sequence_no: int
    reason: str
    created_at: str


#: The four entity kinds that are written once and never edited.
IMMUTABLE_EVENT_ENTITIES = [
    "ChannelPreferenceSignal",
    "Touchpoint",
    "NurtureSend",
    "BudgetLedgerEntry",
]
