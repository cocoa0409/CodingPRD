"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class JoinPolicy(str, Enum):
    OPEN = "OPEN"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class RosterStatus(str, Enum):
    ACCEPTING = "ACCEPTING"
    FULL = "FULL"


class HealthTier(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class MembershipRole(str, Enum):
    MEMBER = "MEMBER"
    MODERATOR = "MODERATOR"


class MembershipStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    LEFT = "LEFT"
    REMOVED = "REMOVED"


class GiftCategory(str, Enum):
    FURNITURE = "FURNITURE"
    CLOTHING = "CLOTHING"
    FOOD = "FOOD"
    HOUSEHOLD = "HOUSEHOLD"
    ELECTRONICS = "ELECTRONICS"
    OTHER = "OTHER"


class ClaimMode(str, Enum):
    FIRST_COME = "FIRST_COME"
    FAIRNESS_DRAW = "FAIRNESS_DRAW"
    GIVER_PICK = "GIVER_PICK"


class GiftPostStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    QUEUED = "QUEUED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    FULFILLED = "FULFILLED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    NO_SHOW = "NO_SHOW"


class PickupPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class WishlistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MATCHED = "MATCHED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CurbAlertStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class ReportTargetType(str, Enum):
    MEMBER = "MEMBER"
    GIFT_POST = "GIFT_POST"
    CLAIM = "CLAIM"
    CURB_ALERT = "CURB_ALERT"


class ReportCategory(str, Enum):
    NO_SHOW = "NO_SHOW"
    SAFETY = "SAFETY"
    SPAM = "SPAM"
    PROHIBITED_ITEM = "PROHIBITED_ITEM"
    HARASSMENT = "HARASSMENT"
    OTHER = "OTHER"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_ACTION = "RESOLVED_ACTION"
    RESOLVED_DISMISSED = "RESOLVED_DISMISSED"


class ModerationActionType(str, Enum):
    WARNING = "WARNING"
    STRIKE = "STRIKE"
    CONTENT_REMOVAL = "CONTENT_REMOVAL"


class ModerationActionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    OVERTURNED = "OVERTURNED"


class ReputationEventType(str, Enum):
    WELCOME_BONUS = "WELCOME_BONUS"
    GIFT_COMPLETED = "GIFT_COMPLETED"
    RECEIVE_COMPLETED = "RECEIVE_COMPLETED"
    NO_SHOW_PENALTY = "NO_SHOW_PENALTY"
    STRIKE_APPLIED = "STRIKE_APPLIED"


class ReputationEventStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    GROUP_MODERATOR = "GroupModerator"
    PLATFORM_ADMIN = "PlatformAdmin"


# common_fields: true — carries id + created_at + updated_at + version (PRD §2.4)
class Member(TypedDict, total=False):
    id: str
    email: str
    display_name: str
    status: str
    reputation_score: float
    pending_reputation_score: float
    fairness_score: int
    active_strike_points: int
    given_count_90d: int
    received_count_90d: int
    suspension_ends_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NeighborhoodGroup(TypedDict, total=False):
    id: str
    name: str
    zip_code: str
    join_policy: str
    capacity: int
    member_count: int
    roster_status: str
    health_score: int
    health_tier: str
    created_at: str
    updated_at: str
    version: int


class GroupMembership(TypedDict, total=False):
    id: str
    member_id: str
    group_id: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftPost(TypedDict, total=False):
    id: str
    group_id: str
    giver_id: str
    title: str
    description: str
    category: str
    claim_mode: str
    status: str
    expires_at: str
    current_claim_id: Optional[str]
    current_offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    post_id: str
    claimer_id: str
    status: str
    claim_seq: int
    offered_at: Optional[str]
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PickupPlan(TypedDict, total=False):
    id: str
    claim_id: str
    proposer_id: str
    last_proposer_id: str
    window_start: str
    window_end: str
    location_note: str
    round_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Wishlist(TypedDict, total=False):
    id: str
    member_id: str
    group_id: str
    keyword: str
    category: Optional[str]
    status: str
    matched_post_id: Optional[str]
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class CurbAlert(TypedDict, total=False):
    id: str
    group_id: str
    creator_id: str
    zone: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    group_id: str
    reporter_id: str
    target_type: str
    target_id: str
    category: str
    details: str
    status: str
    reviewed_by: Optional[str]
    sla_due_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModerationAction(TypedDict, total=False):
    id: str
    report_id: str
    member_id: str
    action_type: str
    severity_points: Optional[int]
    rationale: str
    status: str
    active_until: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger entry; carries ONLY id + created_at
# (PRD §2.4: both updated_at and version are absent from ReputationEvent)
class ReputationEvent(TypedDict, total=False):
    id: str
    member_id: str
    event_type: str
    base_points: float
    status: str
    settled_at: Optional[str]
    created_at: str
