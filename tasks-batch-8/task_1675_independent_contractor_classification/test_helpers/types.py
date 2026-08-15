"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ENGAGEMENT_MANAGER = "EngagementManager"
    CLASSIFICATION_ANALYST = "ClassificationAnalyst"
    HR_APPROVER = "HRApprover"
    LEGAL_APPROVER = "LegalApprover"
    COMPLIANCE_BOARD_MEMBER = "ComplianceBoardMember"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TAX_REPORTING_SPECIALIST = "TaxReportingSpecialist"
    AGENCY_LIAISON = "AgencyLiaison"


class TestType(str, Enum):
    ABC_TEST = "ABC_TEST"
    COMMON_LAW_WEIGHTED = "COMMON_LAW_WEIGHTED"
    ECONOMIC_REALITY = "ECONOMIC_REALITY"


class EntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    SOLE_PROPRIETOR = "SOLE_PROPRIETOR"
    LLC = "LLC"
    S_CORP = "S_CORP"
    PARTNERSHIP = "PARTNERSHIP"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class StandingStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    SUSPENDED_STANDING = "SUSPENDED_STANDING"
    CONVERTED_TO_EMPLOYEE = "CONVERTED_TO_EMPLOYEE"


class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    INTAKE_SUBMITTED = "INTAKE_SUBMITTED"
    CLASSIFIED = "CLASSIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"
    CONVERTED = "CONVERTED"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class DeterminationOutcome(str, Enum):
    CONTRACTOR = "CONTRACTOR"
    EMPLOYEE_RISK = "EMPLOYEE_RISK"


class ExceptionGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class AmendmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CLOSED = "CLOSED"


class ReviewOutcome(str, Enum):
    CLEARED = "CLEARED"
    FINDINGS_FILED = "FINDINGS_FILED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_FINALIZED = "FINDINGS_FINALIZED"
    REMEDIATION = "REMEDIATION"
    CLOSED = "CLOSED"


class AuditType(str, Enum):
    SCREENING = "SCREENING"
    FIELDWORK = "FIELDWORK"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RemediationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    WAIVED = "WAIVED"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED_AGENCY = "REJECTED_AGENCY"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class FilingKind(str, Enum):
    ORIGINAL = "ORIGINAL"
    CORRECTION = "CORRECTION"


class InquiryStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    RESOLVED = "RESOLVED"
    AUDIT_OPENED = "AUDIT_OPENED"


class ConversionStatus(str, Enum):
    INITIATED = "INITIATED"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    RESCINDED = "RESCINDED"


# ─── Entity payloads ────────────────────────────────
# All primary resources carry id, created_at, updated_at, version (PRD §2.4).
# ClassificationDetermination is the sole exception: id + created_at only.


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    test_type: str
    employee_score_threshold: float
    state_filing_threshold_cents: int
    max_active_exceptions: int
    min_insurance_cents: int
    description: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict, total=False):
    id: str
    legal_name: str
    entity_type: str
    ein: str
    insurance_coverage_cents: int
    verification_status: str
    standing_status: str
    lifetime_reported_cents: int
    created_at: str
    updated_at: str
    version: int


class ApprovalEntry(TypedDict, total=False):
    role: str
    user_id: str
    decided_at: str


class Engagement(TypedDict, total=False):
    id: str
    contractor_id: str
    jurisdiction_id: str
    title: str
    scope_description: str
    agreed_rate_cents: int
    rate_unit: str
    start_date: str
    end_date: str
    supervision_level: str
    status: str
    risk_tier: Optional[str]
    required_approval_count: int
    approvals_recorded: List[ApprovalEntry]
    current_determination_id: Optional[str]
    scope_creep_index: int
    scope_creep_tier: str
    created_at: str
    updated_at: str
    version: int


class IntakeQuestionnaire(TypedDict, total=False):
    id: str
    engagement_id: str
    answers: List[dict]
    revision: int
    complete: bool
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class ClassificationDetermination(TypedDict, total=False):
    # Append-only record: carries only id + created_at; no updated_at, no version.
    id: str
    engagement_id: str
    jurisdiction_test_type: str
    questionnaire_revision: int
    outcome: str
    score: float
    failed_prongs: int
    superseded: bool
    created_at: str


class ExceptionGrant(TypedDict, total=False):
    id: str
    engagement_id: str
    justification: str
    expires_at: str
    granted_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractAgreement(TypedDict, total=False):
    id: str
    engagement_id: str
    contractor_id: str
    jurisdiction_id: str
    start_date: str
    end_date: str
    rate_cents: int
    rate_unit: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractAmendment(TypedDict, total=False):
    id: str
    contract_id: str
    new_rate_cents: Optional[int]
    new_end_date: Optional[str]
    scope_change_summary: str
    exception_grant_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringReview(TypedDict, total=False):
    id: str
    engagement_id: str
    scheduled_date: str
    findings: List[dict]
    remediation_action_ids: List[str]
    findings_count: int
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RiskAudit(TypedDict, total=False):
    id: str
    contractor_id: str
    engagement_id: Optional[str]
    audit_type: str
    provisional_risk_score: float
    final_risk_score: Optional[float]
    risk_level: str
    open_action_count: int
    findings_summary: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RemediationAction(TypedDict, total=False):
    id: str
    audit_id: str
    description: str
    severity: str
    due_date: str
    status: str
    close_note: str
    created_at: str
    updated_at: str
    version: int


class TaxForm1099Filing(TypedDict, total=False):
    id: str
    contractor_id: str
    state_jurisdiction_id: str
    tax_year: int
    kind: str
    corrects_filing_id: Optional[str]
    payment_line_items: List[dict]
    reportable_amount_cents: int
    federal_filing_required: bool
    state_filing_required: bool
    signed_amount_cents: int
    filed_at: Optional[str]
    days_late: int
    penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgencyInquiry(TypedDict, total=False):
    id: str
    engagement_id: str
    agency_type: str
    received_at: str
    response_deadline: str
    back_payments_cents: int
    quarters_outstanding: int
    exposure_estimate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConversionCase(TypedDict, total=False):
    id: str
    engagement_id: str
    lookback_quarters: List[dict]
    w2_equivalent_total_cents: int
    lookback_delta_cents: int
    offer_salary_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
