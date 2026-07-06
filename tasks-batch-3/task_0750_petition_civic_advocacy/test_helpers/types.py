"""Domain types: entity TypedDicts, status enums, role enum.

All ten resources carry the full common-field set (id, created_at, updated_at,
version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    GUEST = "Guest"
    MEMBER = "Member"
    MODERATOR = "Moderator"
    ADMIN = "Admin"


class PetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    PUBLISHED = "PUBLISHED"
    CLOSED_VICTORY = "CLOSED_VICTORY"
    CLOSED_WITHDRAWN = "CLOSED_WITHDRAWN"
    REMOVED = "REMOVED"


class ModerationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"


class PetitionCategory(str, Enum):
    ENVIRONMENT = "ENVIRONMENT"
    POLITICS = "POLITICS"
    HEALTH = "HEALTH"
    EDUCATION = "EDUCATION"
    OTHER = "OTHER"


class TargetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    UNREACHABLE = "UNREACHABLE"


class SignatureStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class CommentType(str, Enum):
    COMMENT = "COMMENT"
    UPDATE = "UPDATE"


class CommentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    REMOVED = "REMOVED"


class CampaignStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DonationStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class PlacementTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    SPOTLIGHT = "SPOTLIGHT"


class PromotionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class DeliveryMeetingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class User(TypedDict):
    id: str
    email: str
    full_name: str
    jurisdiction: str
    role_hint: str
    created_at: str
    updated_at: str
    version: int


class Petition(TypedDict):
    id: str
    author_user_id: str
    title: str
    summary: str
    body: str
    category: str
    goal: int
    eligible_jurisdiction: Optional[str]
    status: str
    moderation_status: str
    verified_signature_count: int
    pending_signature_count: int
    goal_reached: bool
    milestone_thresholds: List[int]
    milestones_reached: List[int]
    approved_comment_count: int
    delivered_meeting_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Target(TypedDict):
    id: str
    petition_id: str
    representative_id: Optional[str]
    name: str
    title: str
    office: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Representative(TypedDict):
    id: str
    full_name: str
    office: str
    jurisdiction: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Signature(TypedDict):
    id: str
    petition_id: str
    signer_user_id: str
    public_comment: Optional[str]
    verification_token: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Comment(TypedDict):
    id: str
    petition_id: str
    author_user_id: str
    comment_type: str
    body: str
    status: str
    delivered: bool
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    petition_id: str
    goal_cents: int
    status: str
    gross_pledged_cents: int
    funds_raised_cents: int
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    campaign_id: str
    donor_user_id: str
    amount_cents: int
    platform_fee_cents: int
    net_to_campaign_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    petition_id: str
    purchaser_user_id: str
    category: str
    placement_tier: str
    window_start: str
    window_end: str
    duration_days: int
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryMeeting(TypedDict):
    id: str
    petition_id: str
    target_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
