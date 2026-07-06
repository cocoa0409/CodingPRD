"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    FULFILLMENT_OPS = "FulfillmentOps"
    BILLING_ADMIN = "BillingAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Customer status ---
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


# --- Plan enums ---
class Cadence(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class BouquetStyle(str, Enum):
    ROUND = "ROUND"
    GARDEN = "GARDEN"
    EUROPEAN = "EUROPEAN"


class BouquetSize(str, Enum):
    PETITE = "PETITE"
    ORIGINAL = "ORIGINAL"
    DELUXE = "DELUXE"
    GRAND = "GRAND"


# --- Subscription enums ---
class SubscriptionLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class SubscriptionBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"


# --- Shipment ---
class ShipmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SKIPPED = "SKIPPED"
    SOURCING = "SOURCING"
    SOURCED = "SOURCED"
    SUBSTITUTED = "SUBSTITUTED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# --- Stem lot / allocation ---
class StemGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class ColdChainState(str, Enum):
    FRESH = "FRESH"
    EXPIRED = "EXPIRED"


class StemAllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


# --- Charge ---
class ChargeKind(str, Enum):
    RENEWAL = "RENEWAL"
    UPCHARGE = "UPCHARGE"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


# --- Wallet entry ---
class WalletReason(str, Enum):
    REFUND = "REFUND"
    SKIP_CREDIT = "SKIP_CREDIT"
    ADJUSTMENT = "ADJUSTMENT"


# --- Win-back offer ---
class WinBackOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


# --- Entity TypedDicts ---


class Customer(TypedDict):
    """common_fields: true — id, created_at, updated_at, version + specific fields."""

    id: str
    email: str
    full_name: str
    default_zip: Optional[str]
    status: str
    lifetime_cycles: int
    loyalty_tier: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict):
    id: str
    name: str
    cadence: str
    base_fee_cents: int
    default_style: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    plan_id: str
    size: str
    style: str
    vase_addon: bool
    is_gift: bool
    occasion: Optional[str]
    gift_message: Optional[str]
    lifecycle_status: str
    billing_status: str
    current_cycle_index: int
    next_renewal_date: str
    discount_pct: float
    renewal_price_cents: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    subscription_id: str
    cycle_index: int
    scheduled_delivery_date: str
    status: str
    occasion: Optional[str]
    gift_message: Optional[str]
    substitution_applied: bool
    route_id: Optional[str]
    delivery_window_start: Optional[str]
    delivery_window_end: Optional[str]
    stem_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StemLot(TypedDict):
    id: str
    variety: str
    grade: str
    quantity_total: int
    unit_cost_cents: int
    sourced_at: str
    shelf_life_hours: int
    quantity_available: int
    usable_until: str
    cold_chain_state: str
    created_at: str
    updated_at: str
    version: int


class StemAllocation(TypedDict):
    id: str
    shipment_id: str
    lot_id: str
    quantity_reserved: int
    hold_start: str
    hold_end: str
    status: str
    reserved_value_cents: int
    committed_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CarrierRoute(TypedDict):
    id: str
    zone: str
    service_date: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    subscription_id: str
    cycle_index: int
    kind: str
    amount_cents: int
    status: str
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at (no updated_at, no version)
class WalletEntry(TypedDict):
    id: str
    customer_id: str
    amount_cents: int
    reason: str
    related_charge_id: Optional[str]
    created_at: str


class WinBackOffer(TypedDict):
    id: str
    customer_id: str
    discount_pct: float
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at (no updated_at, no version)
class SubstitutionRule(TypedDict):
    id: str
    from_variety: str
    to_variety: str
    allowed: bool
    max_substitution_pct: float
    quality_floor_grade: str
    created_at: str
