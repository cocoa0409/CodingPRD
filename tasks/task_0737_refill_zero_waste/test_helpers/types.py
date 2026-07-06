"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Refill & Zero-Waste Store PRD's resources. Mutable resources carry
id/created_at/updated_at/version; the append-only event log (WalletLedger)
carries only id and created_at (it is never modified after it is written).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    MEMBER = "Member"
    STORE_CLERK = "StoreClerk"
    INVENTORY_MANAGER = "InventoryManager"


# ─── Status / enum vocabularies ───────────────────────────────────────────

class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"


class ProductCategory(str, Enum):
    GRAINS = "GRAINS"
    LIQUIDS = "LIQUIDS"
    SPICES = "SPICES"
    CLEANING = "CLEANING"


class StationStatus(str, Enum):
    OPEN = "OPEN"
    MAINTENANCE = "MAINTENANCE"


class BinStatus(str, Enum):
    OPEN = "OPEN"
    LOW = "LOW"
    QUARANTINED = "QUARANTINED"


class ContainerType(str, Enum):
    GLASS_500 = "GLASS_500"
    GLASS_1000 = "GLASS_1000"
    BYO = "BYO"


class AllergenHold(str, Enum):
    NONE = "NONE"
    PEANUT = "PEANUT"
    GLUTEN = "GLUTEN"
    DAIRY = "DAIRY"


class ContainerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ISSUED = "ISSUED"
    IN_USE = "IN_USE"
    RETURNED = "RETURNED"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class FulfillmentChannel(str, Enum):
    IN_STORE = "IN_STORE"
    DELIVERY = "DELIVERY"


class OrderFulfillmentStatus(str, Enum):
    CART = "CART"
    FILLING = "FILLING"
    FILLED = "FILLED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    CAPTURED = "CAPTURED"


class PricingStage(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    VOIDED = "VOIDED"


class RestockTaskStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class WalletLedgerEntryType(str, Enum):
    DEPOSIT_COMMIT = "DEPOSIT_COMMIT"
    DEPOSIT_REFUND = "DEPOSIT_REFUND"
    LOYALTY_ACCRUAL = "LOYALTY_ACCRUAL"
    LOYALTY_REDEEM = "LOYALTY_REDEEM"


class WalletLedgerSourceKind(str, Enum):
    ORDER = "ORDER"
    CONTAINER = "CONTAINER"
    DELIVERY = "DELIVERY"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# common_fields: true — id + created_at + updated_at + version

class Member(TypedDict):
    id: str
    email: str
    full_name: str
    membership_tier: str
    wallet_balance_cents: int
    deposit_liability_cents: int
    loyalty_points_balance: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    name: str
    category: str
    unit_price_cents_per_100g: int
    bulk_tier_threshold_g: int
    bulk_tier_price_cents_per_100g: int
    allergen_tags: List[str]
    taxable: bool
    created_at: str
    updated_at: str
    version: int


class RefillStation(TypedDict):
    id: str
    name: str
    station_status: str
    created_at: str
    updated_at: str
    version: int


class BulkBin(TypedDict):
    id: str
    product_id: str
    station_id: str
    capacity_g: int
    reorder_threshold_g: int
    on_hand_g: int
    last_recount_g: int
    last_recount_at: str
    last_shrink_g: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict):
    id: str
    member_id: Optional[str]
    container_type: str
    declared_tare_g: int
    measured_tare_g: Optional[int]
    deposit_cents: int
    allergen_hold: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    member_id: str
    station_id: str
    fulfillment_channel: str
    fill_window_start_at: str
    fill_window_end_at: str
    fulfillment_status: str
    payment_status: str
    subtotal_cents: int
    discount_cents: int
    deposit_total_cents: int
    tax_cents: int
    total_cents: int
    loyalty_points_earned: int
    created_at: str
    updated_at: str
    version: int


class RefillLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    container_id: str
    bin_id: Optional[str]
    declared_tare_g: int
    estimated_gross_g: int
    gross_weight_g: Optional[int]
    net_weight_g: int
    line_price_cents: int
    pricing_stage: str
    created_at: str
    updated_at: str
    version: int


class RestockTask(TypedDict):
    id: str
    bin_id: str
    requested_fill_g: int
    restocked_g: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    product_id: str
    station_id: str
    target_net_g: int
    interval_days: int
    next_run_at: str
    last_run_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryVehicle(TypedDict):
    id: str
    plate: str
    capacity_orders: int
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    order_id: str
    vehicle_id: str
    member_id: str
    window_start_at: str
    window_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event log, only id + created_at
class WalletLedgerEntry(TypedDict):
    id: str
    member_id: str
    entry_type: str
    wallet_delta_cents: int
    liability_delta_cents: int
    points_delta: int
    source_kind: str
    source_id: Optional[str]
    memo: Optional[str]
    created_at: str
