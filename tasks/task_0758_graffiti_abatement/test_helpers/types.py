"""Domain types: entity TypedDicts, status enums, role enum.

All names use the PRD's domain vocabulary (Graffiti Abatement API).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    RESIDENT = "Resident"
    INTAKE_CLERK = "IntakeClerk"
    ABATEMENT_COORDINATOR = "AbatementCoordinator"
    CREW_LEAD = "CrewLead"
    INVENTORY_MANAGER = "InventoryManager"
    PROPERTY_OWNER_USER = "PropertyOwnerUser"
    PROGRAM_ADMIN = "ProgramAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class SiteStatus(str, Enum):
    NORMAL = "NORMAL"
    MONITORED = "MONITORED"
    HOTSPOT = "HOTSPOT"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    REMEDIATED = "REMEDIATED"
    CLOSED = "CLOSED"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISPATCHED = "DISPATCHED"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RECALLED = "RECALLED"


class MaterialReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class MaterialStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LOW = "LOW"
    DEPLETED = "DEPLETED"


class CostRecoveryStatus(str, Enum):
    PENDING = "PENDING"
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    WAIVED = "WAIVED"
    LIEN_PENDING = "LIEN_PENDING"
    PAID = "PAID"
    VOID = "VOID"


class NoticeStatus(str, Enum):
    SENT = "SENT"
    CONSENTED = "CONSENTED"
    DISPUTED = "DISPUTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


# --------------------------------------------------------------------------
# Input-field enums
# --------------------------------------------------------------------------
class OwnershipType(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class ReportedVia(str, Enum):
    PHONE_311 = "PHONE_311"
    WEB = "WEB"
    MOBILE_APP = "MOBILE_APP"


class SurfaceType(str, Enum):
    WALL = "WALL"
    FENCE = "FENCE"
    SIGN = "SIGN"
    SIDEWALK = "SIDEWALK"
    VEHICLE = "VEHICLE"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class CrewType(str, Enum):
    CITY = "CITY"
    CONTRACTOR = "CONTRACTOR"


class RemovalMethod(str, Enum):
    PAINT_OVER = "PAINT_OVER"
    PRESSURE_WASH = "PRESSURE_WASH"
    CHEMICAL = "CHEMICAL"


class MaterialCategory(str, Enum):
    PAINT = "PAINT"
    SOLVENT = "SOLVENT"
    ABRASIVE = "ABRASIVE"


class MaterialUnit(str, Enum):
    LITERS = "LITERS"
    GALLONS = "GALLONS"


class NoticeType(str, Enum):
    ABATEMENT_NOTICE = "ABATEMENT_NOTICE"
    COST_RECOVERY_NOTICE = "COST_RECOVERY_NOTICE"


class PhotoPhase(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class RemovalLogAction(str, Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    RECALLED = "RECALLED"


# --------------------------------------------------------------------------
# Entity TypedDicts
#   common_fields: true  -> id, created_at, updated_at, version
#   common_fields: false -> id, created_at only (append-only audit records)
# --------------------------------------------------------------------------
class PropertyOwner(TypedDict):
    id: str
    name: str
    mailing_address: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    address: str
    latitude: float
    longitude: float
    ownership_type: str
    property_owner_id: Optional[str]
    status: str
    report_count_90d: int
    open_report_count: int
    hotspot_severity_index_rolling: int
    hotspot_severity_index_confirmed: int
    outstanding_recovery_cents: int
    lien_count: int
    active_notice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict):
    id: str
    site_id: str
    reported_via: str
    reporter_contact: Optional[str]
    surface_type: str
    severity: str
    is_offensive: bool
    description: str
    latitude: Optional[float]
    longitude: Optional[float]
    priority_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    crew_type: str
    is_offensive_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    report_id: str
    crew_id: str
    scheduled_start: str
    scheduled_end: str
    method: str
    estimated_labor_hours: float
    actual_labor_hours: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaterialReservation(TypedDict):
    id: str
    work_order_id: str
    material_id: str
    quantity_reserved: float
    quantity_consumed: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Material(TypedDict):
    id: str
    name: str
    category: str
    color: Optional[str]
    unit: str
    unit_cost_cents: int
    quantity_available: float
    quantity_reserved: float
    reorder_threshold: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CostRecovery(TypedDict):
    id: str
    site_id: str
    work_order_id: str
    estimated_cost_cents: int
    final_cost_cents: Optional[int]
    labor_cost_cents: int
    material_cost_cents: int
    admin_fee_cents: int
    recoverable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Notice(TypedDict):
    id: str
    site_id: str
    cost_recovery_id: Optional[str]
    notice_type: str
    cure_days: int
    sent_at: str
    cure_deadline: str
    response_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit records — id + created_at ONLY (no updated_at / version)
class Photo(TypedDict):
    id: str
    work_order_id: str
    phase: str
    url: str
    captured_at: str
    created_at: str


class RemovalLog(TypedDict):
    id: str
    work_order_id: str
    action: str
    note: Optional[str]
    logged_by: str
    created_at: str
