"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    LISTING_AGENT = "ListingAgent"
    MARKETING_COORDINATOR = "MarketingCoordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    MARKETING_DIRECTOR = "MarketingDirector"
    PORTAL_WEBHOOK = "PortalWebhook"


class PropertyType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    CONDO = "CONDO"
    TOWNHOUSE = "TOWNHOUSE"
    MULTI_FAMILY = "MULTI_FAMILY"
    LAND = "LAND"


class LifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"
    ACTIVE = "ACTIVE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class SyndicationPosture(str, Enum):
    NOT_SYNDICATED = "NOT_SYNDICATED"
    SYNDICATING = "SYNDICATING"
    SYNDICATED = "SYNDICATED"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"


class MediaKind(str, Enum):
    PHOTO = "PHOTO"
    VIDEO = "VIDEO"
    FLOOR_PLAN = "FLOOR_PLAN"


class MediaAssetStatus(str, Enum):
    UPLOADED = "UPLOADED"
    READY = "READY"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PortalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SubscriptionStatus(str, Enum):
    SUBSCRIBED = "SUBSCRIBED"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class JobType(str, Enum):
    FULL_SYNC = "FULL_SYNC"
    PRICE_UPDATE = "PRICE_UPDATE"
    REMARKS_UPDATE = "REMARKS_UPDATE"
    STATUS_UPDATE = "STATUS_UPDATE"
    MEDIA_UPDATE = "MEDIA_UPDATE"
    TERMINAL_SYNC = "TERMINAL_SYNC"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    ACKED = "ACKED"
    FAILED = "FAILED"
    RETRY_QUEUED = "RETRY_QUEUED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    DEAD_LETTER = "DEAD_LETTER"


class EventType(str, Enum):
    PRICE_CHANGE = "PRICE_CHANGE"
    REMARKS_UPDATE = "REMARKS_UPDATE"
    STATUS_CHANGE = "STATUS_CHANGE"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class FeedbackStatus(str, Enum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


# Primary resources carry id + created_at + updated_at + version (PRD §2.5).

class Agent(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    agent_id: str
    address_line1: str
    city: str
    state_code: str
    postal_code: str
    property_type: str
    list_price_cents: int
    listing_expires_on: str
    bedrooms: Optional[int]
    bathrooms: Optional[float]
    square_feet: Optional[int]
    marketing_remarks: Optional[str]
    mls_number: Optional[str]
    lifecycle_status: str
    syndication_posture: str
    relist_count: int
    terminal_entered_at: Optional[str]
    terminal_price_cents: Optional[int]
    feedback_score_raw: Optional[float]
    feedback_score_weighted: Optional[float]
    audited_breach_count: int
    provisional_breach_count: int
    created_at: str
    updated_at: str
    version: int


class MediaAsset(TypedDict, total=False):
    id: str
    listing_id: str
    kind: str
    file_url: str
    file_bytes: int
    width_px: Optional[int]
    height_px: Optional[int]
    is_primary: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReview(TypedDict, total=False):
    id: str
    listing_id: str
    status: str
    remarks_snapshot: Optional[str]
    flagged_terms: Optional[List[str]]
    notes: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PortalAccount(TypedDict, total=False):
    id: str
    portal_name: str
    status: str
    sla_seconds: int
    discount_pct: float
    rounding_increment_cents: int
    created_at: str
    updated_at: str
    version: int


# BlackoutWindow is append-only: only id + created_at (PRD §2.5); no updated_at/version.

class BlackoutWindow(TypedDict, total=False):
    id: str
    portal_account_id: str
    starts_at: str
    ends_at: str
    reason: Optional[str]
    created_at: str


class FeedSubscription(TypedDict, total=False):
    id: str
    listing_id: str
    portal_account_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SyndicationJob(TypedDict, total=False):
    id: str
    feed_subscription_id: str
    listing_id: str
    job_type: str
    status: str
    attempt_count: int
    scheduled_at: str
    dispatched_at: Optional[str]
    completed_at: Optional[str]
    propagation_delay_seconds: Optional[int]
    payload_display_price_cents: Optional[int]
    failure_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ListingEvent is append-only: only id + created_at (PRD §2.5); no updated_at/version.

class ListingEvent(TypedDict, total=False):
    id: str
    listing_id: str
    seq: int
    event_type: str
    old_price_cents: Optional[int]
    new_price_cents: Optional[int]
    old_remarks: Optional[str]
    new_remarks: Optional[str]
    from_lifecycle: Optional[str]
    to_lifecycle: Optional[str]
    created_at: str


class ShowingWindow(TypedDict, total=False):
    id: str
    listing_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShowingFeedback(TypedDict, total=False):
    id: str
    showing_window_id: str
    listing_id: str
    rating: int
    comment: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RelistRequest(TypedDict, total=False):
    id: str
    listing_id: str
    relist_count_before: int
    price_reduction_pct: float
    new_list_price_cents: int
    fee_cents: int
    created_at: str
    updated_at: str
    version: int
