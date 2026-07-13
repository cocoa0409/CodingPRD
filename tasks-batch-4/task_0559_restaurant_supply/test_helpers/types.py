"""Domain types: entity TypedDicts, status enums, role enum.

All figures reference PRD terminology only.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    BUYER = "Buyer"
    WAREHOUSE_OPS = "WarehouseOps"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TaxExemptStatus(str, Enum):
    NONE = "NONE"
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"


class CreditTerms(str, Enum):
    PREPAID = "PREPAID"
    NET_15 = "NET_15"
    NET_30 = "NET_30"


class CertStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ProductCategory(str, Enum):
    SMALLWARE = "SMALLWARE"
    EQUIPMENT = "EQUIPMENT"
    CONSUMABLE = "CONSUMABLE"


class FulfillmentType(str, Enum):
    STOCK = "STOCK"
    DROPSHIP = "DROPSHIP"


class FreightType(str, Enum):
    PARCEL = "PARCEL"
    LTL = "LTL"


class OrderLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    INVOICED = "INVOICED"
    PAID = "PAID"


class PricingTier(str, Enum):
    EACH = "EACH"
    CASE = "CASE"
    PALLET = "PALLET"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    PARTIAL = "PARTIAL"
    BACKORDERED = "BACKORDERED"
    DROPSHIP_PENDING = "DROPSHIP_PENDING"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ShippingMode(str, Enum):
    PARCEL = "PARCEL"
    LTL = "LTL"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RECEIVED = "RECEIVED"
    REFUNDED = "REFUNDED"
    REJECTED = "REJECTED"


class ReturnLineStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"


class ReturnCondition(str, Enum):
    SEALED = "SEALED"
    OPENED = "OPENED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class InstallJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (all entities carry the full common field set) ---

class Account(TypedDict):
    id: str
    business_name: str
    credit_terms: str
    credit_limit_cents: int
    tax_rate: float
    outstanding_cents: int
    credit_available_cents: int
    tax_exempt_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxExemptCertificate(TypedDict):
    id: str
    account_id: str
    cert_number: str
    state_code: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    taxable: bool
    unit_price_cents: int
    case_qty: int
    case_price_cents: int
    pallet_case_qty: int
    pallet_price_cents: int
    weight_lbs_per_unit: int
    fulfillment_type: str
    freight_type: str
    lead_time_days: int
    on_hand_qty: int
    par_level: int
    reorder_point: int
    needs_reorder: bool
    reorder_suggested_qty: int
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict):
    id: str
    account_id: str
    confirmed_at: Optional[str]
    merchandise_subtotal_cents: int
    tax_cents: int
    freight_cents: int
    total_cents: int
    lifecycle_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    quantity: int
    pricing_tier: str
    line_subtotal_cents: int
    allocated_qty: int
    backordered_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    carrier: str
    liftgate_required: bool
    shipping_mode: str
    freight_quote_cents: int
    final_freight_cents: Optional[int]
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict):
    id: str
    order_id: str
    reason: str
    restock_fee_cents: int
    refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnLine(TypedDict):
    id: str
    return_id: str
    product_id: str
    quantity: int
    condition: str
    line_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dock(TypedDict):
    id: str
    name: str
    location: str
    created_at: str
    updated_at: str
    version: int


class DeliveryAppointment(TypedDict):
    id: str
    order_id: str
    dock_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallCrew(TypedDict):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict):
    id: str
    order_id: str
    crew_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
