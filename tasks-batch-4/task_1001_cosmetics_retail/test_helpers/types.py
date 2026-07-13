"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    CUSTOMER = "Customer"
    STORE_ASSOCIATE = "StoreAssociate"
    BEAUTY_ARTIST = "BeautyArtist"
    MERCHANDISING_ADMIN = "MerchandisingAdmin"


# ─── Enums (PRD §3) ───────────────────────────────────

class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class ProductCategory(str, Enum):
    SKINCARE = "SKINCARE"
    MAKEUP = "MAKEUP"
    FRAGRANCE = "FRAGRANCE"
    HAIR = "HAIR"


class HygieneClass(str, Enum):
    SEALED = "SEALED"
    TESTER_APPLIED = "TESTER_APPLIED"
    DIRECT_CONTACT = "DIRECT_CONTACT"


class Finish(str, Enum):
    MATTE = "MATTE"
    DEWY = "DEWY"
    SATIN = "SATIN"


class Undertone(str, Enum):
    WARM = "WARM"
    COOL = "COOL"
    NEUTRAL = "NEUTRAL"


class VariantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class LaunchStatus(str, Enum):
    NOT_LIMITED = "NOT_LIMITED"
    SCHEDULED = "SCHEDULED"
    TIER_ROUGE_ONLY = "TIER_ROUGE_ONLY"
    TIER_VIB_PLUS = "TIER_VIB_PLUS"
    PUBLIC = "PUBLIC"
    CLOSED = "CLOSED"


class Tier(str, Enum):
    INSIDER = "INSIDER"
    VIB = "VIB"
    ROUGE = "ROUGE"


class ReturnPrivilege(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PromoType(str, Enum):
    GWP = "GWP"
    SAMPLE = "SAMPLE"
    BUNDLE = "BUNDLE"


class PromotionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class Channel(str, Enum):
    BOPIS = "BOPIS"
    SHIP_FROM_STORE = "SHIP_FROM_STORE"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class PricingVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class LineType(str, Enum):
    SALE = "SALE"
    GWP = "GWP"
    SAMPLE = "SAMPLE"


class PointsEntryType(str, Enum):
    SEED = "SEED"
    EARN = "EARN"
    REDEEM = "REDEEM"
    REVERSAL = "REVERSAL"
    CLAWBACK = "CLAWBACK"
    SERVICE_BONUS = "SERVICE_BONUS"


class ServiceType(str, Enum):
    BROW = "BROW"
    MAKEOVER = "MAKEOVER"


class ArtistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    RESCHEDULE_PENDING = "RESCHEDULE_PENDING"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReturnReason(str, Enum):
    WRONG_SHADE = "WRONG_SHADE"
    DAMAGED = "DAMAGED"
    CHANGED_MIND = "CHANGED_MIND"
    ALLERGIC_REACTION = "ALLERGIC_REACTION"


class DenyReason(str, Enum):
    HYGIENE_VIOLATION = "HYGIENE_VIOLATION"
    NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"
    OUT_OF_POLICY = "OUT_OF_POLICY"


class Disposition(str, Enum):
    RESTOCK = "RESTOCK"
    DESTROY = "DESTROY"


# ─── Entities (PRD §2.5, §3) ──────────────────────────
# Every resource below except PointsLedgerEntry carries id/created_at/updated_at/version.
# A points-ledger entry is append-only: id and created_at only.


class Store(TypedDict):
    id: str
    name: str
    region_code: str
    status: str
    bopis_slot_capacity: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    name: str
    brand: str
    category: str
    hygiene_class: str
    base_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Variant(TypedDict):
    id: str
    product_id: str
    shade_name: str
    shade_code: str
    finish: str
    undertone: str
    depth_index: int
    price_cents: int
    status: str
    is_limited_launch: bool
    launch_status: str
    launch_open_rouge_at: Optional[str]
    launch_open_vib_at: Optional[str]
    launch_open_public_at: Optional[str]
    per_customer_cap: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    store_id: str
    variant_id: str
    units_received: int
    on_hand_units: int
    reserved_units: int
    tester_units: int
    sold_units: int
    destroyed_units: int
    launch_reserved_units: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    name: str
    tier: str
    points_balance: int
    qualifying_spend_cents: int
    lifetime_spend_cents: int
    cycle_started_at: str
    hygiene_strikes: int
    return_privilege: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    name: str
    promo_type: str
    threshold_cents: int
    gift_variant_id: Optional[str]
    gift_quantity: int
    bundle_variant_ids: Optional[List[str]]
    bundle_discount_pct: float
    priority: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    store_id: str
    channel: str
    pickup_slot_start: Optional[str]
    allow_partial: bool
    points_redeemed: int
    fulfillment_status: str
    payment_status: str
    pricing_variant: str
    tier_at_reserve: Optional[str]
    subtotal_cents: int
    tier_discount_cents: int
    discounted_subtotal_cents: int
    gwp_eligible: bool
    points_value_cents: int
    total_due_cents: int
    points_earned: int
    refunded_cents: int
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    variant_id: str
    promotion_id: Optional[str]
    line_type: str
    quantity: int
    unit_price_cents: int
    line_gross_cents: int
    line_discount_cents: int
    line_net_cents: int
    hygiene_class: str
    returned_quantity: int
    created_at: str
    updated_at: str
    version: int


class PointsLedgerEntry(TypedDict):
    """Append-only and immutable (PRD §2.5): id and created_at only — no updated_at, no version."""
    id: str
    customer_id: str
    order_id: Optional[str]
    entry_type: str
    delta_points: int
    balance_after: int
    created_at: str


class Artist(TypedDict):
    id: str
    store_id: str
    name: str
    skills: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceBooking(TypedDict):
    id: str
    customer_id: str
    store_id: str
    artist_id: str
    linked_order_id: Optional[str]
    service_type: str
    start_at: str
    duration_minutes: int
    proposed_start_at: Optional[str]
    status: str
    reschedule_count: int
    bonus_points_awarded: int
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict):
    id: str
    order_line_id: str
    quantity: int
    reason: str
    status: str
    deny_reason: Optional[str]
    disposition: Optional[str]
    refund_line_cents: int
    restocking_fee_cents: int
    refund_cents: int
    points_clawback: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
