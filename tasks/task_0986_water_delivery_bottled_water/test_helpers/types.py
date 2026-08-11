"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    DISPATCHER = "Dispatcher"
    DRIVER = "Driver"
    BILLING_ADMIN = "BillingAdmin"
    CUSTOMER_SELF = "CustomerSelf"


class AccountType(str, Enum):
    OFFICE = "OFFICE"
    HOME = "HOME"


class ServiceMode(str, Enum):
    AUTO = "AUTO"
    WILL_CALL = "WILL_CALL"


class PricingTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    PLANNED = "PLANNED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"
    SKIPPED = "SKIPPED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EntryKind(str, Enum):
    DELIVER_FULL = "DELIVER_FULL"
    PICKUP_EMPTY = "PICKUP_EMPTY"
    MARK_SHORTAGE = "MARK_SHORTAGE"
    ADJUSTMENT = "ADJUSTMENT"
    RETURN_FULL = "RETURN_FULL"
    EXCHANGE = "EXCHANGE"


class CoolerModel(str, Enum):
    COUNTERTOP = "COUNTERTOP"
    FREESTANDING = "FREESTANDING"
    BOTTOM_LOAD = "BOTTOM_LOAD"
    FILTRATION_POE = "FILTRATION_POE"


class RentalStatus(str, Enum):
    PENDING_INSTALL = "PENDING_INSTALL"
    INSTALLED = "INSTALLED"
    SUSPENDED = "SUSPENDED"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"


class AddonKind(str, Enum):
    COFFEE = "COFFEE"
    FILTRATION = "FILTRATION"
    CUPS = "CUPS"
    SANITIZATION = "SANITIZATION"


class Cadence(str, Enum):
    RECURRING = "RECURRING"
    ONE_TIME = "ONE_TIME"


class AddonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    CHECK = "CHECK"
    CREDIT_MEMO = "CREDIT_MEMO"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class OrderKind(str, Enum):
    DELIVERY = "DELIVERY"
    COOLER_INSTALL = "COOLER_INSTALL"
    COOLER_RETURN = "COOLER_RETURN"
    PICKUP_ONLY = "PICKUP_ONLY"
    EXCHANGE_ONLY = "EXCHANGE_ONLY"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class CreditStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class Customer(TypedDict, total=False):
    id: str
    account_type: str
    business_name: str
    billing_email: str
    service_address: str
    delivery_zone_id: str
    service_mode: str
    par_level_bottles: int
    pricing_tier: str
    account_status: str
    outstanding_balance_cents: int
    bottles_on_site: int
    deposit_liability_cents: int
    overdue_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryZone(TypedDict, total=False):
    id: str
    code: str
    name: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    zone_id: str
    service_date: str
    driver_name: str
    truck_capacity_bottles: int
    committed_bottles: int
    route_status: str
    created_at: str
    updated_at: str
    version: int


class Stop(TypedDict, total=False):
    id: str
    route_id: str
    customer_id: str
    sequence_index: int
    planned_bottles: int
    planned_empties_pickup: int
    stop_status: str
    actual_bottles_delivered: int
    actual_empties_collected: int
    shortage_count: int
    skip_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BottleCustodyLedger(TypedDict, total=False):
    # Append-only ledger: carries ONLY id + created_at (no updated_at, no version).
    id: str
    customer_ref: str
    stop_id: Optional[str]
    entry_kind: str
    quantity: int
    occurred_at: str
    created_at: str


class CoolerRental(TypedDict, total=False):
    id: str
    customer_id: str
    cooler_model: str
    monthly_rent_cents: int
    deposit_cents: int
    rental_status: str
    installed_at: Optional[str]
    returned_at: Optional[str]
    accrued_rent_cents: int
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict, total=False):
    id: str
    customer_id: str
    addon_kind: str
    quantity: int
    unit_price_cents: int
    cadence: str
    addon_status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    customer_id: str
    billing_period_start: str
    billing_period_end: str
    subtotal_water_cents: int
    subtotal_addon_cents: int
    subtotal_rent_cents: int
    shortage_charge_cents: int
    deposit_credit_cents: int
    total_due_cents: int
    balance_due_cents: int
    invoice_status: str
    due_date: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    payment_status: str
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    customer_id: str
    order_kind: str
    requested_date: str
    quantity_bottles: int
    order_status: str
    linked_stop_id: Optional[str]
    linked_rental_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PricingConfig(TypedDict, total=False):
    id: str
    effective_from: str
    bottle_deposit_cents: int
    bottle_shortage_fee_cents: int
    standard_per_bottle_cents: int
    silver_per_bottle_cents: int
    gold_per_bottle_cents: int
    silver_volume_threshold: int
    gold_volume_threshold: int
    late_fee_flat_cents: int
    created_at: str
    updated_at: str
    version: int


class SkipCredit(TypedDict, total=False):
    id: str
    customer_id: str
    stop_id: str
    credit_cents: int
    credit_status: str
    expires_at: str
    notified_before_cutoff: bool
    created_at: str
    updated_at: str
    version: int
