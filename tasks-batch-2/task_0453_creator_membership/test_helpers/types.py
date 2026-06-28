"""Domain types for the Creator Membership API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CREATOR = "Creator"
    PATRON = "Patron"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CreatorStatus(str, Enum):
    ACTIVE = "ACTIVE"


class TierStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class PatronStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PledgeLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class PledgeBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    GRACE = "GRACE"
    LAPSED = "LAPSED"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class ChargeKind(str, Enum):
    INITIAL_PRORATION = "INITIAL_PRORATION"
    CYCLE_RENEWAL = "CYCLE_RENEWAL"
    UPGRADE_PRORATION = "UPGRADE_PRORATION"
    PER_CREATION = "PER_CREATION"
    WIN_BACK = "WIN_BACK"


class PostStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class ConversationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MessageSenderRole(str, Enum):
    CREATOR = "CREATOR"
    PATRON = "PATRON"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REVERSED = "REVERSED"


class WinBackOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class BillingModel(str, Enum):
    MONTHLY = "MONTHLY"
    PER_CREATION = "PER_CREATION"


class PlatformPlan(str, Enum):
    STARTER = "STARTER"
    PRO = "PRO"
    PREMIUM = "PREMIUM"


class ChargeTiming(str, Enum):
    UP_FRONT = "UP_FRONT"
    END_OF_MONTH = "END_OF_MONTH"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#   common_fields: true  → id, created_at, updated_at, version
#   common_fields: false → id, created_at ONLY  (PostAccess, Message)
# ---------------------------------------------------------------------------
class Creator(TypedDict):
    id: str
    display_name: str
    email: str
    platform_plan: str
    payout_account_ref: str
    billing_mode: str
    charge_timing: str
    pending_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Tier(TypedDict, total=False):
    id: str
    creator_id: str
    name: str
    monthly_fee_cents: Optional[int]
    per_creation_fee_cents: Optional[int]
    per_creation_monthly_cap_cents: Optional[int]
    billing_model: str
    rank: int
    benefit_labels: List[str]
    active_pledge_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Patron(TypedDict):
    id: str
    display_name: str
    email: str
    wallet_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict, total=False):
    id: str
    patron_id: str
    creator_id: str
    tier_id: str
    scheduled_tier_id: Optional[str]
    billing_model: str
    cycle_anchor_date: str
    current_cycle_charged_cents: int
    lifecycle_status: str
    billing_status: str
    grace_deadline: Optional[str]
    lapsed_at: Optional[str]
    win_back_applied: bool
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict, total=False):
    id: str
    pledge_id: str
    creator_id: str
    charge_kind: str
    cycle_anchor_date: str
    gross_amount_cents: int
    wallet_applied_cents: int
    net_amount_cents: int
    processing_fee_cents: int
    status: str
    swept_into_payout_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Post(TypedDict, total=False):
    id: str
    creator_id: str
    title: str
    body: str
    min_tier_rank: int
    is_paid_creation: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable access-grant record (no updated_at / version)
class PostAccess(TypedDict):
    id: str
    post_id: str
    patron_id: str
    pledge_id: str
    granted_tier_rank: int
    created_at: str


class Conversation(TypedDict):
    id: str
    creator_id: str
    patron_id: str
    status: str
    message_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only message log (no updated_at / version)
class Message(TypedDict):
    id: str
    conversation_id: str
    sender_role: str
    sender_id: str
    body: str
    created_at: str


class Payout(TypedDict):
    id: str
    creator_id: str
    cycle_anchor_date: str
    gross_cents: int
    platform_fee_cents: int
    processing_fee_cents: int
    payout_amount_cents: int
    swept_charge_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WinBackOffer(TypedDict):
    id: str
    pledge_id: str
    discount_pct: float
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
