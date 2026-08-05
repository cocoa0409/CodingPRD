"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Role enum (PRD §2.1) ──────────────────────────────────────────────
class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    CASE_MANAGER = "CaseManager"
    INSPECTOR = "Inspector"
    CONTRACTOR = "Contractor"
    PROGRAM_ADMIN = "ProgramAdmin"


# ─── Status / classification enums ─────────────────────────────────────
class CaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATION = "INVESTIGATION"
    ENFORCEMENT = "ENFORCEMENT"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class MedicalStatus(str, Enum):
    ELEVATED = "ELEVATED"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"


class ReferenceBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"


class PriorityClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class IncomeTier(str, Enum):
    EXTREMELY_LOW = "EXTREMELY_LOW"
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MODERATE = "MODERATE"


class ResultClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"


class SpecimenType(str, Enum):
    VENOUS = "VENOUS"
    CAPILLARY = "CAPILLARY"


class TestKind(str, Enum):
    SCREENING = "SCREENING"
    DIAGNOSTIC = "DIAGNOSTIC"
    FOLLOWUP = "FOLLOWUP"


class InvestigationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class HazardType(str, Enum):
    PAINT = "PAINT"
    DUST = "DUST"
    SOIL = "SOIL"
    WATER = "WATER"


class Severity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class HazardControlStatus(str, Enum):
    OPEN = "OPEN"
    CONTROLLED = "CONTROLLED"


class OrderStatus(str, Enum):
    ISSUED = "ISSUED"
    IN_REMEDIATION = "IN_REMEDIATION"
    CLEARANCE_PENDING = "CLEARANCE_PENDING"
    CLEARED = "CLEARED"
    VOID = "VOID"


class ClearanceResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RelocationUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"


class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class ContractorStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts ─────────────────────────────────────────────────
# common_fields: true -> id, created_at, updated_at, version
class Child(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    guardian_name: str
    primary_dwelling_id: str
    medicaid_enrolled: bool
    income_tier: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only (immutable audit record)
class BloodLeadTest(TypedDict):
    id: str
    child_id: str
    bll_ug_dl: float
    specimen_type: str
    test_kind: str
    collected_at: str
    result_class: str
    created_at: str


class Dwelling(TypedDict):
    id: str
    street_address: str
    unit_designation: Optional[str]
    year_built: int
    owner_name: str
    jurisdiction: str
    pre_1978: bool
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    child_id: str
    dwelling_id: str
    qualifying_test_id: str
    case_status: str
    medical_status: str
    reference_bll_ug_dl: float
    reference_basis: str
    priority_class: str
    income_tier: str
    open_hazard_count: int
    controlled_hazard_count: int
    total_hazard_count: int
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    certification_id_number: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class EnvironmentalInvestigation(TypedDict):
    id: str
    case_id: str
    dwelling_id: str
    inspector_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    hazard_finding_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HazardFinding(TypedDict):
    id: str
    investigation_id: str
    hazard_type: str
    location: str
    measurement_value: float
    severity: str
    control_status: str
    created_at: str
    updated_at: str
    version: int


class HazardControlOrder(TypedDict):
    id: str
    case_id: str
    dwelling_id: str
    investigation_id: str
    status: str
    issued_at: str
    compliance_deadline: str
    hazard_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only
class ClearanceTest(TypedDict):
    id: str
    order_id: str
    cleared_by_inspector_id: str
    floor_result_ug_ft2: float
    sill_result_ug_ft2: float
    trough_result_ug_ft2: float
    evaluated_result: str
    created_at: str


class RelocationUnit(TypedDict):
    id: str
    address: str
    bedroom_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RelocationPlacement(TypedDict):
    id: str
    case_id: str
    relocation_unit_id: str
    start_date: str
    end_date: str
    occupant_count: int
    status: str
    actual_end_date: Optional[str]
    reimbursement_cents: int
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    business_name: str
    rrp_certification_number: str
    certification_status: str
    certification_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantFund(TypedDict):
    id: str
    fund_name: str
    fiscal_year: int
    total_budget_cents: int
    reserved_cents: int
    spent_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class RemediationProject(TypedDict):
    id: str
    order_id: str
    contractor_id: str
    grant_fund_id: str
    status: str
    estimated_cost_cents: int
    final_cost_cents: Optional[int]
    line_items: List[dict]
    created_at: str
    updated_at: str
    version: int
