"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class CodeVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class SupplierStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    TERMINATED = "TERMINATED"


class SupplierSector(str, Enum):
    APPAREL = "APPAREL"
    ELECTRONICS = "ELECTRONICS"
    FOOD = "FOOD"
    HARDLINES = "HARDLINES"


class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConsequenceTier(str, Enum):
    PREFERRED = "PREFERRED"
    QUALIFIED = "QUALIFIED"
    PROBATION_WATCH = "PROBATION_WATCH"
    SOURCING_EXIT = "SOURCING_EXIT"


class AuditorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    REPORT_SUBMITTED = "REPORT_SUBMITTED"
    COMPLETED = "COMPLETED"
    FAILED_ZT = "FAILED_ZT"
    CANCELLED = "CANCELLED"


class AuditType(str, Enum):
    INITIAL = "INITIAL"
    ANNUAL = "ANNUAL"
    RE_AUDIT = "RE_AUDIT"
    FOLLOW_UP = "FOLLOW_UP"


class Announcement(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    SEMI_ANNOUNCED = "SEMI_ANNOUNCED"


class FindingClassification(str, Enum):
    ZERO_TOLERANCE = "ZERO_TOLERANCE"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class FindingCategory(str, Enum):
    FORCED_LABOR = "FORCED_LABOR"
    CHILD_LABOR = "CHILD_LABOR"
    WORKING_HOURS = "WORKING_HOURS"
    WAGES = "WAGES"
    HEALTH_SAFETY = "HEALTH_SAFETY"
    ENVIRONMENT = "ENVIRONMENT"
    HARASSMENT = "HARASSMENT"
    RECRUITMENT_FEES = "RECRUITMENT_FEES"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    VOIDED = "VOIDED"


class CapStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VERIFICATION_REQUESTED = "VERIFICATION_REQUESTED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFIED_PASSED = "VERIFIED_PASSED"


class GrievanceChannel(str, Enum):
    HOTLINE = "HOTLINE"
    WORKER_COMMITTEE = "WORKER_COMMITTEE"
    AUDIT_INTERVIEW = "AUDIT_INTERVIEW"


class GrievanceCategory(str, Enum):
    WAGES = "WAGES"
    HARASSMENT = "HARASSMENT"
    FORCED_LABOR = "FORCED_LABOR"
    SAFETY = "SAFETY"
    RECRUITMENT_FEES = "RECRUITMENT_FEES"
    OTHER = "OTHER"


class GrievanceSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class GrievanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ReviewStatus(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    VIOLATION_CONFIRMED = "VIOLATION_CONFIRMED"
    REIMBURSED = "REIMBURSED"
    CLEARED = "CLEARED"


class ReimbursementStatus(str, Enum):
    RECORDED = "RECORDED"
    REVERSED = "REVERSED"


class ProgramName(str, Enum):
    BSCI = "BSCI"
    SMETA = "SMETA"
    RBA = "RBA"
    WRAP = "WRAP"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    SOURCING_PROGRAM_ADMIN = "SourcingProgramAdmin"
    AUDIT_COORDINATOR = "AuditCoordinator"
    AUDITOR = "Auditor"
    SUPPLIER_CONTACT = "SupplierContact"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    WORKER_HOTLINE = "WorkerHotline"


# ---------------------------------------------------------------------------
# Entity shapes (mutable resources carry id + created_at + updated_at +
# version; the two immutable registration records carry only id + created_at)
# ---------------------------------------------------------------------------

class CodeVersion(TypedDict):
    id: str
    version_label: str
    effective_from: str
    zero_tolerance_categories: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    legal_name: str
    country_code: str
    sector: str
    status: str
    current_code_version_id: Optional[str]
    provisional_score: int
    verified_score: int
    consequence_tier: str
    escalation_penalty_points: int
    created_at: str
    updated_at: str
    version: int


class CodeAcknowledgment(TypedDict):
    # Immutable registration record: no updated_at, no version (PRD §2.4).
    id: str
    supplier_id: str
    code_version_id: str
    signer_name: str
    signer_title: str
    acknowledged_at: str
    supersedes_acknowledgment_id: Optional[str]
    created_at: str


class Facility(TypedDict):
    id: str
    supplier_id: str
    name: str
    country_code: str
    worker_count: int
    processes: List[str]
    status: str
    risk_score_baseline: float
    risk_score_history: Optional[float]
    risk_tier: str
    next_audit_interval_months: int
    next_audit_due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Auditor(TypedDict):
    id: str
    full_name: str
    firm_name: str
    certifications: List[str]
    country_codes_covered: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict):
    id: str
    facility_id: str
    auditor_id: str
    audit_type: str
    announcement: str
    scheduled_start: str
    scheduled_end: str
    status: str
    zt_count: int
    major_count: int
    minor_count: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict):
    id: str
    audit_id: str
    classification: str
    category: str
    description: str
    status: str
    remediation_due_date: str
    void_justification: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict):
    id: str
    finding_id: str
    supplier_id: str
    actions: List[dict]
    status: str
    rejection_reason: Optional[str]
    escalation_count: int
    verified_by_auditor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Grievance(TypedDict):
    id: str
    facility_id: str
    channel: str
    category: str
    severity: str
    description: str
    is_anonymized: bool
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkerInterviewRecord(TypedDict):
    # Immutable registration record: no updated_at, no version (PRD §2.4).
    id: str
    audit_id: str
    interview_count: int
    forced_labor_indicators: bool
    recruitment_fee_indicators: bool
    notes: Optional[str]
    created_at: str


class RecruitmentFeeReview(TypedDict):
    id: str
    audit_id: str
    workers_assessed: int
    fee_items: List[dict]
    linked_grievance_id: Optional[str]
    total_reimbursement_cents: int
    reimbursed_cents: int
    outstanding_reimbursement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reimbursement(TypedDict):
    id: str
    review_id: str
    amount_cents: int
    worker_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MutualRecognitionClaim(TypedDict):
    id: str
    facility_id: str
    program_name: str
    external_audit_ref: str
    external_audit_date: str
    external_score: float
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
