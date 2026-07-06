"""Domain types for the Pool Construction API: entity TypedDicts, status enums, role enum.

Every entity in this contract carries the common fields id, created_at, updated_at and
version (PRD §2.4), so all TypedDicts below include them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) -------------------------------------------------
class UserRole(str, Enum):
    BUILDER_PM = "BuilderPM"
    DESIGNER = "Designer"
    OWNER = "Owner"
    INSPECTOR = "Inspector"
    SUBCONTRACTOR = "Subcontractor"


# --- Status / enum vocabularies -------------------------------------------
class ConstructionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_CONSTRUCTION = "IN_CONSTRUCTION"
    STARTUP_READY = "STARTUP_READY"
    ORIENTED = "ORIENTED"
    CLOSED = "CLOSED"


class Posture(str, Enum):
    OPEN = "OPEN"
    HOLD = "HOLD"
    STOP_WORK = "STOP_WORK"


class DesignStatus(str, Enum):
    NO_DESIGN = "NO_DESIGN"
    IN_DESIGN = "IN_DESIGN"
    DESIGN_APPROVED = "DESIGN_APPROVED"
    PERMITTED = "PERMITTED"


class CurrentPhase(str, Enum):
    NONE = "NONE"
    EXCAVATION = "EXCAVATION"
    STEEL = "STEEL"
    PLUMBING = "PLUMBING"
    GUNITE = "GUNITE"
    PLASTER = "PLASTER"
    STARTUP = "STARTUP"


class PoolType(str, Enum):
    GUNITE = "GUNITE"
    REMODEL = "REMODEL"


class DesignPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    RENDERED_3D = "RENDERED_3D"
    OWNER_APPROVED = "OWNER_APPROVED"


class PermitStatus(str, Enum):
    NONE = "NONE"
    SUBMITTED = "SUBMITTED"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"


class PhaseGateStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    INSPECTION_PENDING = "INSPECTION_PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class Phase(str, Enum):
    EXCAVATION = "EXCAVATION"
    STEEL = "STEEL"
    PLUMBING = "PLUMBING"
    GUNITE = "GUNITE"
    PLASTER = "PLASTER"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SubcontractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Trade(str, Enum):
    EXCAVATOR = "EXCAVATOR"
    STEEL = "STEEL"
    PLUMBER = "PLUMBER"
    GUNITE = "GUNITE"
    PLASTER = "PLASTER"
    GENERAL = "GENERAL"


class CrewAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ChangeOrderCategory(str, Enum):
    PUMP = "PUMP"
    HEATER = "HEATER"
    LIGHTING = "LIGHTING"
    WATER_FEATURE = "WATER_FEATURE"
    CLEANER = "CLEANER"
    SCOPE = "SCOPE"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class DrawRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FUNDED = "FUNDED"


class PunchSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SAFETY = "SAFETY"


class PunchStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


# --- Entity TypedDicts ----------------------------------------------------
class PoolProject(TypedDict):
    id: str
    owner_name: str
    owner_user_id: str
    site_address: str
    pool_type: str
    contract_price_cents: int
    pool_gallons: int
    construction_status: str
    current_phase: str
    design_status: str
    posture: str
    contract_amount_cents: int
    amount_disbursed_cents: int
    retainage_held_cents: int
    amount_remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class DesignPlan(TypedDict):
    id: str
    pool_project_id: str
    length_ft: float
    width_ft: float
    avg_depth_ft: float
    status: str
    permit_status: str
    jurisdiction: Optional[str]
    permit_number: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class PhaseGate(TypedDict):
    id: str
    pool_project_id: str
    phase: str
    sequence_index: int
    budget_cents: int
    status: str
    inspection_attempts: int
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    pool_project_id: str
    phase_gate_id: str
    inspector_name: str
    scheduled_at: str
    status: str
    result_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict):
    id: str
    company_name: str
    trade: str
    status: str
    committed_crew_hours: float
    reliability_projected: float
    reliability_realized: float
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    pool_project_id: str
    subcontractor_id: str
    phase_gate_id: str
    start_at: str
    end_at: str
    duration_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    pool_project_id: str
    category: str
    description: str
    price_delta_cents: int
    phase: Optional[str]
    applied_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DrawRequest(TypedDict):
    id: str
    pool_project_id: str
    phase_gate_id: str
    requested_cents: int
    provisional_eligible_cents: int
    eligible_cents: int
    retainage_cents: int
    net_disbursed_cents: int
    retainage_released: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchItem(TypedDict):
    id: str
    pool_project_id: str
    description: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int
