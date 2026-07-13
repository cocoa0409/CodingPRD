"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the four common system-managed properties
(id, created_at, updated_at, version) per the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---
class UserRole(str, Enum):
    SUPERVISOR = "Supervisor"
    INSPECTOR = "Inspector"
    DISPATCHER = "Dispatcher"
    CREW_LEAD = "CrewLead"
    COORDINATOR = "Coordinator"


# --- Status enums ---
class AssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REPAIR = "UNDER_REPAIR"
    RETIRED = "RETIRED"


class AssetConditionState(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    FAILED = "FAILED"


class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ServiceRequestStatus(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    LINKED = "LINKED"
    CLOSED = "CLOSED"
    DUPLICATE = "DUPLICATE"


class ServiceRequestPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EMERGENCY = "EMERGENCY"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_ASSIGNMENT = "ON_ASSIGNMENT"


class DispatchStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class MaterialReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class ROWPermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    DENIED = "DENIED"
    RELEASED = "RELEASED"


# --- Entity TypedDicts (all carry the four common fields) ---
class Asset(TypedDict):
    id: str
    asset_class: str
    gis_segment_id: str
    location_desc: str
    install_date: str
    replacement_value_cents: int
    status: str
    pci_score: Optional[float]
    condition_state: Optional[str]
    last_inspection_at: Optional[str]
    maintenance_cost_to_date_cents: int
    capital_cost_to_date_cents: int
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    asset_id: str
    inspector_id: str
    inspection_type: str
    raw_distress_index: float
    computed_pci: Optional[float]
    scheduled_window_start: str
    scheduled_window_end: str
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    asset_id: str
    channel: str
    category: str
    reported_by: str
    location_desc: str
    priority: str
    sla_due_at: str
    duplicate_of_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    asset_id: str
    service_request_id: Optional[str]
    work_type: str
    origin: str
    priority: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    estimated_cost_cents: int
    labor_cost_cents: int
    material_cost_cents: int
    actual_cost_cents: int
    capitalized: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    crew_type: str
    hourly_rate_cents: int
    status: str
    committed_minutes: int
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    work_order_id: str
    crew_id: str
    window_start: str
    window_end: str
    labor_hours: float
    labor_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Yard(TypedDict):
    id: str
    name: str
    location_desc: str
    created_at: str
    updated_at: str
    version: int


class MaterialItem(TypedDict):
    id: str
    material_type: str
    yard_id: str
    unit: str
    on_hand_qty: float
    reserved_qty: float
    available_qty: float
    unit_cost_cents: int
    reorder_point: float
    created_at: str
    updated_at: str
    version: int


class MaterialReservation(TypedDict):
    id: str
    work_order_id: str
    material_item_id: str
    qty: float
    consumed_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ROWPermit(TypedDict):
    id: str
    work_order_id: str
    permit_type: str
    gis_segment_id: str
    utility_company: Optional[str]
    window_start: str
    window_end: str
    clearance_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int
