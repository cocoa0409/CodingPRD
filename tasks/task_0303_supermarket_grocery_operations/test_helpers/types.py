"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this system carries the full set of common properties
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    STORE_MANAGER = "StoreManager"
    RECEIVING_CLERK = "ReceivingClerk"
    PRICE_MANAGER = "PriceManager"
    CASHIER = "Cashier"
    INVENTORY_AUDITOR = "InventoryAuditor"
    LOYALTY_MEMBER = "LoyaltyMember"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class InventoryLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    PULLED = "PULLED"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVING = "RECEIVING"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class ShipmentLineStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    SHORT = "SHORT"


class PricePlanStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PromotionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PromoType(str, Enum):
    PERCENT_OFF = "PERCENT_OFF"
    BOGO = "BOGO"
    FIXED_OFF = "FIXED_OFF"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MemberTier(str, Enum):
    BASIC = "BASIC"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ClippedCouponStatus(str, Enum):
    CLIPPED = "CLIPPED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class TenderStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class CycleCountStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class EodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every entity carries common fields (PRD §2.4)
# ---------------------------------------------------------------------------
class Department(TypedDict):
    id: str
    code: str
    name: str
    shrink_alert_bps: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    department_id: str
    sku: Optional[str]
    plu: Optional[str]
    name: str
    sell_by_weight: bool
    unit_price_cents: int
    is_perishable: bool
    reorder_point_qty: int
    on_hand_qty: int
    on_hand_value_cents: int
    reorder_flagged: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    product_id: str
    shipment_id: Optional[str]
    received_qty: int
    remaining_qty: int
    unit_cost_cents: int
    expiration_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    vendor_name: str
    reference_code: str
    expected_total_cents: int
    received_total_cents: int
    variance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShipmentLine(TypedDict):
    id: str
    shipment_id: str
    product_id: str
    ordered_qty: int
    accepted_qty: int
    unit_cost_cents: int
    expiration_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PricePlan(TypedDict):
    id: str
    product_id: str
    ad_price_cents: int
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    product_id: str
    promo_type: str
    percent_off_bps: Optional[int]
    fixed_off_cents: Optional[int]
    min_qty: int
    stackable: bool
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyMember(TypedDict):
    id: str
    email: str
    full_name: str
    points_balance: int
    tier: str
    lifetime_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DigitalCoupon(TypedDict):
    id: str
    code: str
    product_id: str
    discount_cents: int
    min_spend_cents: int
    stackable: bool
    effective_start: str
    effective_end: str
    created_at: str
    updated_at: str
    version: int


class ClippedCoupon(TypedDict):
    id: str
    member_id: str
    coupon_id: str
    redeemed_in_sale_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesTransaction(TypedDict):
    id: str
    member_id: Optional[str]
    clipped_coupon_id: Optional[str]
    subtotal_cents: int
    coupon_discount_cents: int
    total_cents: int
    cogs_cents: int
    points_earned: int
    tender_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class SaleLineItem(TypedDict):
    id: str
    sale_id: str
    product_id: str
    quantity: Optional[int]
    weight_milli: Optional[int]
    unit_price_applied_cents: int
    extended_price_cents: int
    promo_id_applied: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CycleCount(TypedDict):
    id: str
    department_id: str
    product_id: str
    counted_qty: int
    book_qty_snapshot: int
    variance_qty: int
    shrink_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EndOfDayReconciliation(TypedDict):
    id: str
    department_id: str
    business_date: str
    opening_value_cents: int
    cogs_total_cents: int
    shrink_total_cents: int
    sales_total_cents: int
    closing_value_cents: int
    shrink_bps: int
    shrink_alert: bool
    status: str
    created_at: str
    updated_at: str
    version: int
