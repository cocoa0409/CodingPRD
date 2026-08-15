"""Domain types: entity TypedDicts, status enums, role enum (PRD §2 and §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    EHS_ADMIN = "EHSAdmin"
    EHS_INSPECTOR = "EHSInspector"
    PRINCIPAL_INVESTIGATOR = "PrincipalInvestigator"
    LAB_MEMBER = "LabMember"


class WorkerRole(str, Enum):
    PI = "PI"
    RESEARCHER = "RESEARCHER"
    STUDENT = "STUDENT"


class LabStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    DECOMMISSIONED = "DECOMMISSIONED"


class LabPosture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class HazardClass(str, Enum):
    FLAMMABLE = "FLAMMABLE"
    OXIDIZER = "OXIDIZER"
    CORROSIVE = "CORROSIVE"
    TOXIC = "TOXIC"
    CONTROLLED_SUBSTANCE = "CONTROLLED_SUBSTANCE"
    SELECT_AGENT = "SELECT_AGENT"


class QuantityUnit(str, Enum):
    GAL = "GAL"
    L = "L"
    KG = "KG"
    LB = "LB"


class ContainerState(str, Enum):
    IN_USE = "IN_USE"
    WASTE_TAGGED = "WASTE_TAGGED"
    PICKED_UP = "PICKED_UP"


class AreaType(str, Enum):
    SAA = "SAA"
    CAA = "CAA"


class PickupStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FindingSeverity(str, Enum):
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    REOPENED = "REOPENED"
    VERIFIED = "VERIFIED"


class TrainingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MaterialType(str, Enum):
    CONTROLLED_SUBSTANCE = "CONTROLLED_SUBSTANCE"
    SELECT_AGENT = "SELECT_AGENT"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SURRENDERED = "SURRENDERED"
    SUPERSEDED = "SUPERSEDED"


class Lab(TypedDict, total=False):
    id: str
    name: str
    department: str
    building: str
    room: str
    pi_worker_id: Optional[str]
    status: str
    posture: str
    hazard_totals_physical: Dict[str, float]
    hazard_totals_regulatory: Dict[str, float]
    permit_report_required: bool
    created_at: str
    updated_at: str
    version: int


class LabWorker(TypedDict, total=False):
    id: str
    lab_id: str
    full_name: str
    role_in_lab: str
    created_at: str
    updated_at: str
    version: int


class ChemicalContainer(TypedDict, total=False):
    id: str
    lab_id: str
    barcode: str
    chemical_name: str
    hazard_class: str
    quantity_value: float
    quantity_unit: str
    state: str
    accumulation_area_id: Optional[str]
    tagged_at: Optional[str]
    pickup_request_id: Optional[str]
    access_blocked: bool
    created_at: str
    updated_at: str
    version: int


class AccumulationArea(TypedDict, total=False):
    id: str
    lab_id: str
    name: str
    area_type: str
    capacity_containers: int
    current_container_count: int
    has_overstay_containers: bool
    created_at: str
    updated_at: str
    version: int


class WastePickupRequest(TypedDict, total=False):
    id: str
    lab_id: str
    status: str
    dock_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    rejection_reason: Optional[str]
    estimated_quantity_total: float
    estimated_cost: float
    created_at: str
    updated_at: str
    version: int


class LabInspection(TypedDict, total=False):
    id: str
    lab_id: str
    inspector_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    findings: List[Dict[str, Any]]
    score_weighted: Optional[float]
    score_flat: Optional[float]
    outcome: Optional[str]
    completed_by_inspector_id: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict, total=False):
    id: str
    inspection_id: str
    lab_id: str
    description: str
    severity: str
    status: str
    due_date: str
    resolution_note: Optional[str]
    verified_by: Optional[str]
    overdue: bool
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict, total=False):
    id: str
    lab_id: str
    worker_id: str
    hazard_class: str
    status: str
    due_date: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    lab_id: str
    title: str
    description: str
    severity: str
    near_miss: bool
    status: str
    reported_by: str
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    lab_id: str
    material_type: str
    registration_number: str
    status: str
    created_at: str
    updated_at: str
    version: int
