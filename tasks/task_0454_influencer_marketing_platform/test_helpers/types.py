"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    BRAND = "Brand"
    CREATOR = "Creator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status / enum value sets ---
class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ContentSubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class TaxForm1099Status(str, Enum):
    GENERATED = "GENERATED"
    FILED = "FILED"
    VOIDED = "VOIDED"


class BrandSafetyFlagStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class AttributionAssetStatus(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class DiscoveryStatus(str, Enum):
    NEW = "NEW"
    DISCOVERABLE = "DISCOVERABLE"
    SUPPRESSED = "SUPPRESSED"


class BrandSafetyStatus(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    BLOCKED = "BLOCKED"


class PrimaryPlatform(str, Enum):
    INSTAGRAM = "INSTAGRAM"
    TIKTOK = "TIKTOK"
    YOUTUBE = "YOUTUBE"


class PayoutMethod(str, Enum):
    ACH = "ACH"
    PAYPAL = "PAYPAL"


class ContentType(str, Enum):
    FEED_POST = "FEED_POST"
    STORY = "STORY"
    REEL = "REEL"
    VIDEO = "VIDEO"


class AssetType(str, Enum):
    TRACKING_LINK = "TRACKING_LINK"
    PROMO_CODE = "PROMO_CODE"


class EventType(str, Enum):
    IMPRESSION = "IMPRESSION"
    ENGAGEMENT = "ENGAGEMENT"
    SALE = "SALE"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReasonCode(str, Enum):
    HATE_SPEECH = "HATE_SPEECH"
    FRAUD_SIGNAL = "FRAUD_SIGNAL"
    NSFW = "NSFW"
    MISINFORMATION = "MISINFORMATION"
    OTHER = "OTHER"


class Initiator(str, Enum):
    BRAND = "BRAND"
    CREATOR = "CREATOR"


# --- Versioned entities (carry id + created_at + updated_at + version) ---
class Brand(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    budget_cents: int
    committed_cents: int
    available_budget_cents: int
    created_at: str
    updated_at: str
    version: int


class Creator(TypedDict):
    id: str
    handle: str
    primary_platform: str
    payout_method: str
    tax_id_on_file: bool
    discovery_status: str
    brand_safety_status: str
    ytd_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    brand_id: str
    title: str
    campaign_budget_cents: int
    requires_ftc_disclosure: bool
    starts_at: str
    ends_at: str
    status: str
    committed_cents: int
    actual_spend_cents: int
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    campaign_id: str
    content_type: str
    quantity: int
    due_at: str
    base_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    campaign_id: str
    creator_id: str
    initiated_by: str
    current_amount_cents: int
    last_actor: str
    round_count: int
    exclusivity_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    offer_id: str
    campaign_id: str
    creator_id: str
    contracted_rate_cents: int
    pinned_offer_version: int
    exclusivity_start: str
    exclusivity_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContentSubmission(TypedDict):
    id: str
    deliverable_id: str
    contract_id: str
    media_url: str
    caption: str
    has_ftc_disclosure: bool
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AttributionAsset(TypedDict):
    id: str
    contract_id: str
    asset_type: str
    code_or_slug: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    contract_id: str
    gross_amount_cents: int
    platform_fee_cents: int
    tax_withholding_cents: int
    net_amount_cents: int
    expected_contract_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxForm1099(TypedDict):
    id: str
    creator_id: str
    tax_year: int
    total_reported_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BrandSafetyFlag(TypedDict):
    id: str
    creator_id: str
    severity: str
    reason_code: str
    note: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only telemetry entities (carry ONLY id + created_at) ---
class AudienceSnapshot(TypedDict):
    id: str
    creator_id: str
    follower_count: int
    avg_engagement_rate: float
    estimated_reach: int
    fake_follower_pct: float
    fraud_score: float
    captured_at: str
    created_at: str


class ConversionEvent(TypedDict):
    id: str
    attribution_asset_id: str
    event_type: str
    count: int
    revenue_cents: int
    occurred_at: str
    created_at: str
