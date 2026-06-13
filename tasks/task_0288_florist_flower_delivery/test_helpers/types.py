"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enums ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CUSTOMER = "Customer"
    FLORIST = "Florist"
    DISPATCHER = "Dispatcher"
    CATALOG_ADMIN = "CatalogAdmin"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class PremiumTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class SubstitutionPolicy(str, Enum):
    NONE = "NONE"
    SAME_VALUE = "SAME_VALUE"
    FLORIST_CHOICE = "FLORIST_CHOICE"


class Occasion(str, Enum):
    GENERAL = "GENERAL"
    BIRTHDAY = "BIRTHDAY"
    ANNIVERSARY = "ANNIVERSARY"
    SYMPATHY = "SYMPATHY"
    ROMANCE = "ROMANCE"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class WireFulfillmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    RELEASED = "RELEASED"


class ClaimReason(str, Enum):
    WILTED = "WILTED"
    WRONG_ITEM = "WRONG_ITEM"
    LATE = "LATE"
    DAMAGED = "DAMAGED"


class ClaimRemedy(str, Enum):
    REDELIVERY = "REDELIVERY"
    REFUND = "REFUND"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"


class Cadence(str, Enum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ─

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    loyalty_tier: str
    lifetime_delivered_count: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliveryZone(TypedDict):
    id: str
    zone_code: str
    base_delivery_fee_cents: int
    same_day_cutoff_hour_utc: int
    window_capacity_per_slot: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Arrangement(TypedDict):
    id: str
    sku: str
    display_name: str
    base_price_cents: int
    premium_tier: str
    substitution_policy: str
    substitution_cap_pct: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class HolidayWindow(TypedDict):
    id: str
    name: str
    start_date: str
    end_date: str
    surge_multiplier: float
    applies_to_standard: bool
    surge_cutoff_hour_utc: int
    created_at: str
    updated_at: str
    version: int


class Florist(TypedDict):
    id: str
    shop_name: str
    covered_zone_id: str
    daily_capacity: int
    quality_rating: float
    wire_surcharge_cents: int
    accepting: bool
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    arrangement_id: str
    zone_id: str
    parent_recurrence_id: Optional[str]
    source_order_id: Optional[str]
    occasion: str
    card_message: str
    delivery_date: str
    window_start_minute: int
    window_end_minute: int
    apply_wallet_credit: bool
    fulfillment_status: str
    payment_status: str
    estimated_total_cents: int
    final_total_cents: int
    wallet_credit_applied_cents: int
    is_same_day: bool
    created_at: str
    updated_at: str
    version: int


class WireFulfillment(TypedDict):
    id: str
    order_id: str
    florist_id: str
    assigned_delivery_date: str
    status: str
    florist_surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class Substitution(TypedDict):
    id: str
    order_id: str
    florist_id: str
    removed_stem: str
    added_stem: str
    price_delta_cents: int
    accepted: bool
    created_at: str
    updated_at: str
    version: int


class QualityClaim(TypedDict):
    id: str
    order_id: str
    customer_id: str
    reason: str
    requested_remedy: str
    status: str
    refund_cents: int
    redelivery_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecurringSchedule(TypedDict):
    id: str
    customer_id: str
    arrangement_id: str
    zone_id: str
    cadence: str
    next_delivery_date: str
    window_start_minute: int
    window_end_minute: int
    occurrences_remaining: int
    status: str
    recurring_discount_pct: float
    created_at: str
    updated_at: str
    version: int


# ─── Lighter entities (common_fields: false → only id + created_at) ───────────

class DeliverySlot(TypedDict):
    id: str
    order_id: str
    zone_id: str
    slot_date: str
    slot_start_minute: int
    slot_end_minute: int
    released: bool
    created_at: str


class ClockState(TypedDict):
    id: str
    current_utc: str
    created_at: str
