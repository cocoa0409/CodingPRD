"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Vitamin & Supplement Store PRD. Every persisted resource
carries id/created_at/updated_at/version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enumerations ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    STORE_OPERATOR = "StoreOperator"
    CUSTOMER = "Customer"
    PRACTITIONER = "Practitioner"


class ProductForm(str, Enum):
    CAPSULE = "CAPSULE"
    TABLET = "TABLET"
    POWDER = "POWDER"
    GUMMY = "GUMMY"
    LIQUID = "LIQUID"


class RegimenGoal(str, Enum):
    IMMUNITY = "IMMUNITY"
    SLEEP = "SLEEP"
    ENERGY = "ENERGY"
    JOINT = "JOINT"
    DIGESTION = "DIGESTION"


class DsheaClaimType(str, Enum):
    STRUCTURE_FUNCTION = "STRUCTURE_FUNCTION"
    NONE = "NONE"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    RECALLED = "RECALLED"
    EXPIRED = "EXPIRED"


class RecallSeverity(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class RecommendationStatus(str, Enum):
    ISSUED = "ISSUED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class OrderType(str, Enum):
    ONE_OFF = "ONE_OFF"
    AUTOSHIP = "AUTOSHIP"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ReturnReason(str, Enum):
    DEFECT = "DEFECT"
    UNWANTED = "UNWANTED"
    RECALL = "RECALL"
    EXPIRED = "EXPIRED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REFUNDED = "REFUNDED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ───────

class Product(TypedDict):
    id: str
    name: str
    form: str
    regimen_goals: List[str]
    is_practitioner_line: bool
    dshea_claim_type: str
    requires_fda_disclaimer: bool
    unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    product_id: str
    lot_number: str
    expiration_date: str
    quantity_received: int
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int
    status: str
    recall_reason: Optional[str]
    recall_severity: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    status: str
    lifetime_points_earned: int
    points_balance: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Practitioner(TypedDict):
    id: str
    full_name: str
    license_number: str
    created_at: str
    updated_at: str
    version: int


class Recommendation(TypedDict):
    id: str
    practitioner_id: str
    customer_id: str
    product_id: str
    issued_at: str
    expires_at: str
    max_units: int
    consumed_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bundle(TypedDict):
    id: str
    name: str
    component_product_ids: List[str]
    discount_pct: float
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    product_id: str
    quantity_per_cycle: int
    cadence_days: int
    first_ship_date: str
    next_ship_date: str
    autoship_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    subscription_id: Optional[str]
    order_type: str
    points_redeemed: int
    status: str
    provisional_subtotal_cents: Optional[int]
    final_subtotal_cents: Optional[int]
    redemption_cents: int
    total_cents: Optional[int]
    points_earned: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    bundle_id: Optional[str]
    quantity: int
    gross_unit_price_cents: int
    net_unit_price_cents: int
    line_total_cents: int
    lot_allocations: list
    short_quantity: int
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict):
    id: str
    order_id: str
    order_line_id: str
    quantity: int
    reason: str
    status: str
    refund_cents: Optional[int]
    points_reversed: Optional[int]
    restock: Optional[bool]
    created_at: str
    updated_at: str
    version: int
