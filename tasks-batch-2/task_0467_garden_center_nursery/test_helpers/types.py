"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as the PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INVENTORY_MANAGER = "InventoryManager"
    SALES_CLERK = "SalesClerk"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class AccountType(str, Enum):
    RETAIL = "RETAIL"
    LANDSCAPER_B2B = "LANDSCAPER_B2B"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    GOLD = "GOLD"


class ProductCategory(str, Enum):
    LIVE_PLANT = "LIVE_PLANT"
    BULK_MATERIAL = "BULK_MATERIAL"
    DRY_GOOD = "DRY_GOOD"


class ProductUnit(str, Enum):
    EACH = "EACH"
    CUBIC_YARD = "CUBIC_YARD"


class LifecycleClass(str, Enum):
    ANNUAL = "ANNUAL"
    PERENNIAL = "PERENNIAL"
    NONE = "NONE"


class InventoryLotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class CareLogEntryType(str, Enum):
    WATERING = "WATERING"
    TREATMENT = "TREATMENT"
    INSPECTION = "INSPECTION"
    SHRINK_LOSS = "SHRINK_LOSS"


class PromotionScope(str, Enum):
    LIVE_PLANT = "LIVE_PLANT"
    BULK_MATERIAL = "BULK_MATERIAL"
    DRY_GOOD = "DRY_GOOD"
    ALL = "ALL"


class PromotionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class VehicleType(str, Enum):
    FLATBED = "FLATBED"
    BOX_TRUCK = "BOX_TRUCK"


class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    ON_ACCOUNT = "ON_ACCOUNT"
    PAID = "PAID"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class WarrantyResolution(str, Enum):
    REPLACEMENT = "REPLACEMENT"
    REFUND = "REFUND"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class LoyaltyEventType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REDEMPTION = "REDEMPTION"
    REVERSAL = "REVERSAL"


class LoyaltySourceKind(str, Enum):
    ORDER = "ORDER"
    WARRANTY_CLAIM = "WARRANTY_CLAIM"


# ---------------------------------------------------------------------------
# Entity TypedDicts — versioned aggregates carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class Nursery(TypedDict):
    id: str
    name: str
    site_hardiness_zone: int
    loyalty_accrual_per_dollar: int
    gold_tier_threshold_points: int
    shrink_writeoff_zone_grace: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    nursery_id: str
    account_type: str
    display_name: str
    ship_to_hardiness_zone: int
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    lifetime_points: int
    loyalty_tier: str
    points_balance: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    nursery_id: str
    sku: str
    name: str
    category: str
    unit: str
    lifecycle_class: str
    hardiness_min_zone: int
    hardiness_max_zone: int
    unit_price_cents: int
    warranty_days: int
    warranty_pct: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    product_id: str
    nursery_id: str
    special_order_id: Optional[str]
    received_qty: int
    unit_cost_cents: int
    qty_on_hand: int
    reserved_qty: int
    shrink_qty: int
    sold_qty: int
    provisional_shrink_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonalPromotion(TypedDict):
    id: str
    nursery_id: str
    name: str
    category_scope: str
    discount_pct: int
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    nursery_id: str
    label: str
    vehicle_type: str
    capacity_cubic_yards: int
    turnaround_minutes: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    account_id: str
    nursery_id: str
    gross_total_cents: int
    promo_discount_cents: int
    redemption_cents: int
    net_total_cents: int
    requested_redeem_points: int
    fulfillment_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    qty: int
    unit_price_cents: int
    line_discount_cents: int
    line_net_cents: int
    allocated_lot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    account_id: str
    nursery_id: str
    product_id: str
    requested_qty: int
    quoted_unit_cost_cents: int
    deposit_cents: int
    received_lot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    order_id: str
    vehicle_id: str
    nursery_id: str
    window_start: str
    window_end: str
    bulk_volume_cubic_yards: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    order_line_id: str
    nursery_id: str
    claim_qty: int
    filed_at: str
    resolution: str
    payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only ledger records — carry ONLY id + created_at (no updated_at/version)
# ---------------------------------------------------------------------------
class CareLogEntry(TypedDict):
    id: str
    inventory_lot_id: str
    entry_type: str
    qty_lost: int
    note: str
    logged_at: str
    created_at: str


class LoyaltyEvent(TypedDict):
    id: str
    account_id: str
    event_type: str
    points_delta: int
    source_kind: str
    source_ref_id: str
    recorded_at: str
    created_at: str
