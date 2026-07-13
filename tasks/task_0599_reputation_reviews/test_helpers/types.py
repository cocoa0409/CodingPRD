"""Domain types for the Online Reputation Management API.

Entity TypedDicts, status enums and the role enum, derived from the PRD.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BUSINESS_OWNER = "BusinessOwner"
    LOCATION_MANAGER = "LocationManager"
    RESPONSE_AGENT = "ResponseAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ANONYMOUS = "Anonymous"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class PlanTier(str, Enum):
    BASIC = "BASIC"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class Posture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class Site(str, Enum):
    GOOGLE = "GOOGLE"
    YELP = "YELP"
    FACEBOOK = "FACEBOOK"


class SyncState(str, Enum):
    PENDING_SYNC = "PENDING_SYNC"
    CONNECTED = "CONNECTED"
    SYNC_FAILED = "SYNC_FAILED"
    DISCONNECTED = "DISCONNECTED"


class SyncOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class Channel(str, Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class RequestStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    CLICKED = "CLICKED"
    CONVERTED = "CONVERTED"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"


class DeliveryEvent(str, Enum):
    DELIVERED = "DELIVERED"
    CLICKED = "CLICKED"
    FAILED = "FAILED"


class Sentiment(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class ModerationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FLAGGED = "FLAGGED"


class ResponseState(str, Enum):
    """The review's reply dimension (PRD §3.3)."""

    NONE = "NONE"
    DRAFTED = "DRAFTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    RESPONDED = "RESPONDED"


class ReviewResponseState(str, Enum):
    """The ReviewResponse's own approval lifecycle (PRD §3.4)."""

    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"


class EscalationState(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class EscalationReason(str, Enum):
    NEGATIVE_SENTIMENT = "NEGATIVE_SENTIMENT"


class SurveyStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"


class NpsCategory(str, Enum):
    PROMOTER = "PROMOTER"
    PASSIVE = "PASSIVE"
    DETRACTOR = "DETRACTOR"


class WidgetStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class AlertType(str, Enum):
    NEGATIVE_REVIEW = "NEGATIVE_REVIEW"
    POSTURE_CHANGED = "POSTURE_CHANGED"
    LISTING_SYNC_FAILED = "LISTING_SYNC_FAILED"
    NPS_DETRACTOR = "NPS_DETRACTOR"
    SEND_CAP_REACHED = "SEND_CAP_REACHED"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# --------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD §2.4)
# --------------------------------------------------------------------------
class Business(TypedDict):
    id: str
    name: str
    plan_tier: str
    default_frequency_cap_days: int
    location_count: int
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    business_id: str
    name: str
    nap_name: str
    nap_address: str
    nap_phone: str
    posture: str
    review_count: int
    avg_rating: float
    responded_review_count: int
    sentiment_positive_count: int
    sentiment_neutral_count: int
    sentiment_negative_count: int
    reputation_score_provisional: float
    reputation_score_certified: float
    certified_at: Optional[str]
    listing_health_score: float
    nps_score: float
    open_escalation_count: int
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    location_id: str
    site: str
    external_listing_id: str
    listed_nap_name: str
    listed_nap_address: str
    listed_nap_phone: str
    sync_state: str
    sync_failure_count: int
    last_synced_at: Optional[str]
    nap_match_count: int
    created_at: str
    updated_at: str
    version: int


class Contact(TypedDict):
    id: str
    business_id: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    sms_consent: bool
    email_consent: bool
    opted_out: bool
    last_requested_at: Optional[str]
    request_count: int
    created_at: str
    updated_at: str
    version: int


class ResponseTemplate(TypedDict):
    id: str
    business_id: str
    name: str
    body: str
    min_rating: int
    max_rating: int
    requires_approval: bool
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    location_id: str
    name: str
    channel: str
    message_body: str
    send_window_start: str
    send_window_end: str
    daily_send_cap: int
    credits_allocated: int
    credits_reserved: int
    credits_consumed: int
    credits_released: int
    status: str
    activated_at: Optional[str]
    sent_count: int
    billing_cost: float
    created_at: str
    updated_at: str
    version: int


class ReviewRequest(TypedDict):
    id: str
    campaign_id: str
    contact_id: str
    channel: str
    status: str
    send_index: Optional[int]
    unit_cost: Optional[float]
    sent_at: Optional[str]
    converted_review_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    id: str
    location_id: str
    review_request_id: Optional[str]
    site: str
    external_review_id: str
    author_name: str
    text: str
    rating: int
    posted_at: str
    sentiment: str
    moderation_state: str
    response_state: str
    created_at: str
    updated_at: str
    version: int


class ReviewResponse(TypedDict):
    id: str
    review_id: str
    template_id: Optional[str]
    body: str
    state: str
    drafted_by_user_id: str
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    revision_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Escalation(TypedDict):
    id: str
    review_id: str
    reason: str
    state: str
    acknowledged_by_user_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyResponse(TypedDict):
    id: str
    location_id: str
    contact_id: str
    status: str
    nps_score: Optional[int]
    nps_category: Optional[str]
    comment: Optional[str]
    submitted_at: Optional[str]
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Widget(TypedDict):
    id: str
    location_id: str
    min_rating: int
    max_reviews: int
    status: str
    embed_token: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only snapshots: id + created_at ONLY (PRD §2.4)
# --------------------------------------------------------------------------
class Competitor(TypedDict):
    id: str
    location_id: str
    name: str
    site: str
    avg_rating: float
    review_count: int
    created_at: str


class Alert(TypedDict):
    id: str
    location_id: str
    alert_type: str
    severity: str
    message: str
    payload_ref_id: str
    created_at: str
