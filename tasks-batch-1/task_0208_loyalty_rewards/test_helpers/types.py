"""Domain types: entity TypedDicts, status enums, role enum for the Loyalty Rewards API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    MEMBER = "Member"
    PARTNER_OPERATOR = "PartnerOperator"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TierCode(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class PointsLotSourceType(str, Enum):
    EARN_PURCHASE = "EARN_PURCHASE"
    EARN_BONUS = "EARN_BONUS"
    BIRTHDAY = "BIRTHDAY"
    REFERRAL = "REFERRAL"
    TRANSFER_IN_REVERSAL = "TRANSFER_IN_REVERSAL"


class PointsLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class PointsTransactionType(str, Enum):
    EARN_PURCHASE = "EARN_PURCHASE"
    EARN_BONUS = "EARN_BONUS"
    BIRTHDAY = "BIRTHDAY"
    REFERRAL = "REFERRAL"
    REDEEM = "REDEEM"
    TRANSFER_OUT = "TRANSFER_OUT"
    EXPIRE = "EXPIRE"
    TRANSFER_IN_REVERSAL = "TRANSFER_IN_REVERSAL"


class PromotionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class CatalogRewardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class RedemptionStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PartnerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class TransferBlackoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class PartnerTransferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id, created_at, updated_at, version
# common_fields: false -> id, created_at ONLY (append-only / child records)
# ---------------------------------------------------------------------------
class LoyaltyProgram(TypedDict):
    id: str
    name: str
    base_earn_rate: float
    point_value_cents: float
    lot_expiration_months: int
    qualifying_window_months: int
    birthday_reward_points: int
    referral_referrer_points: int
    referral_referee_points: int
    referral_min_qualifying_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Tier(TypedDict):
    id: str
    program_id: str
    code: str
    qualify_threshold: int
    earn_multiplier: float
    transfer_ratio: float
    rank: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    program_id: str
    email: str
    full_name: str
    birth_month_day: str
    referred_by_member_id: Optional[str]
    current_tier_code: str
    available_points: int
    projected_points: int
    qualifying_points_window: int
    lifetime_earned_points: int
    status: str
    last_birthday_grant_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PointsLot(TypedDict):
    id: str
    member_id: str
    source_type: str
    source_id: Optional[str]
    original_points: int
    remaining_points: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger row: id + created_at only.
class PointsTransaction(TypedDict):
    id: str
    member_id: str
    lot_id: Optional[str]
    type: str
    points_delta: int
    qualifying_points: int
    ref_redemption_id: Optional[str]
    ref_transfer_id: Optional[str]
    created_at: str


class Promotion(TypedDict):
    id: str
    program_id: str
    name: str
    bonus_multiplier: float
    starts_at: str
    ends_at: str
    min_eligible_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CatalogReward(TypedDict):
    id: str
    program_id: str
    name: str
    point_cost: int
    tier_discount_pct: float
    stock: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Redemption(TypedDict):
    id: str
    member_id: str
    quoted_cost_points: int
    final_cost_points: Optional[int]
    status: str
    expected_member_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Child record fixed at quote time: id + created_at only.
class RedemptionLine(TypedDict):
    id: str
    redemption_id: str
    reward_id: str
    quantity: int
    line_cost_points: int
    created_at: str


class Referral(TypedDict):
    id: str
    program_id: str
    referrer_member_id: str
    referee_member_id: Optional[str]
    referee_email: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartnerAccount(TypedDict):
    id: str
    program_id: str
    name: str
    transfer_block_size: int
    min_transfer_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferBlackout(TypedDict):
    id: str
    partner_account_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PartnerTransfer(TypedDict):
    id: str
    member_id: str
    partner_account_id: str
    loyalty_points: int
    partner_points: int
    status: str
    expected_member_version: int
    created_at: str
    updated_at: str
    version: int


class PurchaseEvent(TypedDict):
    id: str
    member_id: str
    eligible_amount_cents: int
    occurred_at: Optional[str]
    earned_points: int
    qualifying_points: int
    applied_promotion_id: Optional[str]
    posted: bool
    created_at: str
    updated_at: str
    version: int
