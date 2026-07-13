"""Domain types: entity TypedDicts, status enums, role enum (Urban Forestry & Tree Permit API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    FORESTRY_ADMIN = "ForestryAdmin"
    FORESTRY_STAFF = "ForestryStaff"
    ARBORIST = "Arborist"
    INSPECTOR = "Inspector"
    APPLICANT = "Applicant"
    CONTRACTOR = "Contractor"


# --------------------------------------------------------------------------
# Status / enum value sets
# --------------------------------------------------------------------------
class ZoneCanopyStatus(str, Enum):
    MEETS = "MEETS"
    DEFICIT = "DEFICIT"


class TreeHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DECLINING = "DECLINING"
    HAZARD = "HAZARD"
    REMOVED = "REMOVED"


class RiskRating(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class ConditionClass(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    DEAD = "DEAD"


class InspectionType(str, Enum):
    ROUTINE = "ROUTINE"
    RISK = "RISK"
    POST_STORM = "POST_STORM"


class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"


class PermitType(str, Enum):
    REMOVAL = "REMOVAL"
    PRUNING = "PRUNING"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"


class MitigationMethod(str, Enum):
    REPLACEMENT_COST = "REPLACEMENT_COST"
    APPRAISED_VALUE = "APPRAISED_VALUE"


class ContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class WorkType(str, Enum):
    REMOVAL = "REMOVAL"
    PRUNING = "PRUNING"
    EMERGENCY_REMOVAL = "EMERGENCY_REMOVAL"


class WorkOrderStatus(str, Enum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class DigTicketStatus(str, Enum):
    REQUESTED = "REQUESTED"
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class StormSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class StormEventStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ReplacementPlantingStatus(str, Enum):
    REQUIRED = "REQUIRED"
    PLANTED = "PLANTED"
    ESTABLISHED = "ESTABLISHED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# common_fields: true -> id + created_at + updated_at + version
class Zone(TypedDict):
    id: str
    name: str
    target_canopy_pct: float
    area_sqm: float
    live_canopy_sqm: float
    current_canopy_pct: float
    canopy_status: str
    high_risk_tree_count: int
    tree_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> ONLY id + created_at (no updated_at / version)
class Species(TypedDict):
    id: str
    name: str
    is_protected_species: bool
    is_native: bool
    mature_canopy_sqm: float
    base_replacement_value_dollars: float
    base_appraisal_value_per_sqin: float
    min_spacing_m: float
    created_at: str


class Tree(TypedDict):
    id: str
    zone_id: str
    species_id: str
    dbh_inches: float
    canopy_radius_m: float
    latitude: float
    longitude: float
    condition_class: str
    is_protected: bool
    health_status: str
    risk_rating: str
    prior_risk_rating: str
    prior_health_status: str
    current_inspection_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    tree_id: str
    inspection_type: str
    likelihood_score: int
    consequence_score: int
    target_rating: int
    provisional_risk_score: int
    provisional_risk_rating: str
    final_risk_score: Optional[int]
    final_risk_rating: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    tree_id: str
    permit_type: str
    reason: str
    requested_by_user_id: str
    status: str
    mitigation_method: Optional[str]
    required_replacement_count: int
    mitigation_fee_cents: int
    fee_paid: bool
    fee_paid_cents: int
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    name: str
    license_number: str
    license_expiry: str
    is_certified_arborist: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    tree_id: str
    permit_id: Optional[str]
    contractor_id: str
    work_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DigTicket(TypedDict):
    id: str
    work_order_id: str
    ticket_number: str
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StormEvent(TypedDict):
    id: str
    affected_zone_id: str
    severity: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplacementPlanting(TypedDict):
    id: str
    permit_id: str
    species_id: str
    target_zone_id: str
    sequence_index: int
    status: str
    created_at: str
    updated_at: str
    version: int
