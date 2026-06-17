"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD exactly. Entities that the PRD lists as carrying the
standard system-managed fields (id, created_at, updated_at, version) include them;
the two immutable association records (Fitment, CrossReference) carry only id and
created_at per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict


# ─── Role enum (PRD §2.1) ──────────────────────────────────────────────────
class UserRole(str, Enum):
    COUNTER_CLERK = "CounterClerk"
    WHOLESALE_REP = "WholesaleRep"
    INVENTORY_MANAGER = "InventoryManager"
    WARRANTY_ADMIN = "WarrantyAdmin"


# ─── Status enums ──────────────────────────────────────────────────────────
class PartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"


class AccountType(str, Enum):
    RETAIL = "RETAIL"
    WHOLESALE = "WHOLESALE"


class Channel(str, Enum):
    COUNTER = "COUNTER"
    WHOLESALE = "WHOLESALE"


class FulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class CoreReturnStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class WarrantyResolution(str, Enum):
    REPLACE = "REPLACE"
    REFUND = "REFUND"


class ReorderStatus(str, Enum):
    SUGGESTED = "SUGGESTED"
    ORDERED = "ORDERED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class FitmentPosition(str, Enum):
    FRONT = "FRONT"
    REAR = "REAR"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    UNIVERSAL = "UNIVERSAL"


class CrossReferenceRelation(str, Enum):
    SUPERSEDES = "SUPERSEDES"
    EQUIVALENT = "EQUIVALENT"
    OE_TO_AFTERMARKET = "OE_TO_AFTERMARKET"


class DeliveryRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (common_fields: true) ───────────────────────────────
class Part(TypedDict):
    id: str
    sku: str
    description: str
    list_price_cents: int
    cost_cents: int
    core_charge_cents: int
    is_rebuildable: bool
    warranty_days: int
    stockable: bool
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    reorder_point: int
    reorder_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    year: int
    make: str
    model: str
    engine: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    name: str
    account_type: str
    price_tier_id: str
    credit_limit_cents: int
    ar_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceTier(TypedDict):
    id: str
    name: str
    discount_pct: float
    core_discount_pct: float
    min_margin_pct: float
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    account_id: str
    channel: str
    fulfillment_status: str
    settlement_status: str
    merchandise_subtotal_cents: int
    core_subtotal_cents: int
    order_total_cents: int
    hotshot_requested: bool
    hotshot_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    part_id: str
    price_tier_id: str
    qty: int
    is_special_order: bool
    unit_merch_price_cents: int
    unit_core_price_cents: int
    line_merch_total_cents: int
    line_core_total_cents: int
    cores_outstanding: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoreReturn(TypedDict):
    id: str
    order_line_id: str
    qty: int
    refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    order_line_id: str
    qty: int
    reason: str
    resolution: str
    credit_cents: int
    restock_defective: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReorderRequest(TypedDict):
    id: str
    part_id: str
    qty_ordered: int
    qty_received: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    name: str
    turnaround_min: int
    created_at: str
    updated_at: str
    version: int


class Bay(TypedDict):
    id: str
    code: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRun(TypedDict):
    id: str
    order_id: str
    driver_id: str
    bay_id: str
    window_start_min: int
    window_end_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Immutable association records (common_fields: false) ──────────────────
# PRD §2.4: Fitment and CrossReference carry ONLY id and created_at.
class Fitment(TypedDict):
    id: str
    part_id: str
    vehicle_id: str
    position: str
    notes: str
    created_at: str


class CrossReference(TypedDict):
    id: str
    part_id: str
    interchange_part_id: str
    relation: str
    created_at: str
