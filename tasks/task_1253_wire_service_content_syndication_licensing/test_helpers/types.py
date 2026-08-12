"""Domain types: entity TypedDicts, status enums, role enum (wire service PRD)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_OPS = "SalesOps"
    EDITOR = "Editor"
    LEGAL = "Legal"
    AUDITOR = "Auditor"
    BILLING = "Billing"
    SUBSCRIBER_REP = "SubscriberRep"


class MediaRights(str, Enum):
    TEXT_ONLY = "TEXT_ONLY"
    TEXT_AND_PHOTO = "TEXT_AND_PHOTO"
    TEXT_PHOTO_VIDEO = "TEXT_PHOTO_VIDEO"


class FeedTopic(str, Enum):
    NATIONAL = "NATIONAL"
    WORLD = "WORLD"
    BUSINESS = "BUSINESS"
    SPORTS = "SPORTS"
    FEATURES = "FEATURES"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class FeedStatus(str, Enum):
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"


class SubscriberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class EntitlementStatus(str, Enum):
    LIVE = "LIVE"
    REVOKED = "REVOKED"


class ArticleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"
    TAKEN_DOWN = "TAKEN_DOWN"


class EmbargoStatus(str, Enum):
    CLEAR = "CLEAR"
    EMBARGOED = "EMBARGOED"
    EMBARGO_LIFTED = "EMBARGO_LIFTED"


class AssetKind(str, Enum):
    PHOTO = "PHOTO"
    VIDEO = "VIDEO"


class RightsScope(str, Enum):
    WIRE = "WIRE"
    EDITORIAL_ONLY = "EDITORIAL_ONLY"
    MEMBER_ONLY = "MEMBER_ONLY"


class AssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TAKEN_DOWN = "TAKEN_DOWN"


class PublicationStatus(str, Enum):
    RECORDED = "RECORDED"
    AUDIT_FLAGGED = "AUDIT_FLAGGED"
    DISMISSED = "DISMISSED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# --- Entity TypedDicts (all carry id + created_at + updated_at + version,
# --- except ClockCheckpoint which carries only id + created_at) ---


class ContentPackage(TypedDict, total=False):
    id: str
    code: str
    display_name: str
    media_rights: str
    base_monthly_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriberTier(TypedDict, total=False):
    id: str
    code: str
    min_audience: int
    max_audience: Optional[int]
    circulation_multiplier_basis_points: int
    monthly_republish_quota: int
    overage_per_article_cents: int
    member_discount_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Feed(TypedDict, total=False):
    id: str
    code: str
    topic: str
    embargo_window_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict, total=False):
    id: str
    legal_name: str
    billing_email: str
    declared_audience: int
    is_member: bool
    member_credit_balance_cents: int
    status: str
    termination_notice_at: Optional[str]
    termination_effective_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    subscriber_id: str
    package_id: str
    tier_id: str
    monthly_price_cents: int
    start_at: str
    renewal_due_at: str
    renewal_notice_sent_at: Optional[str]
    months_used_current_period: int
    republish_count_current_month: int
    current_month_bucket: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Entitlement(TypedDict, total=False):
    id: str
    subscription_id: str
    feed_id: str
    granted_at: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Article(TypedDict, total=False):
    id: str
    feed_id: str
    headline: str
    body_word_count: int
    slug: str
    published_at: Optional[str]
    embargo_until: Optional[str]
    embargo_status: str
    contributing_member_subscriber_id: Optional[str]
    member_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    article_id: str
    kind: str
    rights_scope: str
    file_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Publication(TypedDict, total=False):
    id: str
    subscriber_id: str
    subscription_id: str
    article_id: str
    republished_at: str
    billed_amount_cents: int
    within_quota: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    subscriber_id: str
    subscription_id: str
    billing_month: str
    base_fee_cents: int
    overage_cents: int
    member_credit_applied_cents: int
    total_due_cents: int
    provisional_total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClockCheckpoint(TypedDict, total=False):
    # Append-only clock resource: carries ONLY id + created_at (+ current_utc).
    # No updated_at, no version.
    id: str
    current_utc: str
    created_at: str
