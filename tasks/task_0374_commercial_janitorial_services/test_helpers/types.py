"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    FIELD_SUPERVISOR = "FieldSupervisor"
    CLIENT_CONTACT = "ClientContact"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status enums ---
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class FloorType(str, Enum):
    CARPET = "CARPET"
    VCT = "VCT"
    TERRAZZO = "TERRAZZO"
    CONCRETE = "CONCRETE"


class ServiceContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class RecurringScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class CrewMemberStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INACTIVE = "INACTIVE"


class VisitKind(str, Enum):
    ROUTINE = "ROUTINE"
    PERIODIC = "PERIODIC"
    CALLBACK = "CALLBACK"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class TimeEntryStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class PeriodicJobType(str, Enum):
    STRIP_WAX = "STRIP_WAX"
    DEEP_CARPET = "DEEP_CARPET"


class PeriodicJobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    BILLED = "BILLED"
    CANCELLED = "CANCELLED"


class ComplaintSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CALLBACK_SCHEDULED = "CALLBACK_SCHEDULED"
    RESOLVED = "RESOLVED"


class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    INVOICED = "INVOICED"


class InvoiceLineType(str, Enum):
    BASE = "BASE"
    PERIODIC = "PERIODIC"
    CALLBACK_CREDIT = "CALLBACK_CREDIT"
    HOLDBACK = "HOLDBACK"


class SupplySku(str, Enum):
    PAPER_TOWEL = "PAPER_TOWEL"
    TRASH_LINER = "TRASH_LINER"
    FLOOR_FINISH = "FLOOR_FINISH"
    RESTROOM_KIT = "RESTROOM_KIT"


class SupplyOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts ---
# Entities with common_fields:true carry id, created_at, updated_at, version.

class Account(TypedDict):
    id: str
    name: str
    billing_email: str
    status: str
    open_complaint_count: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    account_id: str
    contact_user_id: str
    label: str
    cleanable_sqft: int
    floor_type: str
    quality_target: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    site_id: str
    monthly_base_cents: int
    hourly_rate_cents: int
    callback_credit_pct: float
    quality_holdback_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RecurringSchedule(TypedDict):
    id: str
    site_id: str
    weekday: int
    window_start_min: int
    window_end_min: int
    assigned_crew_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    full_name: str
    shift_capacity_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    site_id: str
    schedule_id: Optional[str]
    crew_id: str
    visit_kind: str
    service_date: str
    planned_start_min: int
    planned_end_min: int
    estimated_labor_min: int
    actual_labor_min: int
    periodic_job_id: Optional[str]
    complaint_id: Optional[str]
    billing_period_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    visit_id: str
    crew_id: str
    clock_in_min: int
    clock_out_min: Optional[int]
    clocked_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    visit_id: str
    score: int
    deficient: bool
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PeriodicJob(TypedDict):
    id: str
    site_id: str
    job_type: str
    quoted_hours: float
    requested_date: str
    visit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    site_id: str
    visit_id: Optional[str]
    severity: str
    description: str
    callback_visit_id: Optional[str]
    credit_applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict):
    id: str
    contract_id: str
    period_month: str
    base_cents: int
    periodic_cents: int
    callback_credit_cents: int
    holdback_cents: int
    total_cents: int
    mean_quality_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# InvoiceLine has common_fields:false — append-only ledger row: id + created_at only.
class InvoiceLine(TypedDict):
    id: str
    billing_period_id: str
    line_type: str
    amount_cents: int
    memo: str
    created_at: str


class SupplyOrder(TypedDict):
    id: str
    site_id: str
    sku: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int
