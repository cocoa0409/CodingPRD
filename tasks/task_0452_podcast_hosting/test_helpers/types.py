"""Domain types: entity TypedDicts, status enums, role enum (Podcast Hosting & Monetization API)."""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Role enum ──────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PUBLISHER = "Publisher"
    ADVERTISER = "Advertiser"
    LISTENER = "Listener"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ───────────────────────────────────────────────────────────
class ShowStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class EpisodePublishStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"
    DELETED = "DELETED"


class EpisodeMediaStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class MediaAssetStatus(str, Enum):
    UPLOADED = "UPLOADED"
    TRANSCODING = "TRANSCODING"
    READY = "READY"
    FAILED = "FAILED"


class FeedStatus(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class FeedVisibility(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class DistributionStatus(str, Enum):
    PENDING = "PENDING"
    LIVE = "LIVE"
    REJECTED = "REJECTED"
    REMOVED = "REMOVED"


class DistributionChannel(str, Enum):
    APPLE = "APPLE"
    SPOTIFY = "SPOTIFY"


class AdCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXHAUSTED = "EXHAUSTED"
    COMPLETED = "COMPLETED"


class AdPlacementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    INSERTED = "INSERTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class AdPlacementPosition(str, Enum):
    PRE_ROLL = "PRE_ROLL"
    MID_ROLL = "MID_ROLL"
    POST_ROLL = "POST_ROLL"


class PayoutStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    VOID = "VOID"


class IabCategory(str, Enum):
    TECH = "TECH"
    NEWS = "NEWS"
    COMEDY = "COMEDY"
    BUSINESS = "BUSINESS"
    EDUCATION = "EDUCATION"
    TRUE_CRIME = "TRUE_CRIME"


# ─── Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ───
class Publisher(TypedDict):
    id: str
    name: str
    payout_email: str
    revenue_share_pct: float
    created_at: str
    updated_at: str
    version: int


class Advertiser(TypedDict):
    id: str
    name: str
    billing_email: str
    created_at: str
    updated_at: str
    version: int


class Listener(TypedDict):
    id: str
    email: str
    display_name: str
    created_at: str
    updated_at: str
    version: int


class Show(TypedDict):
    id: str
    publisher_id: str
    title: str
    category: str
    status: str
    monetization_enabled: bool
    episode_count: int
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict):
    id: str
    show_id: str
    title: str
    duration_ms: int
    total_ad_slots: int
    offered_positions: List[str]
    media_status: str
    publish_status: str
    scheduled_publish_at: Optional[str]
    filled_slots: int
    available_slots: int
    fill_rate: float
    created_at: str
    updated_at: str
    version: int


class MediaAsset(TypedDict):
    id: str
    episode_id: str
    source_filename: str
    source_duration_ms: int
    status: str
    transcode_attempts: int
    output_duration_ms: int
    created_at: str
    updated_at: str
    version: int


class Feed(TypedDict):
    id: str
    show_id: str
    visibility: str
    status: str
    token_required: bool
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    listener_id: str
    show_id: str
    price_cents: int
    status: str
    period_start: str
    period_end: str
    access_token: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict):
    id: str
    show_id: str
    channel: str
    status: str
    external_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdCampaign(TypedDict):
    id: str
    advertiser_id: str
    name: str
    budget_cents: int
    bid_cpm_cents: int
    targeting_category: str
    premium_targeting: bool
    flight_start: str
    flight_end: str
    status: str
    reserved_budget_cents: int
    spent_budget_cents: int
    available_budget_cents: int
    created_at: str
    updated_at: str
    version: int


class AdPlacement(TypedDict):
    id: str
    campaign_id: str
    episode_id: str
    position: str
    offset_ms: int
    ad_duration_ms: int
    forecast_impressions: int
    delivered_impressions: int
    estimated_cost_cents: int
    fill_tier_multiplier: float
    final_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutStatement(TypedDict):
    id: str
    publisher_id: str
    period_start: str
    period_end: str
    status: str
    gross_revenue_cents: int
    platform_fee_cents: int
    net_payable_cents: int
    settled_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false — ONLY id + created_at) ─────────
class DownloadEvent(TypedDict):
    id: str
    episode_id: str
    placement_id: Optional[str]
    client_ip_hash: str
    user_agent: str
    bytes_served: int
    counted: bool
    event_at: str
    created_at: str
