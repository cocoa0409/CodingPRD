"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    AD_OPS = "AdOps"
    ADVERTISER = "Advertiser"
    AGENCY = "Agency"
    SHOW_PRODUCER = "ShowProducer"
    FINANCE = "Finance"
    INGESTION = "Ingestion"


class ContentCategory(str, Enum):
    TECHNOLOGY = "TECHNOLOGY"
    BUSINESS = "BUSINESS"
    COMEDY = "COMEDY"
    NEWS = "NEWS"
    HEALTH = "HEALTH"
    SPORTS = "SPORTS"


class AdvertiserCategory(str, Enum):
    AUTOMOTIVE = "AUTOMOTIVE"
    CPG_FOOD = "CPG_FOOD"
    FINTECH = "FINTECH"
    GAMBLING = "GAMBLING"
    ALCOHOL = "ALCOHOL"
    HEALTH_PHARMA = "HEALTH_PHARMA"
    TECHNOLOGY = "TECHNOLOGY"


class BrandSafetyTier(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    SUSPENDED = "SUSPENDED"


class EpisodeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    MEASURED = "MEASURED"


class AdvertiserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class LineItemStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class AdCopyKind(str, Enum):
    HOST_READ_SCRIPT = "HOST_READ_SCRIPT"
    PRODUCED_AUDIO = "PRODUCED_AUDIO"


class AdCopyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    WITHDRAWN = "WITHDRAWN"


class AdFormat(str, Enum):
    HOST_READ = "HOST_READ"
    PRODUCED_SPOT = "PRODUCED_SPOT"


class Position(str, Enum):
    PRE_ROLL = "PRE_ROLL"
    MID_ROLL = "MID_ROLL"
    POST_ROLL = "POST_ROLL"


class BillingModel(str, Enum):
    ACTUAL_DELIVERY = "ACTUAL_DELIVERY"
    BOOKED_GROSS = "BOOKED_GROSS"


class UserAgentClass(str, Enum):
    HUMAN = "HUMAN"
    BOT = "BOT"
    UNKNOWN = "UNKNOWN"


class AttributionKind(str, Enum):
    PROMO_CODE = "PROMO_CODE"
    PIXEL = "PIXEL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class MakeGoodStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Entity bodies. Primary resources carry id + created_at + updated_at +
# version (PRD §2.5). Download / Impression / AttributionEvent are append-only
# and carry only id + created_at.
# ---------------------------------------------------------------------------


class Show(TypedDict, total=False):
    id: str
    title: str
    content_category: str
    avg_downloads_30d: int
    blocked_advertiser_categories: List[str]
    brand_safety_tier: str
    forecast_impressions: int
    reserved_impressions: int
    available_impressions: int
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict, total=False):
    id: str
    show_id: str
    title: str
    publish_at: str
    measurement_window_days: int
    slot_capacity: int
    status: str
    provisional_download_count: int
    measured_download_count: Optional[int]
    slots_in_use: int
    created_at: str
    updated_at: str
    version: int


class Agency(TypedDict, total=False):
    id: str
    name: str
    commission_bps: int
    created_at: str
    updated_at: str
    version: int


class Advertiser(TypedDict, total=False):
    id: str
    name: str
    category: str
    agency_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    advertiser_id: str
    name: str
    flight_start: str
    flight_end: str
    booked_impressions: int
    cpm_cents: int
    billing_model: str
    status: str
    delivered_impressions: int
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict, total=False):
    id: str
    campaign_id: str
    show_id: Optional[str]
    episode_id: Optional[str]
    ad_format: str
    position: str
    reserved_impressions: int
    priority: int
    ad_copy_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AdCopy(TypedDict, total=False):
    id: str
    campaign_id: str
    kind: str
    show_id: Optional[str]
    script_text: str
    revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Download(TypedDict, total=False):
    id: str
    episode_id: str
    listener_key: str
    occurred_at: str
    user_agent_class: str
    qualified_provisional: bool
    qualified_final: Optional[bool]
    created_at: str


class Impression(TypedDict, total=False):
    id: str
    download_id: str
    line_item_id: str
    campaign_id: str
    position: str
    served_at: str
    billable_provisional: bool
    billable_final: Optional[bool]
    created_at: str


class AttributionEvent(TypedDict, total=False):
    id: str
    campaign_id: str
    kind: str
    promo_code: Optional[str]
    occurred_at: str
    attributed: bool
    created_at: str


class InvoiceLine(TypedDict, total=False):
    line_item_id: str
    position: str
    billable_impressions: int
    line_cents: int


class Invoice(TypedDict, total=False):
    id: str
    campaign_id: str
    billing_model: str
    delivered_impressions_billed: int
    lines: List[InvoiceLine]
    gross_cents: int
    shortfall_impressions: int
    make_good_credit_cents: int
    agency_commission_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MakeGood(TypedDict, total=False):
    id: str
    campaign_id: str
    invoice_id: str
    granted_impressions: int
    baseline_delivered_impressions: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
