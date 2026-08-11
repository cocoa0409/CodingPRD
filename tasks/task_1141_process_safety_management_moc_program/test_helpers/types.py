"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PSM_ADMIN = "PsmAdmin"
    PSM_MANAGER = "PsmManager"
    REQUESTER = "Requester"
    TECHNICAL_REVIEWER = "TechnicalReviewer"
    OPS_APPROVER = "OpsApprover"
    PSSR_LEAD = "PssrLead"
    INVESTIGATOR = "Investigator"
    AUDITOR = "Auditor"
    TRAINING_COORDINATOR = "TrainingCoordinator"


class Qualification(str, Enum):
    MECHANICAL = "MECHANICAL"
    CHEMICAL = "CHEMICAL"
    ELECTRICAL = "ELECTRICAL"
    PROCESS = "PROCESS"
    HAZOP_LEADER = "HAZOP_LEADER"
    PSSR_CERTIFIED = "PSSR_CERTIFIED"


class Discipline(str, Enum):
    MECHANICAL = "MECHANICAL"
    CHEMICAL = "CHEMICAL"
    ELECTRICAL = "ELECTRICAL"
    PROCESS = "PROCESS"


class ChangeClass(str, Enum):
    REPLACEMENT_IN_KIND = "REPLACEMENT_IN_KIND"
    TEMPORARY = "TEMPORARY"
    PERMANENT = "PERMANENT"


class RiskRank(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Posture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class MocStatus(str, Enum):
    DRAFT = "DRAFT"
    CLASSIFIED = "CLASSIFIED"
    TECHNICAL_REVIEW = "TECHNICAL_REVIEW"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED_IMPLEMENTATION = "APPROVED_IMPLEMENTATION"
    IMPLEMENTED_PSSR_PENDING = "IMPLEMENTED_PSSR_PENDING"
    STARTUP_AUTHORIZED = "STARTUP_AUTHORIZED"
    IN_SERVICE = "IN_SERVICE"
    EXPIRED_REVERT_REQUIRED = "EXPIRED_REVERT_REQUIRED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"


class PhaStudyStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    IN_REVALIDATION = "IN_REVALIDATION"


class RevalidationStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class PssrStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_FIELD = "IN_FIELD"
    PUNCH_LIST = "PUNCH_LIST"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOID = "VOID"


class ActionItemStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED_FOR_VERIFICATION = "SUBMITTED_FOR_VERIFICATION"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    REJECTED = "REJECTED"
    VOID = "VOID"


class ActionItemSource(str, Enum):
    MANUAL = "MANUAL"
    MOC_CONDITION = "MOC_CONDITION"
    PSSR = "PSSR"
    PHA_REVALIDATION = "PHA_REVALIDATION"
    INCIDENT = "INCIDENT"
    AUDIT = "AUDIT"
    REVERT = "REVERT"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ROOT_CAUSE_ANALYSIS = "ROOT_CAUSE_ANALYSIS"
    FINDINGS_SUBMITTED = "FINDINGS_SUBMITTED"
    CLOSED = "CLOSED"


class SeverityClass(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    HIGH = "HIGH"
    CATASTROPHIC = "CATASTROPHIC"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FIELDWORK = "FIELDWORK"
    REPORTED = "REPORTED"
    CLOSED = "CLOSED"


class FindingSeverity(str, Enum):
    OBSERVATION = "OBSERVATION"
    MINOR_NC = "MINOR_NC"
    MAJOR_NC = "MAJOR_NC"


class AuditFindingStatus(str, Enum):
    OPEN = "OPEN"
    ACTION_ASSIGNED = "ACTION_ASSIGNED"
    CLOSED = "CLOSED"


class ProcedureUpdateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class TrainingAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"


class ExtensionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    VOID = "VOID"


class Verdict(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


# --- Entity TypedDicts (common_fields entities carry id/created_at/updated_at/version) ---


class PlantUnit(TypedDict, total=False):
    id: str
    name: str
    unit_code: str
    pha_cycle_months: int
    temp_moc_max_days: int
    max_extensions: int
    extension_max_days: int
    total_temp_cap_days: int
    training_coverage_threshold_pct: float
    open_action_count: int
    overdue_action_count: int
    process_safety_index: int
    psm_posture: str
    created_at: str
    updated_at: str
    version: int


class Personnel(TypedDict, total=False):
    id: str
    full_name: str
    employee_ref: str
    qualifications: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class MocRequest(TypedDict, total=False):
    id: str
    unit_id: str
    title: str
    description: str
    discipline: str
    requester_id: str
    approver_id: Optional[str]
    status: str
    change_class: Optional[str]
    screening_severity: Optional[int]
    screening_likelihood: Optional[int]
    screening_risk_score: Optional[float]
    definitive_risk_score: Optional[float]
    risk_rank: Optional[str]
    review_round: int
    requires_pssr: Optional[bool]
    temporary_start_date: Optional[str]
    temporary_duration_days: Optional[int]
    temporary_end_date: Optional[str]
    extension_count: int
    total_approved_extension_days: int
    training_coverage_pct: Optional[float]
    implemented_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TechnicalReview(TypedDict, total=False):
    id: str
    moc_id: str
    round_number: int
    reviewer_id: Optional[str]
    status: str
    design_basis_ok: Optional[bool]
    codes_standards_ok: Optional[bool]
    relief_systems_ok: Optional[bool]
    materials_compat_ok: Optional[bool]
    severity_score: Optional[int]
    likelihood_score: Optional[int]
    detection_score: Optional[int]
    verdict: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhaStudy(TypedDict, total=False):
    id: str
    unit_id: str
    method: str
    status: str
    last_validated_at: str
    nominal_next_due: str
    risk_accelerated_due: str
    effective_next_due: str
    revalidation_count: int
    status_before_revalidation: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhaRevalidation(TypedDict, total=False):
    id: str
    study_id: str
    leader_id: str
    status: str
    findings_summary: Optional[str]
    findings: List[dict]
    created_at: str
    updated_at: str
    version: int


class Pssr(TypedDict, total=False):
    id: str
    moc_id: str
    lead_id: str
    status: str
    field_window_start: str
    field_window_end: str
    punch_open_count: int
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActionItem(TypedDict, total=False):
    id: str
    unit_id: str
    source_type: str
    source_id: Optional[str]
    title: str
    priority: str
    assignee_id: str
    due_date: str
    status: str
    completer_id: Optional[str]
    verifier_id: Optional[str]
    evidence_count: int
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    """Append-only: carries ONLY id + created_at (no updated_at, no version)."""

    id: str
    action_item_id: str
    file_ref: str
    description: str
    uploaded_by: str
    created_at: str


class IncidentInvestigation(TypedDict, total=False):
    id: str
    unit_id: str
    title: str
    severity_class: str
    occurred_at: str
    investigator_id: str
    status: str
    feeds_pha: bool
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict, total=False):
    id: str
    unit_id: str
    title: str
    lead_auditor_id: str
    field_window_start: str
    field_window_end: str
    status: str
    open_finding_count: int
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    audit_id: str
    title: str
    severity: str
    status: str
    corrective_action_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcedureUpdate(TypedDict, total=False):
    id: str
    moc_id: str
    document_ref: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict, total=False):
    id: str
    procedure_update_id: str
    personnel_id: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict, total=False):
    id: str
    moc_id: str
    requested_days: int
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
