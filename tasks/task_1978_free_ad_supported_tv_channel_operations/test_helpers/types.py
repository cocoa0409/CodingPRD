"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CHANNEL_PROGRAMMER = "ChannelProgrammer"
    CONTENT_LICENSING = "ContentLicensing"
    AD_OPS = "AdOps"
    AD_QUALITY_REVIEWER = "AdQualityReviewer"
    FINANCE_ANALYST = "FinanceAnalyst"
    FINANCE_CONTROLLER = "FinanceController"
    DISTRIBUTOR_PARTNER = "DistributorPartner"


class ChannelStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    OFFLINE = "OFFLINE"
    ARCHIVED = "ARCHIVED"


class ChannelPosture(str, Enum):
    ACTIVE = "ACTIVE"
    GUARDED = "GUARDED"
    FROZEN = "FROZEN"


class ContentStatus(str, Enum):
    INGESTING = "INGESTING"
    AVAILABLE = "AVAILABLE"
    PULLED = "PULLED"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"
    ARCHIVED = "ARCHIVED"


class GrantStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"
    REVOKED = "REVOKED"


class LoopStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    LOCKED = "LOCKED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class BreakStatus(str, Enum):
    MARKED = "MARKED"
    DECIDED = "DECIDED"
    AIRED = "AIRED"
    RECONCILED = "RECONCILED"


class FillType(str, Enum):
    DIRECT = "DIRECT"
    HOUSE = "HOUSE"


class DecisionStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    COMMITTED = "COMMITTED"
    RECONCILED = "RECONCILED"
    VOIDED = "VOIDED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXHAUSTED = "EXHAUSTED"
    COMPLETED = "COMPLETED"


class CreativeStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class HouseAdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class PlatformStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class AgreementStatus(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class CalculationVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ContentType(str, Enum):
    MOVIE = "MOVIE"
    EPISODE = "EPISODE"
    SHORT = "SHORT"


class Rating(str, Enum):
    G = "G"
    PG = "PG"
    PG13 = "PG13"
    R = "R"
    TVMA = "TVMA"


class EventType(str, Enum):
    SESSION_START = "SESSION_START"
    SESSION_END = "SESSION_END"
    CONTENT_WATCH = "CONTENT_WATCH"
    AD_IMPRESSION = "AD_IMPRESSION"
    AD_COMPLETE = "AD_COMPLETE"


# --- Entity records (PRD §2.5 common fields: id, created_at, updated_at, version) ---

class Channel(TypedDict, total=False):
    id: str
    name: str
    genre: str
    timezone: str
    loop_duration_seconds: int
    refresh_cadence_days: int
    ad_separation_window_seconds: int
    avg_slot_impressions: int
    channel_status: str
    channel_posture: str
    ops_run_index: int
    last_published_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContentAsset(TypedDict, total=False):
    id: str
    title: str
    content_type: str
    runtime_seconds: int
    rating: str
    genre: str
    content_status: str
    created_at: str
    updated_at: str
    version: int


class RightsGrant(TypedDict, total=False):
    id: str
    channel_id: str
    content_id: str
    window_start_utc: str
    window_end_utc: str
    max_plays: int
    plays_used: int
    grant_status: str
    created_at: str
    updated_at: str
    version: int


class PlaylistLoop(TypedDict, total=False):
    id: str
    channel_id: str
    broadcast_date: str
    loop_status: str
    used_seconds: int
    validated_at: Optional[str]
    published_at: Optional[str]
    supersedes_loop_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlaylistEntry(TypedDict, total=False):
    id: str
    loop_id: str
    content_id: str
    sequence_index: int
    start_offset_seconds: int
    end_offset_seconds: int
    created_at: str
    updated_at: str
    version: int


class AdBreak(TypedDict, total=False):
    id: str
    loop_id: str
    duration_seconds: int
    after_entry_index: int
    sequence_index: int
    start_offset_seconds: int
    break_status: str
    slots: int
    direct_seconds: int
    house_seconds: int
    slate_seconds: int
    created_at: str
    updated_at: str
    version: int


class FillDecision(TypedDict, total=False):
    id: str
    break_id: str
    slot_index: int
    slots_spanned: int
    fill_type: str
    creative_id: Optional[str]
    campaign_id: Optional[str]
    house_ad_id: Optional[str]
    expected_impressions: int
    committed_cost_cents: int
    actual_impressions: Optional[int]
    reconciled_cost_cents: Optional[int]
    decision_status: str
    created_at: str
    updated_at: str
    version: int


class AdCampaign(TypedDict, total=False):
    id: str
    advertiser_name: str
    iab_category: str
    total_budget_cents: int
    daily_budget_cents: int
    cpm_cents: int
    flight_start_date: str
    flight_end_date: str
    priority: int
    spent_cents: int
    campaign_status: str
    created_at: str
    updated_at: str
    version: int


class AdCreative(TypedDict, total=False):
    id: str
    campaign_id: str
    brand: str
    iab_category: str
    duration_seconds: int
    creative_status: str
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HouseAd(TypedDict, total=False):
    id: str
    name: str
    channel_id: Optional[str]
    duration_seconds: int
    priority_weight: int
    daily_impression_cap: int
    house_ad_status: str
    created_at: str
    updated_at: str
    version: int


class DistributorPlatform(TypedDict, total=False):
    id: str
    name: str
    reporting_tier: str
    platform_status: str
    created_at: str
    updated_at: str
    version: int


class DistributionAgreement(TypedDict, total=False):
    id: str
    channel_id: str
    platform_id: str
    rev_share_bps_below: int
    rev_share_bps_above: int
    tier_threshold_cents: int
    minimum_guarantee_cents: int
    effective_start_date: str
    effective_end_date: str
    agreement_status: str
    locked_rev_share_bps_below: Optional[int]
    locked_rev_share_bps_above: Optional[int]
    locked_tier_threshold_cents: Optional[int]
    locked_minimum_guarantee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RevenueReport(TypedDict, total=False):
    id: str
    channel_id: str
    platform_id: str
    agreement_id: str
    period_month: str
    report_status: str
    calculation_variant: Optional[str]
    gross_revenue_cents: Optional[int]
    platform_share_cents: Optional[int]
    net_revenue_cents: Optional[int]
    dispute_round: int
    generated_by_user_id: str
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.5): carries ONLY id + created_at — no updated_at, no version.
class ViewershipEvent(TypedDict, total=False):
    id: str
    channel_id: str
    platform_id: str
    event_type: str
    break_id: Optional[str]
    decision_id: Optional[str]
    content_id: Optional[str]
    viewer_session_id: str
    occurred_at_utc: str
    watch_seconds: Optional[int]
    quantity: int
    created_at: str


class ChannelDaySnapshot(TypedDict, total=False):
    id: str
    channel_id: str
    snapshot_date: str
    watch_seconds: int
    peak_concurrent_viewers: int
    ad_impressions: int
    direct_sold_impressions: int
    capacity_seconds: int
    direct_seconds: int
    house_seconds: int
    direct_fill_rate: float
    effective_fill_rate: float
    direct_revenue_cents: int
    ecpm_cents: int
    performance_score: int
    computed_at: str
    created_at: str
    updated_at: str
    version: int
