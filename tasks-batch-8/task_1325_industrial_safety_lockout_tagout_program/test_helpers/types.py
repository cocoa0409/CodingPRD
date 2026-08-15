"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    EHS_MANAGER = "EHSManager"
    EHS_AUDITOR = "EHSAuditor"
    AUTHORIZED_EMPLOYEE = "AuthorizedEmployee"


class MachineStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RiskWindowPolicy(str, Enum):
    ROLLING_12MO = "ROLLING_12MO"
    SINCE_PROCEDURE_ACTIVATION = "SINCE_PROCEDURE_ACTIVATION"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReviewStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"


class Qualification(str, Enum):
    AFFECTED = "AFFECTED"
    AUTHORIZED = "AUTHORIZED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"


class SurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProcedureStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVISION = "UNDER_REVISION"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class CourseCode(str, Enum):
    LOTO_AUTHORIZED_INITIAL = "LOTO_AUTHORIZED_INITIAL"
    LOTO_AUTHORIZED_REFRESH = "LOTO_AUTHORIZED_REFRESH"
    LOTO_AFFECTED = "LOTO_AFFECTED"


class DeliveryMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    ONLINE = "ONLINE"


class TrainingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"


class SessionStatus(str, Enum):
    SETUP = "SETUP"
    LOCKED = "LOCKED"
    CLEARED = "CLEARED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class SessionType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"
    CONTRACTOR = "CONTRACTOR"


class LockStatus(str, Enum):
    ISSUED = "ISSUED"
    APPLIED = "APPLIED"
    REMOVED = "REMOVED"
    FORCE_REMOVED = "FORCE_REMOVED"
    VOIDED = "VOIDED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class IncidentKind(str, Enum):
    NEAR_MISS = "NEAR_MISS"
    FIRST_AID = "FIRST_AID"
    INJURY = "INJURY"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    LINKED = "LINKED"
    DISMISSED = "DISMISSED"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class ExceptionStatus(str, Enum):
    PENDING = "PENDING"
    DETERMINED = "DETERMINED"
    REVOKED = "REVOKED"


class Determination(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# All primary resources carry id / created_at / updated_at / version (PRD §2.5).
# ---------------------------------------------------------------------------

class Machine(TypedDict):
    id: str
    asset_tag: str
    name: str
    area: str
    risk_window_policy: str
    status: str
    risk_score: int
    risk_tier: str
    open_session_count: int
    created_at: str
    updated_at: str
    version: int


class MachineModification(TypedDict):
    # Append-only log (PRD §2.5): carries ONLY id and created_at of the common
    # fields — no updated_at, no version.
    id: str
    created_at: str
    machine_id: str
    description: str
    review_status: str


class Employee(TypedDict):
    id: str
    employee_no: str
    full_name: str
    qualification: str
    status: str
    is_currently_qualified: bool
    outstanding_lock_count: int
    created_at: str
    updated_at: str
    version: int


class EnergySource(TypedDict):
    source_type: str
    magnitude: str
    isolation_point: str
    dissipation_method: str


class EnergySurvey(TypedDict):
    id: str
    machine_id: str
    surveyed_by_employee_id: str
    energy_sources: List[EnergySource]
    isolation_point_count: int
    note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcedureStep(TypedDict):
    step_no: int
    action: str
    isolation_point: str


class LockoutProcedure(TypedDict):
    id: str
    machine_id: str
    survey_id: str
    steps: List[ProcedureStep]
    revision_no: int
    isolation_point_count: int
    status: str
    activated_at: Optional[str]
    last_completed_audit_at: Optional[str]
    audit_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict):
    id: str
    employee_id: str
    course_code: str
    delivery_mode: str
    assigned_at: str
    due_at: str
    completed_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LockoutSession(TypedDict):
    id: str
    machine_id: str
    procedure_id: str
    procedure_revision_no: int
    max_locks: int
    session_type: str
    primary_employee_id: str
    zero_energy_verified: bool
    applied_lock_count: int
    started_at: Optional[str]
    ended_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EmployeeLock(TypedDict):
    id: str
    session_id: str
    employee_id: str
    lock_no: str
    tag_no: str
    applied_at: Optional[str]
    removed_at: Optional[str]
    removal_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcedureAudit(TypedDict):
    id: str
    procedure_id: str
    auditor_employee_id: str
    scheduled_start: str
    scheduled_end: str
    period_start: str
    result: Optional[str]
    employees_sampled: Optional[List[str]]
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    machine_id: str
    session_id: Optional[str]
    kind: str
    occurred_at: str
    severity: int
    description: Optional[str]
    linked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractorPermit(TypedDict):
    id: str
    machine_id: str
    company_name: str
    coordinator_employee_id: str
    insurance_valid_until: str
    coordination_meeting_at: Optional[str]
    session_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MinorServicingException(TypedDict):
    id: str
    machine_id: str
    requested_by_employee_id: str
    task_description: str
    routine_repetitive: bool
    integral_to_production: bool
    alternative_measures_effective: bool
    estimated_duration_min: int
    valid_from: str
    valid_until: str
    determination: Optional[str]
    determined_by_employee_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
