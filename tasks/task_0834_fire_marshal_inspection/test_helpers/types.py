"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the standard system-managed fields
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    PLAN_REVIEWER = "PlanReviewer"
    INSPECTOR = "Inspector"
    FIRE_MARSHAL = "FireMarshal"


# ─── Domain enums ─────────────────────────────────────────────────────────
class OccupancyClassification(str, Enum):
    ASSEMBLY = "ASSEMBLY"
    BUSINESS = "BUSINESS"
    EDUCATIONAL = "EDUCATIONAL"
    FACTORY = "FACTORY"
    HIGH_HAZARD = "HIGH_HAZARD"
    INSTITUTIONAL = "INSTITUTIONAL"
    MERCANTILE = "MERCANTILE"
    RESIDENTIAL = "RESIDENTIAL"
    STORAGE = "STORAGE"
    UTILITY = "UTILITY"


class ConstructionType(str, Enum):
    TYPE_I = "TYPE_I"
    TYPE_II = "TYPE_II"
    TYPE_III = "TYPE_III"
    TYPE_IV = "TYPE_IV"
    TYPE_V = "TYPE_V"


class PermitType(str, Enum):
    CONSTRUCTION = "CONSTRUCTION"
    TENANT_IMPROVEMENT = "TENANT_IMPROVEMENT"
    HAZMAT = "HAZMAT"
    TANK = "TANK"


class PermitApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"


class DisciplineStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"


class OverallStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"


class Discipline(str, Enum):
    SPRINKLER = "SPRINKLER"
    ALARM = "ALARM"
    EGRESS = "EGRESS"


class Decision(str, Enum):
    APPROVED = "APPROVED"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class InspectionType(str, Enum):
    PERIODIC = "PERIODIC"
    COMPLAINT = "COMPLAINT"
    RE_INSPECTION = "RE_INSPECTION"
    FINAL = "FINAL"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class InspectionResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class ViolationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    IMMINENT_HAZARD = "IMMINENT_HAZARD"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    ABATED = "ABATED"
    VERIFIED = "VERIFIED"
    ESCALATED = "ESCALATED"


class AbatementOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    COMPLIED = "COMPLIED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    SUPERSEDED = "SUPERSEDED"


class OccupancyStatus(str, Enum):
    VALID = "VALID"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class PlacardStatus(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ────────
class Property(TypedDict):
    id: str
    address: str
    owner_name: str
    occupancy_classification: str
    construction_type: str
    total_floor_area_sqft: int
    stories: int
    occupant_load: int
    design_occupant_load: int
    required_exits: int
    required_fire_flow_gpm: int
    open_violation_count: int
    fees_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    property_id: str
    applicant_user_id: str
    permit_type: str
    project_valuation_cents: int
    scope_area_sqft: int
    flow_test_id: Optional[str]
    status: str
    estimated_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    amount_paid_cents: int
    refunded_cents: int
    resubmit_count: int
    created_at: str
    updated_at: str
    version: int


class PlanReview(TypedDict):
    id: str
    application_id: str
    sprinkler_status: str
    alarm_status: str
    egress_status: str
    overall_status: str
    correction_cycles: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    application_id: str
    permit_number: str
    status: str
    final_fee_cents: int
    issued_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    property_id: str
    inspection_type: str
    complaint_description: Optional[str]
    scheduled_date: str
    status: str
    result_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    inspection_id: str
    code_section: str
    severity: str
    status: str
    abated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbatementOrder(TypedDict):
    id: str
    violation_id: str
    issued_at: str
    deadline: str
    status: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    property_id: str
    occupancy_status: str
    placard_status: str
    created_at: str
    updated_at: str
    version: int


class Hydrant(TypedDict):
    id: str
    property_id: str
    location_desc: str
    main_size_inches: float
    created_at: str
    updated_at: str
    version: int


class FlowTest(TypedDict):
    id: str
    hydrant_id: str
    test_date: str
    static_psi: float
    residual_psi: float
    measured_flow_gpm: float
    available_flow_at_20psi: int
    valid_until: str
    created_at: str
    updated_at: str
    version: int
