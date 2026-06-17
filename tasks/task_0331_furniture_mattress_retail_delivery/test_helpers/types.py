"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model. Money is always integer cents.
The Payment resource is immutable and carries only id + created_at (no
updated_at, no version), per PRD Section 2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD Section 2.1) ──────────────────────────────────────────
class UserRole(str, Enum):
    SALES_ASSOCIATE = "SalesAssociate"
    STORE_MANAGER = "StoreManager"
    DELIVERY_DISPATCHER = "DeliveryDispatcher"
    CUSTOMER = "Customer"


# ─── Status enums (PRD Section 2.6, 3.x) ──────────────────────────────────
class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    FINANCED = "FINANCED"
    PAID_IN_FULL = "PAID_IN_FULL"


class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class FinancingPlanStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    PAID_OFF = "PAID_OFF"
    DECLINED = "DECLINED"
    DEFAULTED = "DEFAULTED"


class PlanType(str, Enum):
    INSTALLMENT = "INSTALLMENT"
    LEASE_TO_OWN = "LEASE_TO_OWN"


class DeliveryRouteStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"


class DeliveryStopStatus(str, Enum):
    BOOKED = "BOOKED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceTier(str, Enum):
    THRESHOLD = "THRESHOLD"
    WHITE_GLOVE = "WHITE_GLOVE"


class ProductCategory(str, Enum):
    SOFA = "SOFA"
    SECTIONAL = "SECTIONAL"
    MATTRESS = "MATTRESS"
    BED_FRAME = "BED_FRAME"
    TABLE = "TABLE"


class ProtectionTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class ProtectionPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ReturnReason(str, Enum):
    DAMAGED = "DAMAGED"
    DEFECTIVE = "DEFECTIVE"
    CHANGED_MIND = "CHANGED_MIND"


class ReturnRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REFUNDED = "REFUNDED"
    REJECTED = "REJECTED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# All "common_fields: true" entities carry id + created_at + updated_at + version.
# Payment is the sole "common_fields: false" entity: id + created_at only.

class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    credit_score: int
    monthly_income_cents: int
    existing_monthly_obligations_cents: int
    open_financing_count: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    base_price_cents: int
    available_fabrics: list
    available_sizes: list
    is_special_order: bool
    lead_days: int
    protection_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    sales_associate_user_id: str
    payment_status: str
    fulfillment_status: str
    merchandise_subtotal_cents: int
    service_total_cents: int
    order_total_cents: int
    amount_refunded_cents: int
    delivery_tier: str
    earliest_schedulable_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    fabric_code: str
    size_code: str
    quantity: int
    add_assembly: bool
    add_haul_away: bool
    unit_config_price_cents: int
    line_total_cents: int
    addon_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingPlan(TypedDict):
    id: str
    order_id: str
    customer_id: str
    plan_type: str
    term_months: int
    financed_principal_cents: int
    monthly_payment_cents: int
    total_of_payments_cents: int
    paid_to_date_cents: int
    payoff_balance_cents: int
    payments_made_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Payment is append-only / immutable: NO updated_at, NO version.
class Payment(TypedDict):
    id: str
    financing_plan_id: str
    amount_cents: int
    applied_period_index: int
    created_at: str


class DeliveryRoute(TypedDict):
    id: str
    region_code: str
    service_date: str
    shift_start_minute: int
    shift_end_minute: int
    capacity_units: int
    committed_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryStop(TypedDict):
    id: str
    route_id: str
    order_id: str
    window_start_minute: int
    window_end_minute: int
    service_tier: str
    unit_load: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProtectionPlan(TypedDict):
    id: str
    order_line_id: str
    tier: str
    coverage_years: int
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict):
    id: str
    order_line_id: str
    order_id: str
    reason: str
    restocking_fee_cents: int
    refund_amount_cents: int
    filed_on: str
    status: str
    created_at: str
    updated_at: str
    version: int
