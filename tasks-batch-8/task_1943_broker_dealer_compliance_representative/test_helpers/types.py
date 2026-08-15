"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    COMPLIANCE_PRINCIPAL = "CompliancePrincipal"
    REGISTERED_REP = "RegisteredRep"
    ANY = "Any"


class RepresentativeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class SupervisionTier(str, Enum):
    STANDARD = "STANDARD"
    HEIGHTENED = "HEIGHTENED"


class BranchPosture(str, Enum):
    NORMAL = "NORMAL"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_REMEDIATION = "AWAITING_REMEDIATION"
    CLOSED = "CLOSED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"


class FindingSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CorrespondenceStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    APPROVED = "APPROVED"
    FLAGGED = "FLAGGED"


class CorrespondenceChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    PAPER_LETTER = "PAPER_LETTER"


class ActivityType(str, Enum):
    OUTSIDE_BUSINESS_ACTIVITY = "OUTSIDE_BUSINESS_ACTIVITY"
    PRIVATE_SECURITIES_TRANSACTION = "PRIVATE_SECURITIES_TRANSACTION"


class ActivityStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"
    SUSPENDED_REVIEW = "SUSPENDED_REVIEW"


class AllegationType(str, Enum):
    FORGERY = "FORGERY"
    THEFT = "THEFT"
    MISREPRESENTATION = "MISREPRESENTATION"
    SUITABILITY = "SUITABILITY"
    UNAUTHORIZED_TRADING = "UNAUTHORIZED_TRADING"
    OTHER = "OTHER"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RESOLVED = "RESOLVED"


class RegulatoryStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    FILED = "FILED"


class DisclosureEventType(str, Enum):
    FELONY_CONVICTION = "FELONY_CONVICTION"
    SECURITIES_MISDEMEANOR = "SECURITIES_MISDEMEANOR"
    REGULATORY_BAR = "REGULATORY_BAR"
    CUSTOMER_AWARD = "CUSTOMER_AWARD"
    CIVIL_JUDGMENT = "CIVIL_JUDGMENT"
    BANKRUPTCY = "BANKRUPTCY"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"


class PlanTerminatedReason(str, Enum):
    MANUAL = "MANUAL"
    REP_TERMINATED = "REP_TERMINATED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CLOSED = "CLOSED"


class AttestationStatus(str, Enum):
    PENDING = "PENDING"
    ATTESTED = "ATTESTED"
    OVERDUE = "OVERDUE"


class WspPolicyArea(str, Enum):
    CORRESPONDENCE = "CORRESPONDENCE"
    OBA_PST = "OBA_PST"
    COMPLAINTS = "COMPLAINTS"
    DISCLOSURE = "DISCLOSURE"
    HEIGHTENED_SUPERVISION = "HEIGHTENED_SUPERVISION"
    INSPECTIONS = "INSPECTIONS"
    BOOKS_RECORDS = "BOOKS_RECORDS"


class WspStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ExamRegulator(str, Enum):
    SEC = "SEC"
    FINRA = "FINRA"
    STATE = "STATE"


class ExamDocumentType(str, Enum):
    TRADE_BLOTTER = "TRADE_BLOTTER"
    CORRESPONDENCE_LOG = "CORRESPONDENCE_LOG"
    COMPLAINT_FILE = "COMPLAINT_FILE"
    WSP_COPY = "WSP_COPY"
    OBA_REGISTER = "OBA_REGISTER"


class ExamRequestStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    FULFILLED = "FULFILLED"


# All resources carry the PRD §2.4 common fields: id, created_at, updated_at, version.


class BranchOffice(TypedDict, total=False):
    id: str
    name: str
    region: str
    inspection_cycle_months: int
    open_findings_count: int
    high_severity_open_count: int
    sd_rep_count: int
    posture: str
    risk_score: int
    next_inspection_due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegisteredRepresentative(TypedDict, total=False):
    id: str
    branch_id: str
    crd_number: str
    full_name: str
    hire_date: str
    status: str
    is_statutorily_disqualified: bool
    supervision_tier: str
    compliance_flag_count: int
    active_approved_activity_count: int
    pst_fee_total_cents: int
    created_at: str
    updated_at: str
    version: int


class BranchInspection(TypedDict, total=False):
    id: str
    branch_id: str
    scheduled_date: str
    started_at: Optional[str]
    completed_date: Optional[str]
    open_findings_count: int
    high_severity_open_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionFinding(TypedDict, total=False):
    id: str
    inspection_id: str
    severity: str
    description: str
    due_date: str
    remediation_note: Optional[str]
    adjudication_note: Optional[str]
    reopen_count: int
    verified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrespondenceItem(TypedDict, total=False):
    id: str
    rep_id: str
    channel: str
    subject: str
    body_excerpt: str
    lexicon_hits: int
    captured_at: str
    review_deadline: str
    provisional_risk_score: int
    final_risk_score: Optional[int]
    reviewed_by: Optional[str]
    escalated_by: Optional[str]
    resolved_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutsideActivityRequest(TypedDict, total=False):
    id: str
    rep_id: str
    activity_type: str
    description: str
    compensation_expected: bool
    estimated_gross_comp_cents: Optional[int]
    start_date: str
    conditions: Optional[list]
    supervisory_fee_cents: Optional[int]
    decided_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerComplaint(TypedDict, total=False):
    id: str
    rep_id: str
    allegation_type: str
    damages_claimed_cents: int
    received_date: str
    description: str
    reportable: bool
    report_deadline: str
    provisional_reserve_cents: int
    final_reserve_cents: Optional[int]
    damages_paid_cents: Optional[int]
    legal_cost_cents: Optional[int]
    reported_at: Optional[str]
    is_late_report: Optional[bool]
    status: str
    regulatory_status: str
    created_at: str
    updated_at: str
    version: int


class DisclosureEvent(TypedDict, total=False):
    id: str
    rep_id: str
    event_type: str
    event_date: str
    description: str
    is_sd_trigger: bool
    filing_deadline: str
    filed_at: Optional[str]
    is_late: Optional[bool]
    source_complaint_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HeightenedSupervisionPlan(TypedDict, total=False):
    id: str
    rep_id: str
    start_date: str
    end_date: str
    conditions: list
    terminated_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceMeeting(TypedDict, total=False):
    id: str
    year: int
    meeting_date: str
    held_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Attestation(TypedDict, total=False):
    id: str
    meeting_id: str
    rep_id: str
    attest_deadline: str
    attested_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WSPDocument(TypedDict, total=False):
    id: str
    policy_area: str
    title: str
    effective_date: str
    version_number: int
    drafted_by: str
    published_by: Optional[str]
    supersedes_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExamDocumentRequest(TypedDict, total=False):
    id: str
    regulator: str
    request_ref: str
    document_type: str
    branch_id: Optional[str]
    due_date: str
    produced_document_ref: Optional[str]
    fulfilled_at: Optional[str]
    is_late: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int
