"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    PATIENT_ADVOCATE = "PatientAdvocate"
    DEPARTMENT_INVESTIGATOR = "DepartmentInvestigator"
    QUALITY_RISK_OFFICER = "QualityRiskOfficer"
    PATIENT_RELATIONS_DIRECTOR = "PatientRelationsDirector"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------
class UnitCategory(str, Enum):
    INPATIENT = "INPATIENT"
    EMERGENCY = "EMERGENCY"
    OUTPATIENT = "OUTPATIENT"
    SURGICAL = "SURGICAL"
    ICU = "ICU"
    OTHER = "OTHER"


class UnitPosture(str, Enum):
    STANDARD = "STANDARD"
    RESTRICTED = "RESTRICTED"


class Capability(str, Enum):
    ADVOCATE = "ADVOCATE"
    INVESTIGATOR = "INVESTIGATOR"
    QRO = "QRO"
    DIRECTOR = "DIRECTOR"


class Channel(str, Enum):
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    PORTAL = "PORTAL"
    IN_PERSON = "IN_PERSON"
    LETTER = "LETTER"


class GrievanceCategory(str, Enum):
    BILLING = "BILLING"
    CARE_QUALITY = "CARE_QUALITY"
    STAFF_CONDUCT = "STAFF_CONDUCT"
    ACCESS_DELAY = "ACCESS_DELAY"
    RIGHTS_ABUSE = "RIGHTS_ABUSE"
    COMMUNICATION = "COMMUNICATION"
    OTHER = "OTHER"


class SeverityTier(str, Enum):
    STANDARD = "STANDARD"
    URGENT = "URGENT"
    CRITICAL = "CRITICAL"


class Classification(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    COMPLAINT = "COMPLAINT"
    GRIEVANCE = "GRIEVANCE"


class LifecycleStatus(str, Enum):
    INTAKE = "INTAKE"
    CLASSIFIED = "CLASSIFIED"
    ASSIGNED = "ASSIGNED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    FINDINGS_REVIEW = "FINDINGS_REVIEW"
    RESPONSE_DRAFTING = "RESPONSE_DRAFTING"
    RESPONSE_REVIEW = "RESPONSE_REVIEW"
    PENDING_CLOSURE = "PENDING_CLOSURE"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    WITHDRAWN = "WITHDRAWN"


class RegulatoryClockStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    ACK_BREACH = "ACK_BREACH"
    RESPONSE_BREACH = "RESPONSE_BREACH"
    SUSPENDED = "SUSPENDED"


class ResolutionTimeliness(str, Enum):
    NA = "NA"
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class DecisionValue(str, Enum):
    COMPLAINT = "COMPLAINT"
    GRIEVANCE = "GRIEVANCE"


class RationaleCode(str, Enum):
    INITIAL_INTAKE = "INITIAL_INTAKE"
    PATIENT_REQUEST = "PATIENT_REQUEST"
    ESCALATION_OF_CONCERN = "ESCALATION_OF_CONCERN"
    REGULATORY_REVIEW = "REGULATORY_REVIEW"
    DIRECTOR_OVERRIDE = "DIRECTOR_OVERRIDE"


class AssignmentRole(str, Enum):
    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_SUBMITTED = "FINDINGS_SUBMITTED"
    FINDINGS_ACCEPTED = "FINDINGS_ACCEPTED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


class NoteType(str, Enum):
    INTERVIEW = "INTERVIEW"
    DOCUMENT_REVIEW = "DOCUMENT_REVIEW"
    SITE_VISIT = "SITE_VISIT"
    PHONE_CALL = "PHONE_CALL"


class LetterStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class LetterSection(str, Enum):
    PATIENT_SUMMARY = "PATIENT_SUMMARY"
    INVESTIGATION_STEPS = "INVESTIGATION_STEPS"
    FINDINGS = "FINDINGS"
    RESOLUTION = "RESOLUTION"
    CONTACT_INFO = "CONTACT_INFO"
    RISK_DISCLOSURE = "RISK_DISCLOSURE"
    QAPI_REFERENCE = "QAPI_REFERENCE"


class RecoveryActionType(str, Enum):
    MEAL_VOUCHER = "MEAL_VOUCHER"
    PARKING_COMP = "PARKING_COMP"
    BILL_ADJUSTMENT = "BILL_ADJUSTMENT"
    GOODWILL_GESTURE = "GOODWILL_GESTURE"
    EXPEDITED_APPOINTMENT = "EXPEDITED_APPOINTMENT"


class RecoveryStatus(str, Enum):
    ISSUED = "ISSUED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class EscalationType(str, Enum):
    CARE_CONCERN = "CARE_CONCERN"
    SYSTEMIC = "SYSTEMIC"


class EscalationSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_CARE_FLAG = "AUTO_CARE_FLAG"
    AUTO_SYSTEMIC_THRESHOLD = "AUTO_SYSTEMIC_THRESHOLD"


class EscalationStatus(str, Enum):
    FILED = "FILED"
    IN_REVIEW = "IN_REVIEW"
    REVIEWS_COMPLETE = "REVIEWS_COMPLETE"
    ADJUDICATED_SUBSTANTIATED = "ADJUDICATED_SUBSTANTIATED"
    ADJUDICATED_UNSUBSTANTIATED = "ADJUDICATED_UNSUBSTANTIATED"


class ReviewTrack(str, Enum):
    COMPLIANCE = "COMPLIANCE"
    SAFETY = "SAFETY"
    BOTH = "BOTH"


class ReviewBranch(str, Enum):
    COMPLIANCE = "COMPLIANCE"
    SAFETY = "SAFETY"


class AdjudicationOutcome(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class AuthorityCode(str, Enum):
    STATE_HEALTH_DEPT = "STATE_HEALTH_DEPT"
    CMS_REGIONAL = "CMS_REGIONAL"
    ACCREDITATION_BODY = "ACCREDITATION_BODY"


class TriggerReason(str, Enum):
    ALLEGED_ABUSE = "ALLEGED_ABUSE"
    SUBSTANTIATED_CARE_CONCERN = "SUBSTANTIATED_CARE_CONCERN"
    SYSTEMIC_ISSUE = "SYSTEMIC_ISSUE"


class EventStatus(str, Enum):
    PENDING_FILING = "PENDING_FILING"
    FILED = "FILED"
    LATE_FILED = "LATE_FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class RoundingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class FollowUpStatus(str, Enum):
    PENDING = "PENDING"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"


class SuspensionReason(str, Enum):
    AWAITING_PATIENT = "AWAITING_PATIENT"
    AWAITING_FAMILY = "AWAITING_FAMILY"
    AWAITING_RECORDS = "AWAITING_RECORDS"
    LANGUAGE_ACCESS = "LANGUAGE_ACCESS"


class SuspensionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common quartet on most resources)
# ---------------------------------------------------------------------------
class HospitalUnit(TypedDict, total=False):
    id: str
    name: str
    category: str
    posture: str
    max_concurrent_roundings: int
    open_case_count: int
    late_filed_event_count: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    capabilities: List[str]
    on_leave: bool
    max_concurrent_assignments: int
    open_assignment_count: int
    recovery_issuance_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class PatientCase(TypedDict, total=False):
    id: str
    patient_ref: str
    unit_id: str
    received_at: str
    channel: str
    description: str
    grievance_category: str
    alleged_abuse_flag: bool
    vulnerable_patient_flag: bool
    severity_tier: str
    classification: str
    lifecycle_status: str
    regulatory_clock_status: str
    acknowledged_at: Optional[str]
    ack_due_at: Optional[str]
    response_due_calendar_at: Optional[str]
    response_due_business_at: Optional[str]
    tolling_credit_seconds: int
    outstanding_recovery_cents: int
    priority_score: int
    requires_qro_cosign: bool
    current_classification_decision_id: Optional[str]
    resolution_timeliness: str
    closure_note: Optional[str]
    closed_at: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only record (PRD §2.5): only id + created_at, no updated_at/version.
class ClassificationDecision(TypedDict, total=False):
    id: str
    created_at: str
    case_id: str
    decision: str
    rationale_code: str
    note: Optional[str]
    decided_by_id: str
    supersedes_decision_id: Optional[str]


class CaseAssignment(TypedDict, total=False):
    id: str
    case_id: str
    investigator_id: str
    assignment_role: str
    status: str
    assigned_by_id: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict, total=False):
    id: str
    case_id: str
    status: str
    care_concern_flag: bool
    findings_summary: Optional[str]
    submitted_by_id: Optional[str]
    submitted_at: Optional[str]
    note_count: int
    interview_note_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only record (PRD §2.5): only id + created_at.
class InvestigationNote(TypedDict, total=False):
    id: str
    created_at: str
    investigation_id: str
    author_id: str
    note_type: str
    body: str


class ResponseLetter(TypedDict, total=False):
    id: str
    case_id: str
    supersedes_letter_id: Optional[str]
    status: str
    sections: List[str]
    body_summary: str
    drafted_by_id: str
    approved_by_id: Optional[str]
    issued_at: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceRecoveryAction(TypedDict, total=False):
    id: str
    case_id: str
    action_type: str
    value_cents: int
    justification: str
    status: str
    issued_by_id: str
    approved_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityRiskEscalation(TypedDict, total=False):
    id: str
    case_id: str
    escalation_type: str
    source: str
    status: str
    review_track: Optional[str]
    compliance_review_done: bool
    safety_review_done: bool
    filed_by_id: str
    adjudicated_by_id: Optional[str]
    adjudicated_at: Optional[str]
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReportableEvent(TypedDict, total=False):
    id: str
    case_id: str
    escalation_id: Optional[str]
    authority_code: str
    trigger_reason: str
    status: str
    filing_deadline_at: str
    filed_at: Optional[str]
    late_filing: bool
    created_at: str
    updated_at: str
    version: int


class RoundingSession(TypedDict, total=False):
    id: str
    unit_id: str
    advocate_id: str
    start_at: str
    end_at: str
    status: str
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterviewRoom(TypedDict, total=False):
    id: str
    name: str
    location: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class InterviewBooking(TypedDict, total=False):
    id: str
    investigation_id: str
    room_id: str
    start_at: str
    end_at: str
    status: str
    booked_by_id: str
    created_at: str
    updated_at: str
    version: int


class SatisfactionFollowUp(TypedDict, total=False):
    id: str
    case_id: str
    status: str
    due_at: str
    expires_at: str
    score: Optional[int]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClockSuspension(TypedDict, total=False):
    id: str
    case_id: str
    reason: str
    status: str
    started_at: str
    closed_at: Optional[str]
    credited_seconds: int
    created_at: str
    updated_at: str
    version: int


class TrendSnapshot(TypedDict, total=False):
    id: str
    unit_id: str
    case_category: str
    period: str
    grievances_closed: int
    complaints_closed: int
    breaches: int
    headcount_rate_bp: int
    exposure_weighted_rate_bp: int
    systemic_new_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only record (PRD §2.5): only id + created_at.
class HolidayObservance(TypedDict, total=False):
    id: str
    created_at: str
    observance_date: str
    name: str


class CaseTimeline(TypedDict, total=False):
    ack_due_at: Optional[str]
    response_due_calendar_at: Optional[str]
    response_due_business_at: Optional[str]
    tolling_credit_seconds: int
    regulatory_clock_status: str
    priority_score: int
    days_remaining: int
