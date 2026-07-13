"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this system carries id, created_at, updated_at, and an integer
version (PRD §2.4), so every TypedDict below lists updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ADMIN = "Admin"
    DISPATCHER = "Dispatcher"
    FIELD_TECH = "FieldTech"
    TRAFFIC_ENGINEER = "TrafficEngineer"
    UTILITY_COORDINATOR = "UtilityCoordinator"


class IntersectionPosture(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    EMERGENCY = "EMERGENCY"


class PoleStatus(str, Enum):
    STANDING = "STANDING"
    DOWN = "DOWN"


class DeviceType(str, Enum):
    SIGNAL_CONTROLLER = "SIGNAL_CONTROLLER"
    SIGNAL_HEAD = "SIGNAL_HEAD"
    PED_SIGNAL = "PED_SIGNAL"
    DETECTOR = "DETECTOR"
    STREETLIGHT = "STREETLIGHT"


class Criticality(str, Enum):
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"
    LOW = "LOW"


class DeviceStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    KNOCKED_DOWN = "KNOCKED_DOWN"
    DECOMMISSIONED = "DECOMMISSIONED"


class MountZone(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"


class PoleAttachmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class Specialty(str, Enum):
    SIGNAL = "SIGNAL"
    LIGHTING = "LIGHTING"
    LOCATE = "LOCATE"
    GENERAL = "GENERAL"


class TicketSource(str, Enum):
    SRC_311 = "SRC_311"
    DETECTOR = "DETECTOR"
    KNOCKDOWN = "KNOCKDOWN"


class PriorityBand(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class SlaResponseStatus(str, Enum):
    PENDING = "PENDING"
    ON_TRACK = "ON_TRACK"
    BREACHED = "BREACHED"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class WorkType(str, Enum):
    REPAIR = "REPAIR"
    PM_LAMP = "PM_LAMP"
    LED_REPLACEMENT = "LED_REPLACEMENT"
    EXCAVATION = "EXCAVATION"
    EMERGENCY = "EMERGENCY"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TimingChangeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class LocateStatus(str, Enum):
    OPEN = "OPEN"
    MARKED = "MARKED"
    CLEARED = "CLEARED"


class CoverageVariant(str, Enum):
    FULL = "FULL"
    PRORATED = "PRORATED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class Intersection(TypedDict):
    id: str
    name: str
    district: str
    latitude: float
    longitude: float
    active_cycle_length_sec: int
    active_offset_sec: int
    active_plan_revision: int
    operational_posture: str
    created_at: str
    updated_at: str
    version: int


class Pole(TypedDict):
    id: str
    intersection_id: Optional[str]
    label: str
    latitude: float
    longitude: float
    load_capacity_units: int
    committed_load_units: int
    available_load_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    intersection_id: str
    pole_id: Optional[str]
    device_type: str
    criticality: str
    model: str
    installed_at: str
    replacement_cost: float
    warranty_provider: str
    last_pm_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PoleAttachment(TypedDict):
    id: str
    pole_id: str
    attacher_name: str
    mount_zone: str
    load_units: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    specialty: str
    labor_capacity_hours: float
    committed_labor_hours: float
    available_labor_hours: float
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    device_id: str
    source: str
    reported_severity: int
    hazard_flag: bool
    struck_pole: bool
    description: str
    priority_score: Optional[int]
    priority_band: Optional[str]
    triaged_at: Optional[str]
    response_due: Optional[str]
    resolution_due: Optional[str]
    sla_response_status: str
    resolved_at: Optional[str]
    reopen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    ticket_id: Optional[str]
    device_id: str
    crew_id: Optional[str]
    locate_request_id: Optional[str]
    work_type: str
    estimated_labor_hours: float
    estimated_parts: List[dict]
    actual_labor_hours: Optional[float]
    actual_parts: List[dict]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    provisional_cost: Optional[float]
    final_cost: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class TimingPlanChangeRequest(TypedDict):
    id: str
    intersection_id: str
    proposed_cycle_length_sec: int
    proposed_offset_sec: int
    rationale: str
    revision_count: int
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LocateRequest(TypedDict):
    id: str
    intersection_id: str
    requested_by: str
    valid_days: int
    valid_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    device_id: str
    work_order_id: Optional[str]
    defect_description: str
    coverage_variant: Optional[str]
    payout_amount: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int
