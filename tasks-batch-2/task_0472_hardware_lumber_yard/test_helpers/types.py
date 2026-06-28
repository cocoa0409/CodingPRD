"""Domain types: entity TypedDicts, status enums, role enum.

All field names match the Hardware Lumber Yard PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class SellMode(str, Enum):
    EACH = "EACH"
    BY_FOOT = "BY_FOOT"


class ContractorAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class PricingMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    RESTOCKED = "RESTOCKED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class RentalAssetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"
    MAINTENANCE = "MAINTENANCE"


class RentalAgreementStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class ServiceStationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFFLINE = "OFFLINE"


class ServiceType(str, Enum):
    KEY_CUT = "KEY_CUT"
    PAINT_MIX = "PAINT_MIX"
    PROPANE_EXCHANGE = "PROPANE_EXCHANGE"


class ServiceTicketStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CONFIRMED = "CONFIRMED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class LoyaltyReason(str, Enum):
    ORDER_ACCRUAL = "ORDER_ACCRUAL"
    ORDER_REVERSAL = "ORDER_REVERSAL"


class UserRole(str, Enum):
    SALES_ASSOCIATE = "SalesAssociate"
    RENTAL_CLERK = "RentalClerk"
    ACCOUNTS_MANAGER = "AccountsManager"
    INVENTORY_MANAGER = "InventoryManager"
    CONTRACTOR = "Contractor"


# ─── Entity TypedDicts ──────────────────────────────────────────────────────
# Primary resources carry id + created_at + updated_at + version.

class Vendor(TypedDict):
    id: str
    name: str
    drop_ship_capable: bool
    coop_rebate_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    vendor_id: str
    sell_mode: str
    aisle: str
    bin: str
    list_price_cents: int
    price_per_foot_cents: int
    cut_fee_cents: int
    on_hand: float
    reorder_point: float
    reorder_qty: float
    reorder_needed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractorAccount(TypedDict):
    id: str
    business_name: str
    credit_limit_cents: int
    net_terms_days: int
    balance_cents: int
    committed_cents: int
    loyalty_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    contractor_account_id: Optional[str]
    fulfillment_status: str
    payment_status: str
    pricing_mode: str
    subtotal_cents: int
    loyalty_discount_cents: int
    total_cents: int
    points_accrued: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    sales_order_id: str
    product_id: str
    qty: float
    cut_count: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    sales_order_id: str
    contractor_account_id: str
    amount_cents: int
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAsset(TypedDict):
    id: str
    asset_tag: str
    category: str
    daily_rate_cents: int
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict):
    id: str
    rental_asset_id: str
    contractor_account_id: Optional[str]
    start_at: str
    due_at: str
    returned_at: Optional[str]
    rental_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceStation(TypedDict):
    id: str
    name: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict):
    id: str
    service_station_id: str
    contractor_account_id: Optional[str]
    service_type: str
    cylinder_certified: bool
    scheduled_start: str
    scheduled_end: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    vendor_id: str
    contractor_account_id: str
    description: str
    quoted_unit_cents: int
    qty: int
    revision_count: int
    confirmed_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict):
    id: str
    vendor_id: str
    lines: List[dict]
    gross_cents: int
    coop_rebate_cents: int
    net_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# LoyaltyLedger is an immutable audit record — carries ONLY id + created_at.
class LoyaltyLedger(TypedDict):
    id: str
    contractor_account_id: str
    delta_points: int
    reason: str
    sales_order_id: str
    created_at: str
