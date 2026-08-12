"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import Optional, List, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceChannel(str, Enum):
    INTERNAL_DETECTION = "INTERNAL_DETECTION"
    THIRD_PARTY_REPORT = "THIRD_PARTY_REPORT"
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"
    CUSTOMER_COMPLAINT = "CUSTOMER_COMPLAINT"
    AUDIT = "AUDIT"


class Severity(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class InvestigationStatus(str, Enum):
    INTAKE = "INTAKE"
    SCOPED = "SCOPED"
    INVESTIGATING = "INVESTIGATING"
    CONFIRMED = "CONFIRMED"
    CONTAINED = "CONTAINED"
    CLOSED = "CLOSED"


class NotificationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    EVALUATING = "EVALUATING"
    REQUIRED = "REQUIRED"
    DRAFTING = "DRAFTING"
    APPROVED = "APPROVED"
    DISPATCHING = "DISPATCHING"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


class RemediationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PLANNING = "PLANNING"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"


class ForensicScopeStatus(str, Enum):
    DRAFT = "DRAFT"
    BASELINED = "BASELINED"
    AMENDED = "AMENDED"
    FINAL = "FINAL"


class DataElement(str, Enum):
    NAME = "NAME"
    SSN = "SSN"
    DOB = "DOB"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ADDRESS = "ADDRESS"
    DRIVER_LICENSE = "DRIVER_LICENSE"
    PASSPORT = "PASSPORT"
    FINANCIAL_ACCOUNT = "FINANCIAL_ACCOUNT"
    HEALTH_RECORD = "HEALTH_RECORD"
    BIOMETRIC = "BIOMETRIC"
    CREDENTIALS = "CREDENTIALS"


class EvidenceType(str, Enum):
    LOG = "LOG"
    DISK_IMAGE = "DISK_IMAGE"
    MEMORY_DUMP = "MEMORY_DUMP"
    EMAIL = "EMAIL"
    NETWORK_PCAP = "NETWORK_PCAP"
    DOCUMENT = "DOCUMENT"
    PHOTO = "PHOTO"


class EvidenceItemStatus(str, Enum):
    COLLECTED = "COLLECTED"
    SEALED = "SEALED"
    RELEASED = "RELEASED"
    DESTROYED = "DESTROYED"


class AffectedSubjectStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    VERIFIED = "VERIFIED"
    NOTICE_QUEUED = "NOTICE_QUEUED"
    NOTIFIED = "NOTIFIED"
    EXCLUDED = "EXCLUDED"


class CreditMonitoringSubjectStatus(str, Enum):
    NOT_OFFERED = "NOT_OFFERED"
    OFFERED_PENDING = "OFFERED_PENDING"
    ENROLLED = "ENROLLED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class DeadlineKind(str, Enum):
    CALENDAR_DAYS = "CALENDAR_DAYS"
    BUSINESS_DAYS = "BUSINESS_DAYS"


class JurisdictionEvaluationStatus(str, Enum):
    PENDING = "PENDING"
    TRIGGERED = "TRIGGERED"
    WAIVED = "WAIVED"
    SATISFIED = "SATISFIED"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    LEGAL_REVIEW = "LEGAL_REVIEW"
    APPROVED = "APPROVED"
    LOCKED_FOR_MAIL = "LOCKED_FOR_MAIL"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class MailingBatchStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    DELIVERED_CONFIRMED = "DELIVERED_CONFIRMED"
    FAILED = "FAILED"


class CreditMonitoringOfferStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CallCenterPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class SubmissionChannel(str, Enum):
    PORTAL = "PORTAL"
    EMAIL = "EMAIL"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"


class RegulatorSubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INQUIRY_OPEN = "INQUIRY_OPEN"
    INQUIRY_RESPONDED = "INQUIRY_RESPONDED"
    CLOSED = "CLOSED"


class RemediationActionCategory(str, Enum):
    TECHNICAL = "TECHNICAL"
    PROCESS = "PROCESS"
    TRAINING = "TRAINING"
    VENDOR = "VENDOR"
    LEGAL = "LEGAL"


class RemediationActionStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    IncidentCommander = "IncidentCommander"
    ForensicLead = "ForensicLead"
    PrivacyCounsel = "PrivacyCounsel"
    GeneralCounsel = "GeneralCounsel"
    DataAnalyst = "DataAnalyst"
    AffectedSubjectRole = "AffectedSubjectRole"
    Auditor = "Auditor"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true — id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Incident(TypedDict, total=False):
    id: str
    title: str
    discovered_at: str
    occurred_at: str
    source_channel: str
    severity: str
    investigation_status: str
    notification_status: str
    risk_score_conservative: int
    risk_score_likelihood_adjusted: int
    total_affected_subjects: int
    total_notified_subjects: int
    total_pending_subjects: int
    credit_monitoring_offered: int
    credit_monitoring_enrolled: int
    credit_monitoring_declined: int
    remediation_status: str
    created_at: str
    updated_at: str
    version: int


class ForensicScope(TypedDict, total=False):
    id: str
    incident_id: str
    scope_statement: str
    systems_in_scope: List[str]
    data_elements_at_risk: List[str]
    exfiltration_likelihood_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    incident_id: str
    label: str
    evidence_type: str
    collected_at: str
    collected_by_user_id: str
    preservation_hash: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EvidenceCustodyLog(TypedDict, total=False):
    # Append-only: only id + created_at + entity-specific fields.
    id: str
    incident_id: str
    evidence_item_id: str
    custodian_user_id: str
    start_at: str
    end_at: Optional[str]
    purpose: str
    created_at: str


class AffectedSubject(TypedDict, total=False):
    id: str
    incident_id: str
    external_subject_ref: str
    full_name: str
    residence_state_code: str
    data_elements_exposed: List[str]
    record_count: int
    status: str
    credit_monitoring_status: str
    offered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JurisdictionEvaluation(TypedDict, total=False):
    id: str
    incident_id: str
    state_code: str
    statute_reference: str
    record_count_threshold: int
    deadline_days: int
    deadline_kind: str
    requires_ag_notification: bool
    requires_credit_agencies: bool
    subjects_in_jurisdiction: int
    notification_required: bool
    deadline_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Notice(TypedDict, total=False):
    id: str
    incident_id: str
    jurisdiction_evaluation_id: str
    version_label: int
    body_text: str
    language: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    supersedes_notice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MailingBatch(TypedDict, total=False):
    id: str
    incident_id: str
    notice_id: str
    vendor_code: str
    recipient_count: int
    scheduled_ship_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditMonitoringOffer(TypedDict, total=False):
    id: str
    incident_id: str
    affected_subject_id: str
    vendor_code: str
    term_months: int
    unit_cost_cents: int
    offer_code: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CallCenterStaffingPlan(TypedDict, total=False):
    id: str
    incident_id: str
    effective_from: str
    effective_until: str
    seats_required: int
    languages_supported: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatorSubmission(TypedDict, total=False):
    id: str
    incident_id: str
    jurisdiction_evaluation_id: str
    notice_id: str
    submission_channel: str
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RemediationAction(TypedDict, total=False):
    id: str
    incident_id: str
    title: str
    category: str
    owner_user_id: str
    due_at: str
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CostSummary(TypedDict, total=False):
    credit_monitoring_cost_cents: int
    offer_count: int
