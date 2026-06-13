"""Domain types: entity TypedDicts, status enums, role enum.

Field names and status values match the Garage Door Install & Repair PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — exactly four roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    SERVICE_MANAGER = "ServiceManager"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CustomerFinancingStanding(str, Enum):
    GOOD = "GOOD"
    BLOCKED = "BLOCKED"


class TechnicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LEAVE = "ON_LEAVE"


class TechnicianSkillLevel(str, Enum):
    APPRENTICE = "APPRENTICE"
    CERTIFIED = "CERTIFIED"
    MASTER = "MASTER"


class PartCategory(str, Enum):
    SPRING = "SPRING"
    CABLE = "CABLE"
    PANEL = "PANEL"
    ROLLER = "ROLLER"
    SENSOR = "SENSOR"


class QuoteType(str, Enum):
    SERVICE_CALL = "SERVICE_CALL"
    INSTALL = "INSTALL"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class QuoteLineItemKind(str, Enum):
    PART = "PART"
    DOOR = "DOOR"
    OPENER = "OPENER"
    LABOR = "LABOR"


class JobDispatchStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class JobBillingStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    PAID = "PAID"


class PartReservationStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class WarrantyPlanStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class FinancingApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"


class CallbackStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    ON_SITE = "ON_SITE"
    RESOLVED = "RESOLVED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Resources carrying id + created_at + updated_at + version unless noted.
# DoorModel and OpenerModel are immutable reference data: id + created_at only.
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    service_address: str
    time_zone: str
    financing_standing: str
    active_warranty_count: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    display_name: str
    skill_level: str
    certified_for_install: bool
    status: str
    booked_minutes: int
    jobs_completed_count: int
    callback_rate_provisional: float
    callback_rate_settled: float
    created_at: str
    updated_at: str
    version: int


# Immutable reference data — id + created_at only (no updated_at, no version)
class DoorModel(TypedDict):
    id: str
    sku: str
    name: str
    width_in: int
    height_in: int
    list_price_cents: int
    install_labor_minutes: int
    requires_lift: bool
    created_at: str


# Immutable reference data — id + created_at only (no updated_at, no version)
class OpenerModel(TypedDict):
    id: str
    sku: str
    name: str
    horsepower: float
    list_price_cents: int
    install_labor_minutes: int
    created_at: str


class Part(TypedDict):
    id: str
    sku: str
    category: str
    unit_price_cents: int
    markup_pct: float
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict):
    id: str
    name: str
    concurrent_capacity: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    customer_id: str
    quote_type: str
    door_model_id: Optional[str]
    opener_model_id: Optional[str]
    status: str
    revision: int
    service_call_fee_cents: int
    estimate_total_cents: int
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict):
    id: str
    quote_id: str
    item_kind: str
    item_ref_id: Optional[str]
    qty: int
    unit_price_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict):
    id: str
    quote_id: str
    customer_id: str
    technician_id: Optional[str]
    equipment_unit_id: Optional[str]
    dispatch_status: str
    billing_status: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    is_emergency: bool
    safety_inspection_passed: bool
    completed_by_user_id: Optional[str]
    final_total_cents: int
    emergency_surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class PartReservation(TypedDict):
    id: str
    job_id: str
    part_id: str
    qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyPlan(TypedDict):
    id: str
    job_id: str
    customer_id: str
    tune_ups_included: int
    tune_ups_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict):
    id: str
    customer_id: str
    quote_id: str
    principal_cents: int
    term_months: int
    status: str
    monthly_payment_cents: int
    created_at: str
    updated_at: str
    version: int


class Callback(TypedDict):
    id: str
    job_id: str
    reason: str
    status: str
    fault_confirmed: bool
    created_at: str
    updated_at: str
    version: int
