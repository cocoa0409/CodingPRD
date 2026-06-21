"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values are taken verbatim from the PRD (Grocery Online
Ordering & Fulfillment). Monetary fields are integer cents.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STORE_OPS = "StoreOps"
    CUSTOMER = "Customer"
    PICKER = "Picker"


# ─── Status enums ─────────────────────────────────────
class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PickerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_SHIFT = "OFF_SHIFT"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class PricingMode(str, Enum):
    UNIT = "UNIT"
    WEIGHT = "WEIGHT"


class SlotType(str, Enum):
    DELIVERY = "DELIVERY"
    PICKUP = "PICKUP"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class FulfillmentStatus(str, Enum):
    PLACED = "PLACED"
    PICKING = "PICKING"
    STAGED = "STAGED"
    HANDED_OFF = "HANDED_OFF"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    PICKED = "PICKED"
    SUBSTITUTED = "SUBSTITUTED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    CANCELLED = "CANCELLED"


class SubstitutionPolicy(str, Enum):
    NO_SUBSTITUTION = "NO_SUBSTITUTION"
    SAME_PRICE_OR_LESS = "SAME_PRICE_OR_LESS"
    SHOPPER_CHOICE = "SHOPPER_CHOICE"


class SubstitutionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PaymentRecordStatus(str, Enum):
    CAPTURED = "CAPTURED"


class RefundReason(str, Enum):
    OUT_OF_STOCK = "OUT_OF_STOCK"


class AgeCheckOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ─── Entity TypedDicts ────────────────────────────────
# Entities carrying common_fields:true expose id, created_at, updated_at, version.

class Store(TypedDict):
    id: str
    name: str
    timezone: str
    ebt_enabled: bool
    cold_chain_hold_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    snap_ebt_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Picker(TypedDict):
    id: str
    store_id: str
    full_name: str
    window_cooldown_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    store_id: str
    sku: str
    name: str
    pricing_mode: str
    unit_price_cents: int
    ebt_eligible: bool
    age_restricted: bool
    cold_chain: bool
    on_hand_qty: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FulfillmentSlot(TypedDict):
    id: str
    store_id: str
    slot_type: str
    window_start: str
    window_end: str
    capacity: int
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    store_id: str
    customer_id: str
    slot_id: str
    picker_id: Optional[str]
    fulfillment_status: str
    payment_status: str
    tip_cents: int
    estimated_total_cents: int
    estimated_ebt_eligible_cents: int
    final_total_cents: int
    final_ebt_eligible_cents: int
    ebt_charged_cents: int
    card_charged_cents: int
    refunded_total_cents: int
    net_captured_cents: int
    staged_at: Optional[str]
    requires_age_check: bool
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    requested_qty: float
    estimated_weight_kg: Optional[float]
    picked_qty: Optional[float]
    actual_weight_kg: Optional[float]
    substitution_policy: str
    estimated_line_cents: int
    final_line_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Substitution(TypedDict):
    id: str
    order_line_id: str
    substitute_product_id: str
    substitute_qty: float
    substitute_weight_kg: Optional[float]
    substitute_line_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    order_id: str
    ebt_amount_cents: int
    card_amount_cents: int
    grand_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgeCheck(TypedDict):
    id: str
    order_id: str
    verifier_user_id: str
    verified_birth_date: str
    outcome: str
    created_at: str
    updated_at: str
    version: int


# Refund carries common_fields:false — append-only event record.
# It exposes ONLY id and created_at (no updated_at, no version).
class Refund(TypedDict):
    id: str
    order_id: str
    order_line_id: str
    amount_cents: int
    reason: str
    created_at: str
