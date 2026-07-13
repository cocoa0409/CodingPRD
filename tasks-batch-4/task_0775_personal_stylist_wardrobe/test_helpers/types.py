"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API are common-fielded resources: each carries a
server-minted ``id``, ``created_at``, ``updated_at`` and an integer ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─────────────────────────── Roles ───────────────────────────
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CLIENT = "Client"
    STYLIST = "Stylist"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─────────────────────────── Status enums ───────────────────────────
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"


class StylistStatus(str, Enum):
    ACTIVE = "ACTIVE"


class StylistTier(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    LEAD = "LEAD"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"


class ColorPalette(str, Enum):
    WARM = "WARM"
    COOL = "COOL"
    NEUTRAL = "NEUTRAL"


class BudgetBand(str, Enum):
    ECONOMY = "ECONOMY"
    MID = "MID"
    PREMIUM = "PREMIUM"
    LUXURY = "LUXURY"


class EngagementMode(str, Enum):
    HOURLY = "HOURLY"
    PACKAGE = "PACKAGE"


class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class SessionType(str, Enum):
    CLOSET_AUDIT = "CLOSET_AUDIT"
    SHOPPING = "SHOPPING"
    VIRTUAL = "VIRTUAL"
    EVENT = "EVENT"


class SessionModality(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ChargeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PurchaseItemStatus(str, Enum):
    PURCHASED = "PURCHASED"
    RETURNED = "RETURNED"


class LookbookStatus(str, Enum):
    DRAFT = "DRAFT"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"


class SubscriptionTier(str, Enum):
    SILVER = "SILVER"
    GOLD = "GOLD"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED_UP = "SIGNED_UP"
    CREDITED = "CREDITED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"


# ─────────────────────────── Entity TypedDicts ───────────────────────────
class Client(TypedDict):
    id: str
    full_name: str
    email: str
    wallet_credit_cents: int
    has_paid_invoice: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Stylist(TypedDict):
    id: str
    full_name: str
    email: str
    commission_pct: float
    tier: str
    earned_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StyleAssessment(TypedDict):
    id: str
    client_id: str
    body_type: str
    color_palette: str
    budget_band: str
    lifestyle: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    client_id: str
    stylist_id: str
    mode: str
    block_rate_cents: int
    package_blocks: Optional[int]
    package_price_cents: Optional[int]
    hours_reserved_blocks: int
    hours_consumed_blocks: int
    hours_available_blocks: int
    retail_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    engagement_id: str
    session_type: str
    modality: str
    scheduled_start: str
    scheduled_end: str
    estimated_blocks: int
    actual_minutes: Optional[int]
    charge_cents: int
    charge_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseItem(TypedDict):
    id: str
    session_id: str
    description: str
    retail_cost_cents: int
    markup_pct: float
    marked_up_price_cents: int
    commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lookbook(TypedDict):
    id: str
    engagement_id: str
    title: str
    outfits: list
    outfit_count: int
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    client_id: str
    tier: str
    monthly_fee_cents: int
    refresh_credits_total: int
    refresh_credits_remaining: int
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referrer_client_id: str
    referee_email: str
    referee_client_id: Optional[str]
    qualifying_invoice_id: Optional[str]
    estimated_credit_cents: int
    realized_credit_cents: int
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    engagement_id: str
    line_items: list
    subtotal_cents: int
    styling_fee_cents: int
    volume_discount_cents: int
    wallet_credit_applied_cents: int
    total_cents: int
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
