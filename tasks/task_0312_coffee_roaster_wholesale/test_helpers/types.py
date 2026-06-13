"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Coffee Roaster Wholesale PRD. Every entity except Payment carries
the full id / created_at / updated_at / version quartet; Payment is an append-only
event carrying only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ROASTER_STAFF = "RoasterStaff"
    SALES_REP = "SalesRep"
    WHOLESALE_BUYER = "WholesaleBuyer"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class RoastLevel(str, Enum):
    LIGHT = "LIGHT"
    MEDIUM = "MEDIUM"
    DARK = "DARK"


class ReorderStatus(str, Enum):
    OK = "OK"
    BELOW_PAR = "BELOW_PAR"


class RoastBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    ROASTING = "ROASTING"
    COOLING = "COOLING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StandingOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class OrderFulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"


class FulfillmentStatus(str, Enum):
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class SampleRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CONVERTED = "CONVERTED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


class PaymentStatus(str, Enum):
    CLEARED = "CLEARED"


# --- Entity TypedDicts (common_fields: true unless noted) ---

class PriceTier(TypedDict):
    id: str
    code: str
    discount_bps: int
    min_monthly_kg: int
    freshness_max_days: int
    archived: bool
    created_at: str
    updated_at: str
    version: int


class WholesaleAccount(TypedDict):
    id: str
    name: str
    price_tier_id: str
    net_terms_days: int
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RoastProfile(TypedDict):
    id: str
    name: str
    roast_level: str
    expected_shrink_bps: int
    charge_temp_c: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    roast_profile_id: str
    base_price_cents_per_kg: int
    freshness_window_days: int
    archived: bool
    created_at: str
    updated_at: str
    version: int


class GreenLot(TypedDict):
    id: str
    origin: str
    lot_ref: str
    received_kg: float
    on_hand_kg: float
    reserved_kg: float
    available_kg: float
    par_level_kg: float
    reorder_status: str
    created_at: str
    updated_at: str
    version: int


class RoastBatch(TypedDict):
    id: str
    green_lot_id: str
    product_id: str
    roast_profile_id: str
    planned_green_kg: float
    planned_roasted_kg: float
    actual_green_kg: Optional[float]
    actual_roasted_kg: Optional[float]
    actual_shrink_bps: Optional[int]
    roast_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RoastedLot(TypedDict):
    id: str
    roast_batch_id: str
    product_id: str
    roast_date: str
    produced_kg: float
    reserved_kg: float
    on_hand_kg: float
    available_kg: float
    created_at: str
    updated_at: str
    version: int


class StandingOrder(TypedDict):
    id: str
    account_id: str
    product_id: str
    qty_kg: float
    cadence_days: int
    next_release_at: str
    cycles_released: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    account_id: str
    standing_order_id: Optional[str]
    lines: list
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    fulfillment_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class Fulfillment(TypedDict):
    id: str
    order_id: str
    product_id: str
    roasted_lot_id: str
    allocated_kg: float
    roast_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SampleRequest(TypedDict):
    id: str
    account_id: str
    product_id: str
    sample_kg: float
    cupping_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    order_id: str
    amount_cents: int
    paid_cents: int
    amount_due_cents: int
    issued_at: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event: ONLY id + created_at (no updated_at, no version)
class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    status: str
    created_at: str
