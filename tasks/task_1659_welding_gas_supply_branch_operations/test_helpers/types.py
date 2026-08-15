"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    COUNTER_REP = "CounterRep"
    BRANCH_MANAGER = "BranchManager"
    ROUTE_DRIVER = "RouteDriver"
    TRAINER = "Trainer"
    SERVICE_TECH = "ServiceTech"


class CustomerTerms(str, Enum):
    CASH = "CASH"
    NET30 = "NET30"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    SUSPENDED = "SUSPENDED"


class PriceBookScope(str, Enum):
    RETAIL = "RETAIL"
    CONTRACT = "CONTRACT"


class PriceBookStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ProductCategory(str, Enum):
    HARDGOOD = "HARDGOOD"
    GAS = "GAS"
    SPECIALTY_GAS = "SPECIALTY_GAS"


class GasGrade(str, Enum):
    OXYGEN = "OXYGEN"
    ACETYLENE = "ACETYLENE"
    ARGON = "ARGON"
    AR_CO2_7525 = "AR_CO2_7525"
    NITROGEN = "NITROGEN"


class CylinderSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class CylinderStatus(str, Enum):
    FULL = "FULL"
    EMPTY = "EMPTY"
    OUT = "OUT"
    RETIRED = "RETIRED"


class MachineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"


class RentalItemType(str, Enum):
    CYLINDER = "CYLINDER"
    MACHINE = "MACHINE"


class RatePlan(str, Enum):
    DEMURRAGE = "DEMURRAGE"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class RentalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class OrderType(str, Enum):
    RETAIL = "RETAIL"
    EXCHANGE = "EXCHANGE"
    SPECIAL_MIX = "SPECIAL_MIX"


class Fulfillment(str, Enum):
    WILL_CALL = "WILL_CALL"
    ROUTE = "ROUTE"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    STAGED = "STAGED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class InvoiceSource(str, Enum):
    ORDER = "ORDER"
    RENTAL_CYCLE = "RENTAL_CYCLE"
    RENTAL_CLOSE = "RENTAL_CLOSE"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class Room(str, Enum):
    ROOM_A = "ROOM_A"
    ROOM_B = "ROOM_B"


class ClassStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class RepairStatus(str, Enum):
    INTAKE = "INTAKE"
    DIAGNOSING = "DIAGNOSING"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    IN_REPAIR = "IN_REPAIR"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries id/created_at/updated_at/version
# (PRD §2.5)
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    account_no: str
    name: str
    terms: str
    status: str
    credit_limit_cents: int
    price_book_id: Optional[str]
    posted_exposure_cents: int
    accrued_rental_cents: int
    projected_exposure_cents: int
    outstanding_balance_cents: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class PriceBook(TypedDict, total=False):
    id: str
    name: str
    scope: str
    customer_id: Optional[str]
    effective_from: str
    effective_to: str
    default_discount_pct: float
    volume_tiers: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    gas_grade: Optional[str]
    retail_price_cents: int
    hazmat: bool
    stock_on_hand: int
    reorder_point: int
    lead_time_days: int
    needs_reorder: bool
    created_at: str
    updated_at: str
    version: int


class CylinderAsset(TypedDict, total=False):
    id: str
    serial_no: str
    gas_grade: str
    size: str
    status: str
    holder_customer_id: Optional[str]
    rental_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict, total=False):
    id: str
    model: str
    serial_no: str
    daily_rate_cents: int
    weekly_rate_cents: int
    monthly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    item_type: str
    cylinder_asset_id: Optional[str]
    machine_id: Optional[str]
    rate_plan: str
    start_date: str
    scheduled_end_date: Optional[str]
    grace_days: int
    status: str
    billed_through_date: Optional[str]
    lifetime_billed_cents: int
    waived_cents: int
    accrued_unbilled_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    route_date: str
    truck_capacity_units: int
    reserved_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    order_type: str
    fulfillment: str
    route_id: Optional[str]
    lines: List[dict]
    available_date: Optional[str]
    units: int
    fulfillment_status: str
    payment_status: str
    subtotal_cents: int
    delivery_fee_cents: int
    hazmat_fee_cents: int
    total_cents: int
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    customer_id: str
    source: str
    order_id: Optional[str]
    amount_cents: int
    paid_cents: int
    status: str
    issued_at: str
    due_at: str
    created_at: str
    updated_at: str
    version: int


class TrainingClass(TypedDict, total=False):
    id: str
    title: str
    room: str
    start_at: str
    end_at: str
    capacity: int
    price_cents: int
    seats_booked: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict, total=False):
    id: str
    class_id: str
    customer_id: str
    attendee_name: str
    status: str
    cert_code: Optional[str]
    cert_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairTicket(TypedDict, total=False):
    id: str
    customer_id: str
    machine_desc: str
    issue_desc: str
    status: str
    quote_cents: Optional[int]
    revision_no: int
    charged_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
