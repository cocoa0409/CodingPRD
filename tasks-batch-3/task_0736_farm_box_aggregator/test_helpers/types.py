"""Domain types: entity TypedDicts, status enums, role enum.

All names use the Farm-Box Aggregator PRD's vocabulary.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FARM = "Farm"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Enumerated attribute domains
# ---------------------------------------------------------------------------
class ProductCategory(str, Enum):
    PRODUCE = "PRODUCE"
    DAIRY = "DAIRY"
    MEAT = "MEAT"
    PANTRY = "PANTRY"
    OTHER = "OTHER"


class PricingMode(str, Enum):
    FIXED = "FIXED"
    WEIGHT = "WEIGHT"


class HubType(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class BoxSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class Cadence(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"


class FulfillmentType(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


# ---------------------------------------------------------------------------
# State-machine status enums (PRD §3.2, §3.4, §3.6, §3.7)
# ---------------------------------------------------------------------------
class MarketCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CUTOFF = "CUTOFF"
    SETTLED = "SETTLED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, Enum):
    CART = "CART"
    PLACED = "PLACED"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class OrderLineStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    PACKED = "PACKED"
    SUBSTITUTED = "SUBSTITUTED"
    SHORTED = "SHORTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities with the full common field set carry id/created_at/updated_at/version.
# VendorSettlement is immutable and carries ONLY id + created_at (PRD §2.4).
# ---------------------------------------------------------------------------
class Farm(TypedDict):
    id: str
    name: str
    region_code: str
    commission_pct: float
    snap_authorized: bool
    payout_balance_cents: int
    settled_cycle_count: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    farm_id: str
    name: str
    category: str
    pricing_mode: str
    unit_price_cents: Optional[int]
    price_per_kg_cents: Optional[int]
    estimated_weight_kg: Optional[float]
    snap_eligible: bool
    created_at: str
    updated_at: str
    version: int


class MarketCycle(TypedDict):
    id: str
    cycle_code: str
    region_code: str
    order_open_at: str
    order_cutoff_at: str
    fulfillment_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Offering(TypedDict, total=False):
    id: str
    product_id: str
    market_cycle_id: str
    offered_qty: int
    unit_price_cents: Optional[int]
    price_per_kg_cents: Optional[int]
    reserved_qty: int
    committed_qty: int
    remaining_qty: int
    created_at: str
    updated_at: str
    version: int


class PickupHub(TypedDict):
    id: str
    name: str
    hub_type: str
    slot_capacity: int
    region_code: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    snap_balance_cents: int
    wallet_credit_cents: int
    doubleup_used_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    pickup_hub_id: str
    box_size: str
    cadence: str
    price_cap_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    market_cycle_id: str
    pickup_hub_id: str
    subscription_id: Optional[str]
    fulfillment_type: str
    delivery_slot_start: Optional[str]
    delivery_slot_end: Optional[str]
    subtotal_cents: int
    eligible_subtotal_cents: int
    snap_applied_cents: int
    doubleup_match_cents: int
    customer_owed_cents: int
    final_total_cents: Optional[int]
    refunded_snap_cents: int
    refunded_wallet_cents: int
    order_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    offering_id: str
    requested_qty: int
    allocated_qty: Optional[int]
    fulfilled_qty: Optional[int]
    actual_weight_kg: Optional[float]
    snap_eligible: bool
    estimated_line_cents: int
    final_line_cents: Optional[int]
    substitute_offering_id: Optional[str]
    price_delta_cents: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable settlement, ONLY id + created_at (PRD §2.4)
class VendorSettlement(TypedDict):
    id: str
    farm_id: str
    market_cycle_id: str
    gross_sales_cents: int
    commission_cents: int
    snap_reimbursable_cents: int
    net_payout_cents: int
    line_count: int
    created_at: str
