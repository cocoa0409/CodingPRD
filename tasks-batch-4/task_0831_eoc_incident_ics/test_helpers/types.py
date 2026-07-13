"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3).

Every persisted resource carries the common system-managed fields id,
created_at, updated_at, and version (PRD §2.4), so each TypedDict below
lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ────────────────────────────────────────────
class UserRole(str, Enum):
    EOC_MANAGER = "EOCManager"
    LOGISTICS_CHIEF = "LogisticsChief"
    OPERATIONS_CHIEF = "OperationsChief"
    PLANNING_CHIEF = "PlanningChief"
    FINANCE_CHIEF = "FinanceChief"
    JURISDICTION_LIAISON = "JurisdictionLiaison"


# ─── Status enums (PRD §3) ───────────────────────────────────────────
class IncidentOpStatus(str, Enum):
    MONITORING = "MONITORING"
    ACTIVATED = "ACTIVATED"
    DEMOBILIZING = "DEMOBILIZING"
    CLOSED = "CLOSED"


class ActivationLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class DeclarationStatus(str, Enum):
    INELIGIBLE = "INELIGIBLE"
    ELIGIBLE = "ELIGIBLE"


class DeclarationCategory(str, Enum):
    EMERGENCY = "EMERGENCY"
    MAJOR_DISASTER = "MAJOR_DISASTER"


class ResourceRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    NEEDS_INFO = "NEEDS_INFO"
    SOURCED = "SOURCED"
    FILLED = "FILLED"
    DENIED = "DENIED"
    DEMOBILIZED = "DEMOBILIZED"


class IAPStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class TaskStatus(str, Enum):
    PLANNED = "PLANNED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ShelterStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MutualAidStatus(str, Enum):
    REQUESTED = "REQUESTED"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class DamageAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class CostRecordStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"
    VOID = "VOID"


# ─── Entity TypedDicts (PRD §3) ──────────────────────────────────────
class Incident(TypedDict):
    id: str
    name: str
    hazard_type: str
    declaration_category: str
    cost_ceiling: float
    op_status: str
    activation_level: str
    total_committed_cost: float
    total_actual_cost: float
    federal_share_estimated: float
    federal_share_actual: float
    total_verified_damage: float
    declaration_status: str
    current_iap_id: Optional[str]
    activated_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    id: str
    name: str
    contact_email: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResourcePool(TypedDict):
    id: str
    jurisdiction_id: str
    resource_type: str
    total_units: int
    units_reserved: int
    units_committed: int
    units_available: int
    surge_cap: Optional[int]
    turnaround_hours: int
    created_at: str
    updated_at: str
    version: int


class ResourceRequest(TypedDict):
    id: str
    incident_id: str
    resource_type: str
    requested_quantity: int
    priority: str
    status: str
    source_pool_id: Optional[str]
    committed_units: int
    deploy_start: Optional[str]
    deploy_end: Optional[str]
    submitted_at: Optional[str]
    sourced_at: Optional[str]
    demobilized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentActionPlan(TypedDict):
    id: str
    incident_id: str
    operational_period_start: str
    operational_period_end: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Task(TypedDict):
    id: str
    iap_id: str
    title: str
    parent_task_id: Optional[str]
    resource_request_id: Optional[str]
    status: str
    assigned_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shelter(TypedDict):
    id: str
    incident_id: str
    name: str
    capacity: int
    current_occupancy: int
    reserved_occupancy: int
    status: str
    opened_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MutualAidRequest(TypedDict):
    id: str
    incident_id: str
    to_jurisdiction_id: str
    resource_type: str
    requested_units: int
    offered_units: int
    countered_units: int
    accepted_units: int
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageAssessment(TypedDict):
    id: str
    incident_id: str
    site_name: str
    estimated_loss: float
    infrastructure_category: str
    status: str
    validated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostRecord(TypedDict):
    id: str
    incident_id: str
    resource_request_id: Optional[str]
    category: str
    estimated_cost: float
    actual_cost: Optional[float]
    eligible: bool
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
