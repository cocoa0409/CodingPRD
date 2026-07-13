"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource shapes described in the Greeting-Card Reminder PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    ACCOUNT_HOLDER = "AccountHolder"
    STUDIO_OPERATOR = "StudioOperator"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SubscriptionTier(str, Enum):
    FREE = "FREE"
    PLUS = "PLUS"
    PRO = "PRO"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class CreditReason(str, Enum):
    SUBSCRIPTION_GRANT = "SUBSCRIPTION_GRANT"
    PRORATION_GRANT = "PRORATION_GRANT"
    ORDER_HOLD = "ORDER_HOLD"
    ORDER_REFUND = "ORDER_REFUND"
    MANUAL_ADJUST = "MANUAL_ADJUST"


class AddressStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    UNDELIVERABLE = "UNDELIVERABLE"


class OccasionType(str, Enum):
    BIRTHDAY = "BIRTHDAY"
    ANNIVERSARY = "ANNIVERSARY"
    HOLIDAY = "HOLIDAY"
    CUSTOM = "CUSTOM"


class Recurrence(str, Enum):
    NONE = "NONE"
    ANNUAL = "ANNUAL"


class ImportantDateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CardCategory(str, Enum):
    BIRTHDAY = "BIRTHDAY"
    THANK_YOU = "THANK_YOU"
    HOLIDAY = "HOLIDAY"
    SYMPATHY = "SYMPATHY"
    CUSTOM = "CUSTOM"


class CatalogStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class GiftKind(str, Enum):
    GIFT_CARD = "GIFT_CARD"
    FLOWERS = "FLOWERS"
    CHOCOLATE = "CHOCOLATE"
    CUSTOM_NOTE = "CUSTOM_NOTE"


class ArtistStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF = "OFF"


class FontStyle(str, Enum):
    SCRIPT = "SCRIPT"
    PRINT = "PRINT"
    CASUAL = "CASUAL"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PROOF = "PENDING_PROOF"
    PROOF_APPROVED = "PROOF_APPROVED"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    MAILED = "MAILED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CreditStatus(str, Enum):
    NONE = "NONE"
    HELD = "HELD"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class ProofStatus(str, Enum):
    PENDING = "PENDING"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class AssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class Carrier(str, Enum):
    USPS = "USPS"
    UPS = "UPS"


class ShipmentStatus(str, Enum):
    LABEL_CREATED = "LABEL_CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# First-class resources carry id + created_at + updated_at + version.
class Account(TypedDict):
    id: str
    email: str
    display_name: str
    status: str
    card_credit_balance: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    account_id: str
    tier: str
    monthly_card_credits: int
    monthly_fee_cents: int
    discount_pct: float
    status: str
    current_period_start: str
    current_period_end: str
    next_renewal_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger row: ONLY id + created_at (no updated_at, no version).
class CreditTransaction(TypedDict):
    id: str
    account_id: str
    delta: int
    reason: str
    balance_after: int
    created_at: str


class Contact(TypedDict):
    id: str
    account_id: str
    full_name: str
    address_line1: str
    address_line2: Optional[str]
    city: str
    region: str
    postal_code: str
    country_code: str
    address_status: str
    created_at: str
    updated_at: str
    version: int


class ImportantDate(TypedDict):
    id: str
    contact_id: str
    occasion_type: str
    event_date: str
    lead_days: int
    recurrence: str
    auto_send: bool
    default_card_id: Optional[str]
    status: str
    next_trigger_at: str
    created_at: str
    updated_at: str
    version: int


class Card(TypedDict):
    id: str
    sku: str
    title: str
    category: str
    base_price_cents: int
    weight_grams: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftItem(TypedDict):
    id: str
    sku: str
    title: str
    kind: str
    price_cents: int
    weight_grams: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HandwritingArtist(TypedDict):
    id: str
    name: str
    region_code: str
    daily_capacity: int
    status: str
    reserved_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    account_id: str
    contact_id: str
    card_id: str
    gift_item_id: Optional[str]
    gift_quantity: int
    important_date_id: Optional[str]
    artist_id: Optional[str]
    message_text: str
    font_style: str
    scheduled_send_at: str
    status: str
    credit_status: str
    estimated_total_cents: int
    postage_cents: int
    gift_discount_cents: int
    tax_cents: int
    final_total_cents: Optional[int]
    mailed_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Proof(TypedDict):
    id: str
    order_id: str
    status: str
    proof_image_ref: str
    revision_count: int
    reviewer_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ArtistAssignment(TypedDict):
    id: str
    artist_id: str
    order_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    carrier: str
    tracking_number: str
    status: str
    mailed_at: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
