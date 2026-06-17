"""Domain types: entity TypedDicts, status enums, and the role enum.

Mirrors the resources and lifecycles described in the PRD (Sections 2.4 and 3).
Every resource in this system carries the four common fields
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    CREW_LEAD = "CrewLead"
    QUALITY_INSPECTOR = "QualityInspector"
    DISPATCH_OPERATOR = "DispatchOperator"


# --- Status enums ---
class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class RouteStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class VisitExecutionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VisitBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    WRITTEN_OFF = "WRITTEN_OFF"


class AddOnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class StormEventStatus(str, Enum):
    REPORTED = "REPORTED"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    STOOD_DOWN = "STOOD_DOWN"


class InspectionStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    FAILED = "FAILED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class SnowZone(str, Enum):
    PRIORITY = "PRIORITY"
    STANDARD = "STANDARD"
    EXEMPT = "EXEMPT"


# --- Entity TypedDicts (all carry the four common fields per PRD §2.4) ---
class ServiceAccount(TypedDict):
    id: str
    name: str
    region_code: str
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    service_account_id: str
    name: str
    address: str
    turf_area_sqft: int
    snow_zone: str
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    service_account_id: str
    site_id: str
    annual_budget_cents: int
    billing_cycle: str
    committed_cents: int
    billed_cents: int
    budget_remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict):
    id: str
    service_contract_id: str
    site_id: str
    service_type: str
    frequency: str
    base_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    service_account_id: str
    name: str
    hourly_rate_cents: int
    certified_for_snow: bool
    created_at: str
    updated_at: str
    version: int


class RouteSchedule(TypedDict):
    id: str
    crew_id: str
    service_account_id: str
    route_date: str
    shift_start_minute: int
    shift_end_minute: int
    booked_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    service_plan_id: str
    service_contract_id: str
    route_schedule_id: str
    crew_id: str
    slot_start_minute: int
    slot_duration_minute: int
    actual_labor_minutes: int
    estimated_charge_cents: int
    final_charge_cents: int
    execution_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class EnhancementAddOn(TypedDict):
    id: str
    service_visit_id: str
    addon_type: str
    quantity: int
    unit_price_cents: int
    addon_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentAsset(TypedDict):
    id: str
    service_account_id: str
    name: str
    hourly_usage_cost_cents: int
    service_interval_hours: int
    accumulated_usage_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentReservation(TypedDict):
    id: str
    equipment_asset_id: str
    service_visit_id: str
    window_start_minute: int
    window_end_minute: int
    reserved_minutes: int
    usage_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SnowStormEvent(TypedDict):
    id: str
    site_id: str
    service_account_id: str
    assigned_crew_id: Optional[str]
    snowfall_inches: int
    response_deadline_minute: int
    dispatch_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityInspection(TypedDict):
    id: str
    service_visit_id: str
    inspector_user_id: str
    score: int
    rework_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    service_contract_id: str
    period_label: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    line_item_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
