"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entities and lifecycle states described in the Reward Crowdfunding PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CREATOR = "Creator"
    BACKER = "Backer"


# --- Status enums ---
class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    CLOSING = "CLOSING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class FundingModel(str, Enum):
    ALL_OR_NOTHING = "ALL_OR_NOTHING"
    FLEXIBLE = "FLEXIBLE"


class TierStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SOLD_OUT = "SOLD_OUT"
    RETIRED = "RETIRED"


class PaymentStatus(str, Enum):
    PENDING_AUTH = "PENDING_AUTH"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    AUTH_DECLINED = "AUTH_DECLINED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SURVEY_SENT = "SURVEY_SENT"
    SURVEY_COMPLETE = "SURVEY_COMPLETE"
    SHIPPED = "SHIPPED"


class PledgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELED = "CANCELED"


class DestinationZone(str, Enum):
    DOMESTIC = "DOMESTIC"
    INTL = "INTL"


class AuthorizationOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    DECLINED = "DECLINED"


class RefundReason(str, Enum):
    FAILED_CAMPAIGN = "FAILED_CAMPAIGN"
    BACKER_CANCEL = "BACKER_CANCEL"


# --- Entity TypedDicts ---

# common_fields: true — id + created_at + updated_at + version
class Creator(TypedDict):
    id: str
    display_name: str
    payout_currency: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Backer(TypedDict):
    id: str
    email: str
    display_name: str
    lifetime_authorized_cents: int
    lifetime_captured_cents: int
    declined_auth_count: int
    reliability_score: float
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Campaign(TypedDict):
    id: str
    creator_id: str
    title: str
    currency: str
    funding_goal_cents: int
    funding_model: str
    deadline_utc: str
    status: str
    committed_amount_cents: int
    settled_amount_cents: Optional[int]
    goal_met: Optional[bool]
    launched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class RewardTier(TypedDict):
    id: str
    campaign_id: str
    title: str
    price_cents: int
    limit_quantity: Optional[int]
    claimed_quantity: int
    weight_grams: int
    is_early_bird: bool
    available_from: Optional[str]
    available_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class StretchGoal(TypedDict):
    id: str
    campaign_id: str
    title: str
    threshold_cents: int
    unlocked: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class AddOn(TypedDict):
    id: str
    campaign_id: str
    title: str
    price_cents: int
    limit_quantity: Optional[int]
    claimed_quantity: int
    weight_grams: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Pledge(TypedDict):
    id: str
    campaign_id: str
    backer_id: str
    tier_id: str
    pledge_amount_cents: int
    destination_zone: str
    items_subtotal_cents: int
    shipping_cents: int
    committed_amount_cents: int
    payment_status: str
    fulfillment_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only line, ONLY id + created_at
class PledgeAddOn(TypedDict):
    id: str
    pledge_id: str
    addon_id: str
    quantity: int
    line_total_cents: int
    created_at: str


# common_fields: false — append-only event, ONLY id + created_at
class PaymentAuthorization(TypedDict):
    id: str
    pledge_id: str
    outcome: str
    amount_cents: int
    created_at: str


# common_fields: false — append-only event, ONLY id + created_at
class Refund(TypedDict):
    id: str
    pledge_id: str
    reason: str
    amount_cents: int
    created_at: str


# common_fields: true
class FulfillmentSurvey(TypedDict):
    id: str
    pledge_id: str
    shipping_address: Optional[str]
    completed: bool
    created_at: str
    updated_at: str
    version: int


# Settlement read shape (computed read, not a stored entity)
class Settlement(TypedDict):
    settled_amount_cents: int
    platform_fee_cents: int
    creator_payout_cents: int
    captured_pledge_count: int
