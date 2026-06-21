"""Domain types: entity TypedDicts, status enums, role enum (Pool & Spa Maintenance API)."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    ROUTE_MANAGER = "RouteManager"
    FIELD_TECHNICIAN = "FieldTechnician"
    CUSTOMER = "Customer"


# --- Status enums ---
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BillingTerms(str, Enum):
    PER_VISIT = "PER_VISIT"
    MONTHLY_ACCRUAL = "MONTHLY_ACCRUAL"


class WaterType(str, Enum):
    CHLORINE = "CHLORINE"
    SALTWATER = "SALTWATER"
    BROMINE_SPA = "BROMINE_SPA"


class PoolStatus(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    GREEN_RECOVERY = "GREEN_RECOVERY"
    WINTERIZED = "WINTERIZED"


class PlanType(str, Enum):
    RECURRING = "RECURRING"
    ONE_TIME = "ONE_TIME"


class Frequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"
    NONE = "NONE"


class ServicePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    RECOVERY_SCHEDULED = "RECOVERY_SCHEDULED"
    CANCELLED = "CANCELLED"


class SkipReason(str, Enum):
    NONE = "NONE"
    WEATHER = "WEATHER"
    HOLIDAY = "HOLIDAY"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"


class WorkOrderComponent(str, Enum):
    PUMP = "PUMP"
    FILTER = "FILTER"
    HEATER = "HEATER"
    CHLORINATOR = "CHLORINATOR"
    LINER = "LINER"


class WorkOrderSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    DIAGNOSED = "DIAGNOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    ON_HOLD = "ON_HOLD"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class SeasonalEventType(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class SeasonalEventStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# --- Entity TypedDicts ---
# All these entities share the common system core: id, created_at, updated_at, version.

class Customer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    billing_terms: str
    account_status: str


class Pool(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    customer_id: str
    label: str
    water_type: str
    volume_gallons: int
    service_status: str
    open_work_order_count: int
    balance_due_cents: int


class ServicePlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    pool_id: str
    plan_type: str
    frequency: str
    per_visit_rate_cents: int
    prepaid_visit_count: int
    visits_remaining: int
    status: str


class RouteAssignment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    technician_id: str
    service_date: str
    window_start_minute: int
    window_end_minute: int
    capacity_visits: int
    status: str


class ServiceVisit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    pool_id: str
    plan_id: str
    route_id: str
    slot_start_minute: int
    slot_end_minute: int
    status: str
    skip_reason: str
    billed_amount_cents: int
    makeup_visit_id: Optional[str]


# ChemicalReading is append-only: it carries ONLY id + created_at.
# No updated_at, no version.
class ChemicalReading(TypedDict):
    id: str
    created_at: str
    visit_id: str
    free_chlorine_ppm: float
    ph: float
    total_alkalinity_ppm: float
    recommended_dose_grams: float


class WorkOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    pool_id: str
    raised_by_visit_id: Optional[str]
    component: str
    severity: str
    quoted_parts_cents: int
    labor_minutes: int
    status: str
    repair_total_cents: int


class SeasonalEvent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    pool_id: str
    event_type: str
    effective_date: str
    status: str


class Invoice(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    pool_id: str
    visit_id: Optional[str]
    work_order_id: Optional[str]
    amount_cents: int
    status: str
