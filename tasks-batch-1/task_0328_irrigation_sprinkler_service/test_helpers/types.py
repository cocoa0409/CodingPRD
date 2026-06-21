"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the full common-field set (id, created_at,
updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    CUSTOMER = "Customer"
    BACKFLOW_TESTER = "BackflowTester"


# --- Status enums ---
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TechnicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INACTIVE = "INACTIVE"


class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ComplianceStatus(str, Enum):
    NON_COMPLIANT = "NON_COMPLIANT"
    COMPLIANT = "COMPLIANT"


class SeasonState(str, Enum):
    DORMANT = "DORMANT"
    ACTIVE = "ACTIVE"
    WINTERIZED = "WINTERIZED"


class BackflowStatus(str, Enum):
    UNTESTED = "UNTESTED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class SystemLifecycleState(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DECOMMISSIONED = "DECOMMISSIONED"


class ZoneState(str, Enum):
    MAPPED = "MAPPED"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PlantType(str, Enum):
    TURF = "TURF"
    SHRUB = "SHRUB"
    DRIP = "DRIP"
    ROTOR = "ROTOR"


class ProgramState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    STALE = "STALE"


class QuoteType(str, Enum):
    INSTALL = "INSTALL"
    REPAIR = "REPAIR"


class QuoteState(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class JobType(str, Enum):
    INSTALL = "INSTALL"
    STARTUP = "STARTUP"
    WINTERIZATION = "WINTERIZATION"
    LEAK_REPAIR = "LEAK_REPAIR"
    HEAD_REPAIR = "HEAD_REPAIR"
    BACKFLOW_TEST = "BACKFLOW_TEST"


class DispatchStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"


class CompletionStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class PlanState(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class BackflowResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RouteState(str, Enum):
    PLANNING = "PLANNING"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class StopState(str, Enum):
    SCHEDULED = "SCHEDULED"
    REMOVED = "REMOVED"


# --- Entity TypedDicts (all carry common fields) ---
class Customer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    company_name: str
    contact_email: str
    billing_zip: str
    status: str


class Technician(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    shift_start_sec: int
    shift_end_sec: int
    backflow_certified: bool
    status: str


class Property(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    customer_id: str
    site_address: str
    lat: float
    lng: float
    status: str
    compliance_status: str


class IrrigationSystem(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    controller_model: str
    static_psi: int
    has_backflow_device: bool
    season_state: str
    backflow_status: str
    lifecycle_state: str
    zone_count: int
    committed_cost_cents: int
    provisional_winter_risk: int
    assessed_winter_risk: int


class Zone(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    system_id: str
    zone_number: int
    plant_type: str
    head_count: int
    gpm_per_head: int
    zone_state: str


class ControllerProgram(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    system_id: str
    program_state: str
    slots: List[dict]
    total_run_minutes: int


class ServiceQuote(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    quote_type: str
    line_items: List[dict]
    estimated_total_cents: int
    final_total_cents: int
    quote_state: str
    linked_work_order_id: Optional[str]


class WorkOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    system_id: str
    job_type: str
    estimated_minutes: int
    estimated_cost_cents: int
    actual_labor_cents: int
    actual_parts_cents: int
    assigned_technician_id: Optional[str]
    dispatch_status: str
    completion_status: str
    origin_quote_id: Optional[str]


class MaintenancePlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    tier: str
    visits_per_year: int
    annual_dues_cents: int
    plan_state: str


class BackflowTest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    system_id: str
    tester_technician_id: str
    relief_open_psi: int
    checkvalve_hold_psi: int
    result: str


class Route(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    technician_id: str
    route_date: str
    route_state: str
    stops_used: int
    minutes_committed: int


class RouteStop(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    route_id: str
    work_order_id: str
    arrival_start_sec: int
    window_minutes: int
    stop_state: str
