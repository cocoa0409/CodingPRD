"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    SAFETY_MANAGER = "SafetyManager"
    SITE_SUPERINTENDENT = "SiteSuperintendent"
    SAFETY_INSPECTOR = "SafetyInspector"
    SUBCONTRACTOR_REP = "SubcontractorRep"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


# ─── Enumerations (PRD §3) ───────────────────────────────────────────────────

class Posture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class WorkerStatus(str, Enum):
    PENDING_ORIENTATION = "PENDING_ORIENTATION"
    ORIENTED = "ORIENTED"
    CLEARED = "CLEARED"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class EmployerType(str, Enum):
    DIRECT = "DIRECT"
    SUBCONTRACTOR = "SUBCONTRACTOR"


class CertType(str, Enum):
    OSHA_10 = "OSHA_10"
    OSHA_30 = "OSHA_30"
    FIRST_AID = "FIRST_AID"
    FLAGGING = "FLAGGING"


class CertificateStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class Standing(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    REMOVED = "REMOVED"


class HuddleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    MISSED = "MISSED"


class JhaStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RE_REVIEW_REQUIRED = "RE_REVIEW_REQUIRED"


class InspectionType(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    QUARTERLY_REGULATORY = "QUARTERLY_REGULATORY"


class InspectionStatus(str, Enum):
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"


class DeficiencySeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"
    IMMINENT_DANGER = "IMMINENT_DANGER"


class DeficiencyStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    CORRECTION_SUBMITTED = "CORRECTION_SUBMITTED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"


class ClosedDisposition(str, Enum):
    CONFIRMED = "CONFIRMED"
    NOT_SUB_FAULT = "NOT_SUB_FAULT"


class IncidentType(str, Enum):
    INJURY = "INJURY"
    ILLNESS = "ILLNESS"
    NEAR_MISS = "NEAR_MISS"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    CRITICAL = "CRITICAL"
    FATALITY = "FATALITY"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    DETERMINATION_MADE = "DETERMINATION_MADE"
    CLOSED = "CLOSED"


class PermitType(str, Enum):
    FALL_PROTECTION = "FALL_PROTECTION"
    EXCAVATION = "EXCAVATION"
    HOT_WORK = "HOT_WORK"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class DrugTestType(str, Enum):
    PRE_EMPLOYMENT = "PRE_EMPLOYMENT"
    RANDOM = "RANDOM"
    POST_INCIDENT = "POST_INCIDENT"


class DrugTestStatus(str, Enum):
    PENDING_RESULT = "PENDING_RESULT"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class ProbationAction(str, Enum):
    DEMOTE = "DEMOTE"
    RESTORE = "RESTORE"


class VerifyOutcome(str, Enum):
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class DrugResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# All resources carry the standard system-managed fields of PRD §2.4
# (id, created_at, updated_at, version).

class Project(TypedDict, total=False):
    id: str
    name: str
    location: str
    annual_hours_worked: int
    safety_posture: str
    current_active_plan_id: Optional[str]
    issued_permit_count: int
    open_deficiency_count: int
    created_at: str
    updated_at: str
    version: int


class SafetyPlan(TypedDict, total=False):
    id: str
    project_id: str
    effective_date: str
    revision_notes: str
    revision_no: int
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict, total=False):
    id: str
    project_id: str
    full_name: str
    employer_type: str
    subcontractor_id: Optional[str]
    is_supervisor: bool
    status: str
    orientation_completed_at: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingCertificate(TypedDict, total=False):
    id: str
    worker_id: str
    cert_type: str
    issued_date: str
    expires_date: str
    status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict, total=False):
    id: str
    project_id: str
    company_name: str
    trade: str
    standing: str
    compliance_score_realtime: int
    compliance_score_period_90d: int
    created_at: str
    updated_at: str
    version: int


class Huddle(TypedDict, total=False):
    id: str
    project_id: str
    huddle_date: str
    topics: str
    status: str
    attendee_worker_ids: List[str]
    conducted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JobHazardAnalysis(TypedDict, total=False):
    id: str
    project_id: str
    huddle_id: str
    task_description: str
    hazards: str
    controls: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    project_id: str
    inspection_type: str
    due_date: str
    status: str
    completed_at: Optional[str]
    findings_summary: str
    created_at: str
    updated_at: str
    version: int


class Deficiency(TypedDict, total=False):
    id: str
    inspection_id: str
    project_id: str
    description: str
    severity: str
    assigned_subcontractor_id: Optional[str]
    due_at: str
    status: str
    correction_notes: str
    created_by_user_id: str
    verified_by_user_id: Optional[str]
    closed_disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    project_id: str
    worker_id: Optional[str]
    incident_type: str
    severity: str
    occurred_at: str
    work_related: bool
    description: str
    status: str
    investigator_user_id: Optional[str]
    investigation_notes: str
    medical_treatment_beyond_first_aid: bool
    days_away_from_work: int
    restricted_duty: bool
    loss_of_consciousness: bool
    significant_diagnosis: bool
    is_osha_recordable: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    project_id: str
    jha_id: str
    permit_type: str
    work_start: str
    work_end: str
    authorized_worker_ids: List[str]
    status: str
    suspension_reason: str
    created_at: str
    updated_at: str
    version: int


class DrugTestRecord(TypedDict, total=False):
    id: str
    worker_id: str
    test_type: str
    incident_id: Optional[str]
    collected_at: str
    status: str
    window_compliant: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class OshaSummary(TypedDict, total=False):
    year: int
    hours_worked: int
    recordable_count_final: int
    recordable_count_provisional: int
    dart_count_final: int
    dart_count_provisional: int
    trir_final: float
    trir_provisional: float
    dart_rate_final: float
    dart_rate_provisional: float
    rate_spread_final: float
