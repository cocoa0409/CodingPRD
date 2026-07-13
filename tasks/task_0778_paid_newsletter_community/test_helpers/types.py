"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this domain carries the full common field set
(id, created_at, updated_at, version) — none is append-only.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CREATOR = "Creator"
    MEMBER = "Member"
    MODERATOR = "Moderator"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


class PublicationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DeliverabilityStatus(str, Enum):
    HEALTHY = "HEALTHY"
    THROTTLED = "THROTTLED"
    SUSPENDED = "SUSPENDED"


class MemberStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    BOUNCED = "BOUNCED"


class SubscriptionStatus(str, Enum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class InvoiceReason(str, Enum):
    INITIAL = "INITIAL"
    RENEWAL = "RENEWAL"
    PRORATION_UPGRADE = "PRORATION_UPGRADE"
    WIN_BACK = "WIN_BACK"


class PaymentStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PostStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SENT = "SENT"
    ARCHIVED = "ARCHIVED"


class ContentType(str, Enum):
    POST = "POST"
    NEWSLETTER = "NEWSLETTER"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    CANCELED = "CANCELED"


class CommentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    HELD = "HELD"
    HIDDEN = "HIDDEN"


class PayoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    FAILED = "FAILED"


class Publication(TypedDict):
    id: str
    name: str
    creator_user_id: str
    platform_fee_bps: int
    status: str
    deliverability_status: str
    sent_count: int
    bounce_count: int
    bounce_rate: float
    lifetime_net_cents: int
    payout_balance_cents: int
    pending_payout_cents: int
    lifetime_paid_out_cents: int
    active_member_count: int
    mrr_cents: int
    recognized_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Tier(TypedDict):
    id: str
    publication_id: str
    name: str
    tier_rank: int
    monthly_price_cents: int
    trial_days: int
    is_free: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    publication_id: str
    email: str
    display_name: str
    status: str
    verification_token: str
    email_bounced: bool
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    tier_id: str
    status: str
    current_tier_rank: int
    current_period_start: str
    current_period_end: str
    trial_end: Optional[str]
    canceled_at: Optional[str]
    dunning_deadline: Optional[str]
    reactivation_count: int
    is_win_back: bool
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    subscription_id: str
    reason: str
    gross_cents: int
    discount_cents: int
    proration_factor: float
    amount_due_cents: int
    platform_fee_cents: int
    creator_net_cents: int
    payment_status: str
    due_at: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Post(TypedDict):
    id: str
    publication_id: str
    title: str
    body: str
    content_type: str
    min_tier_rank: int
    status: str
    send_window_start: Optional[str]
    send_window_end: Optional[str]
    recipient_count: int
    approved_comment_count: int
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    publication_id: str
    title: str
    starts_at: str
    ends_at: str
    registration_closes_at: str
    min_tier_rank: int
    capacity: int
    allow_waitlist: bool
    registered_count: int
    waitlist_count: int
    available_slots: int
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict):
    id: str
    event_id: str
    member_id: str
    status: str
    registered_at: str
    created_at: str
    updated_at: str
    version: int


class Comment(TypedDict):
    id: str
    post_id: str
    member_id: str
    body: str
    status: str
    moderation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    publication_id: str
    amount_cents: int
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
