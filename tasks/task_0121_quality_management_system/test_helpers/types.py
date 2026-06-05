"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as named in the PRD. The 8D step record is an
append-only journal entry: it carries only id + created_at (no updated_at,
no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Request-time role names (X-User-Role)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    QUALITY_ENGINEER = "QualityEngineer"
    QUALITY_MANAGER = "QualityManager"
    INSPECTOR = "Inspector"
    AUDITOR = "Auditor"
    SUPPLIER_USER = "SupplierUser"


# --------------------------------------------------------------------------
# Personnel.role attribute (stored value, distinct from request role name)
# --------------------------------------------------------------------------
class PersonnelRole(str, Enum):
    QUALITY_ENGINEER = "QUALITY_ENGINEER"
    QUALITY_MANAGER = "QUALITY_MANAGER"
    INSPECTOR = "INSPECTOR"
    AUDITOR = "AUDITOR"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class PersonnelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class SupplierApprovalStatus(str, Enum):
    APPROVED = "APPROVED"
    PROBATION = "PROBATION"
    DISQUALIFIED = "DISQUALIFIED"


class NcrStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    DISPOSITIONED = "DISPOSITIONED"
    CAPA_IN_PROGRESS = "CAPA_IN_PROGRESS"
    CLOSED = "CLOSED"
    VOID = "VOID"


class NcrSource(str, Enum):
    SUPPLIER = "SUPPLIER"
    INTERNAL = "INTERNAL"
    AUDIT = "AUDIT"


class NcrSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class NcrDisposition(str, Enum):
    REWORK = "REWORK"
    SCRAP = "SCRAP"
    USE_AS_IS = "USE_AS_IS"
    RETURN_TO_SUPPLIER = "RETURN_TO_SUPPLIER"


class CapaStatus(str, Enum):
    OPEN = "OPEN"
    ROOT_CAUSE = "ROOT_CAUSE"
    VERIFICATION = "VERIFICATION"
    EFFECTIVENESS_CHECK = "EFFECTIVENESS_CHECK"
    CLOSED_EFFECTIVE = "CLOSED_EFFECTIVE"
    CLOSED_INEFFECTIVE = "CLOSED_INEFFECTIVE"


class CapaStep(str, Enum):
    D1 = "D1"
    D2 = "D2"
    D3 = "D3"
    D4 = "D4"
    D5 = "D5"
    D6 = "D6"
    D7 = "D7"
    D8 = "D8"


class ScarStatus(str, Enum):
    OPEN = "OPEN"
    ACK = "ACK"
    RESPONDED = "RESPONDED"
    ACCEPTED_RESPONSE = "ACCEPTED_RESPONSE"
    REJECTED_RESPONSE = "REJECTED_RESPONSE"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class InspectionSeverityMode(str, Enum):
    NORMAL = "NORMAL"
    TIGHTENED = "TIGHTENED"


class InspectionLevel(str, Enum):
    GI = "GI"
    GII = "GII"
    GIII = "GIII"


class InspectionLotStatus(str, Enum):
    PENDING = "PENDING"
    IN_INSPECTION = "IN_INSPECTION"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AuditStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class AuditFindingStatus(str, Enum):
    OPEN = "OPEN"
    NCR_RAISED = "NCR_RAISED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class AuditFindingGrade(str, Enum):
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    OBSERVATION = "OBSERVATION"


class DeviationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ControlPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ControlPlanRevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# common_fields: true -> id + created_at + updated_at + version
class Personnel(TypedDict):
    id: str
    full_name: str
    email: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    name: str
    code: str
    quality_rating: float
    approval_status: str
    open_scar_count: int
    lots_inspected: int
    lots_rejected: int
    ncrs_attributed: int
    created_at: str
    updated_at: str
    version: int


class NonconformanceReport(TypedDict):
    id: str
    title: str
    source: str
    supplier_id: Optional[str]
    audit_finding_id: Optional[str]
    inspection_lot_id: Optional[str]
    part_number: str
    severity: str
    defect_qty: int
    unit_cost_cents: int
    rework_hours: float
    status: str
    disposition: Optional[str]
    deviation_id: Optional[str]
    cost_of_quality_cents: int
    budget_reserved_cents: int
    created_by_personnel_id: str
    created_at: str
    updated_at: str
    version: int


class Capa(TypedDict):
    id: str
    ncr_id: str
    title: str
    current_step: str
    status: str
    rework_loops: int
    provisional_effectiveness: Optional[float]
    final_effectiveness: Optional[float]
    authored_by_personnel_id: str
    verified_by_personnel_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at ONLY (no updated_at, no version)
class EightDStep(TypedDict):
    id: str
    capa_id: str
    discipline: str
    narrative: str
    containment_count: int
    recurred_defects: int
    recorded_by_personnel_id: str
    created_at: str


class Scar(TypedDict):
    id: str
    ncr_id: str
    supplier_id: str
    due_at: str
    status: str
    response_narrative: Optional[str]
    rejection_count: int
    created_at: str
    updated_at: str
    version: int


class InspectionPlan(TypedDict):
    id: str
    name: str
    control_plan_id: str
    part_number: str
    lot_size: int
    aql_pct: float
    inspection_level: str
    severity_mode: str
    consecutive_rejects: int
    needs_review: bool
    created_at: str
    updated_at: str
    version: int


class InspectionLot(TypedDict):
    id: str
    inspection_plan_id: str
    supplier_id: str
    actual_lot_size: int
    sample_size: int
    acceptance_number: int
    rejection_number: int
    defects_found: int
    severity_mode_used: str
    status: str
    inspected_by_personnel_id: str
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict):
    id: str
    title: str
    lead_auditor_id: str
    scheduled_from: str
    scheduled_to: str
    clause_scope: Optional[str]
    status: str
    open_finding_count: int
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    audit_id: str
    clause: str
    grade: str
    description: str
    status: str
    raised_ncr_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deviation(TypedDict):
    id: str
    ncr_id: str
    supplier_id: str
    part_number: str
    valid_from: str
    valid_to: str
    max_qty: int
    status: str
    approved_by_personnel_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ControlPlan(TypedDict):
    id: str
    name: str
    part_number: str
    current_revision_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ControlPlanRevision(TypedDict):
    id: str
    control_plan_id: str
    revision_no: int
    change_summary: str
    source_capa_id: Optional[str]
    status: str
    approved_by_personnel_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
