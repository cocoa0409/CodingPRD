"""Domain types: entity TypedDicts, status enums, and the role enum.

All types reflect the PRD contract for the Sewing-Machine & Vacuum Sales/Service API.
Every persisted resource carries id, created_at, updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    SALES_ASSOCIATE = "SalesAssociate"
    SERVICE_TECH = "ServiceTech"
    STORE_MANAGER = "StoreManager"
    CUSTOMER = "Customer"


# ------------------------------------------------------------------------- enums
class ProductCategory(str, Enum):
    SEWING_MACHINE = "SEWING_MACHINE"
    VACUUM = "VACUUM"
    PART = "PART"
    ACCESSORY = "ACCESSORY"


class RecallStatus(str, Enum):
    NONE = "NONE"
    RECALLED = "RECALLED"


class InventoryStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    SCRAPPED = "SCRAPPED"


class Condition(str, Enum):
    NEW = "NEW"
    REFURBISHED = "REFURBISHED"
    USED_TRADE_IN = "USED_TRADE_IN"


class TradeInCondition(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class SalesOrderStatus(str, Enum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RepairStatus(str, Enum):
    INTAKE = "INTAKE"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    IN_REPAIR = "IN_REPAIR"
    READY = "READY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RentalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class MachineType(str, Enum):
    SEWING = "SEWING"
    VACUUM = "VACUUM"


class ClassSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    ATTENDED = "ATTENDED"
    CANCELLED = "CANCELLED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PRO = "PRO"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------- entities
# Every entity carries id, created_at, updated_at, version (PRD §2.4).
class Product(TypedDict):
    id: str
    model_name: str
    category: str
    brand: str
    msrp_cents: int
    warranty_months: int
    recall_status: str
    recall_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    store_credit_cents: int
    lifetime_spend_cents: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    product_id: str
    serial_number: Optional[str]
    condition: str
    acquisition_cost_cents: int
    list_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    customer_id: str
    inventory_item_id: str
    sale_price_cents: int
    trade_in_model: Optional[str]
    trade_in_condition: Optional[str]
    trade_in_estimate_cents: int
    trade_in_final_cents: Optional[int]
    loyalty_discount_cents: int
    tax_cents: int
    credit_applied_cents: int
    total_due_cents: int
    warranty_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairTicket(TypedDict):
    id: str
    customer_id: str
    product_id: str
    is_warranty: bool
    diagnosis: Optional[str]
    labor_hours: Optional[float]
    labor_estimate_cents: int
    parts_cost_cents: int
    final_invoice_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict):
    id: str
    customer_id: str
    inventory_item_id: str
    start_at: str
    due_at: str
    daily_rate_cents: int
    deposit_cents: int
    returned_at: Optional[str]
    rental_days: int
    late_fee_cents: int
    total_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    title: str
    machine_type: str
    start_at: str
    end_at: str
    capacity: int
    fee_cents: int
    enrolled_count: int
    waitlist_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassEnrollment(TypedDict):
    id: str
    class_session_id: str
    customer_id: str
    fee_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TuneUpSubscription(TypedDict):
    id: str
    customer_id: str
    plan_tier: str
    monthly_fee_cents: int
    tune_ups_included: int
    tune_ups_used: int
    current_period_start: str
    current_period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    quantity: int
    unit_price_cents: int
    deposit_cents: int
    balance_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
