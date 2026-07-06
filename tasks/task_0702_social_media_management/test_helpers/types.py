"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as the PRD specifies.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    CONTENT_CREATOR = "ContentCreator"
    APPROVER = "Approver"
    COMMUNITY_AGENT = "CommunityAgent"
    FINANCE_CONTROLLER = "FinanceController"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ClientStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CHURNED = "CHURNED"


class RetainerPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ChannelStatus(str, Enum):
    PENDING = "PENDING"
    CONNECTED = "CONNECTED"
    LIVE = "LIVE"
    DISCONNECTED = "DISCONNECTED"


class ContentItemStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ContentTargetPublishState(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ScheduleSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    FIRED = "FIRED"
    RELEASED = "RELEASED"


class BoostCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ConversationStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class InfluencerCollabStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class UGCAssetStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RIGHTS_CLEARED = "RIGHTS_CLEARED"
    REJECTED = "REJECTED"


class LedgerEntryType(str, Enum):
    RETAINER_CHARGE = "RETAINER_CHARGE"
    BOOST_RESERVE = "BOOST_RESERVE"
    BOOST_RELEASE = "BOOST_RELEASE"
    BOOST_SPEND = "BOOST_SPEND"


# ---------------------------------------------------------------------------
# Full resources (carry id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Client(TypedDict):
    id: str
    name: str
    account_manager_id: str
    status: str
    retainer_fee_cents: int
    boost_budget_limit_cents: int
    boost_reserved_cents: int
    boost_spent_cents: int
    boost_available_cents: int
    monthly_post_quota: int
    posts_published_this_cycle: int
    current_cycle_index: int
    open_conversation_count: int
    created_at: str
    updated_at: str
    version: int


class RetainerPackage(TypedDict):
    id: str
    client_id: str
    tier: str
    monthly_retainer_fee_cents: int
    monthly_boost_budget_cents: int
    monthly_post_quota: int
    included_channels: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Channel(TypedDict):
    id: str
    client_id: str
    platform: str
    handle: str
    status: str
    min_publish_gap_minutes: int
    created_at: str
    updated_at: str
    version: int


class ContentItem(TypedDict):
    id: str
    client_id: str
    author_id: str
    title: str
    body: str
    status: str
    revision_round: int
    published_cycle_index: Optional[int]
    scheduled_slot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContentTarget(TypedDict):
    id: str
    content_item_id: str
    channel_id: str
    publish_state: str
    created_at: str
    updated_at: str
    version: int


class ScheduleSlot(TypedDict):
    id: str
    channel_id: str
    content_item_id: str
    slot_start_utc: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BoostCampaign(TypedDict):
    id: str
    client_id: str
    content_item_id: str
    requested_budget_cents: int
    daily_cap_cents: int
    duration_days: int
    status: str
    reserved_budget_cents: int
    spent_budget_cents: int
    days_elapsed: int
    current_day_spent_cents: int
    created_at: str
    updated_at: str
    version: int


class Conversation(TypedDict):
    id: str
    channel_id: str
    kind: str
    external_author_handle: str
    status: str
    assigned_agent_id: Optional[str]
    message_count: int
    created_at: str
    updated_at: str
    version: int


class InfluencerCollab(TypedDict):
    id: str
    client_id: str
    influencer_handle: str
    offer_fee_cents: int
    deliverable_count: int
    status: str
    negotiation_round: int
    approved_asset_count: int
    created_at: str
    updated_at: str
    version: int


class UGCAsset(TypedDict):
    id: str
    collab_id: str
    asset_url: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lightweight write-once resources (carry ONLY id + created_at)
# ---------------------------------------------------------------------------
class EngagementMessage(TypedDict):
    id: str
    conversation_id: str
    direction: str
    body: str
    author_agent_id: Optional[str]
    created_at: str


class AnalyticsSnapshot(TypedDict):
    id: str
    client_id: str
    cycle_index: int
    posts_published: int
    boost_spent_cents: int
    engagement_rate_bps: float
    total_impressions: int
    total_engagements: int
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    client_id: str
    entry_type: str
    amount_cents: int
    boost_campaign_id: Optional[str]
    cycle_index: int
    created_at: str
