"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INTAKE_SPECIALIST = "IntakeSpecialist"
    CASE_ANALYST = "CaseAnalyst"
    MEDICAL_DIRECTOR = "MedicalDirector"
    MEMBER_SERVICES_REP = "MemberServicesRep"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLAIMS_PROCESSOR = "ClaimsProcessor"


class Program(str, Enum):
    MEDICARE = "MEDICARE"
    MEDI_CAL = "MEDI_CAL"
    DUAL = "DUAL"


class CaseKind(str, Enum):
    GRIEVANCE = "GRIEVANCE"
    ORG_DETERMINATION = "ORG_DETERMINATION"
    APPEAL = "APPEAL"


class PriorityTrack(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class CaseStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    IN_REVIEW = "IN_REVIEW"
    PENDING_CLINICAL = "PENDING_CLINICAL"
    DECIDED = "DECIDED"
    NOTIFIED = "NOTIFIED"
    IRE_REFERRED = "IRE_REFERRED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class DecisionOutcome(str, Enum):
    FULLY_FAVORABLE = "FULLY_FAVORABLE"
    PARTIALLY_FAVORABLE = "PARTIALLY_FAVORABLE"
    UNFAVORABLE = "UNFAVORABLE"


class ClinicalReviewStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    DETERMINATION_DRAFT = "DETERMINATION_DRAFT"
    DETERMINED = "DETERMINED"
    SUPERSEDED = "SUPERSEDED"


class Determination(str, Enum):
    UPHOLD_SERVICE = "UPHOLD_SERVICE"
    OVERTURN_SERVICE = "OVERTURN_SERVICE"
    PARTIAL = "PARTIAL"


class NotificationStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETRIED = "RETRIED"


class NotificationKind(str, Enum):
    ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT"
    EXTENSION_NOTICE = "EXTENSION_NOTICE"
    DECISION = "DECISION"
    IRE_FORWARD_NOTICE = "IRE_FORWARD_NOTICE"
    REOPEN_OUTCOME = "REOPEN_OUTCOME"
    EFFECTUATION_CONFIRMATION = "EFFECTUATION_CONFIRMATION"


class RecipientKind(str, Enum):
    MEMBER = "MEMBER"
    PROVIDER = "PROVIDER"


class ReferralStatus(str, Enum):
    FORWARDED = "FORWARDED"
    ACKNOWLEDGED_BY_IRE = "ACKNOWLEDGED_BY_IRE"
    DECISION_RECEIVED = "DECISION_RECEIVED"
    EFFECTUATED = "EFFECTUATED"


class IreDecision(str, Enum):
    UPHOLD_PLAN = "UPHOLD_PLAN"
    OVERTURN_PLAN = "OVERTURN_PLAN"
    PARTIAL = "PARTIAL"


class EffectuationStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    EFFECTUATED = "EFFECTUATED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    WAIVED = "WAIVED"


class ReopeningStatus(str, Enum):
    REQUESTED = "REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class ReopenReason(str, Enum):
    NEW_EVIDENCE = "NEW_EVIDENCE"
    CLERICAL_ERROR = "CLERICAL_ERROR"
    FRAUD_OR_SIMILAR_FAULT = "FRAUD_OR_SIMILAR_FAULT"


class CaseEventType(str, Enum):
    NOTE = "NOTE"
    DOCUMENT = "DOCUMENT"
    EXTENSION_REQUEST = "EXTENSION_REQUEST"
    EXTENSION_GRANTED = "EXTENSION_GRANTED"
    CTM_LINKED = "CTM_LINKED"
    CTM_UNLINKED = "CTM_UNLINKED"
    PRIORITY_UPGRADE = "PRIORITY_UPGRADE"
    DECISION_RECORDED = "DECISION_RECORDED"
    NOTIFICATION_SENT = "NOTIFICATION_SENT"
    IRE_FORWARDED = "IRE_FORWARDED"
    REOPEN_REQUESTED = "REOPEN_REQUESTED"
    REOPEN_GRANTED = "REOPEN_GRANTED"
    REOPEN_DENIED = "REOPEN_DENIED"
    EFFECTUATION_STARTED = "EFFECTUATION_STARTED"
    EFFECTUATION_COMPLETED = "EFFECTUATION_COMPLETED"


class CtmTier(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# --- Entity TypedDicts ---
# Members, Providers, Deadline Policies, Cases, Clinical Reviews, Notifications,
# IRE Referrals, Effectuations, Reopenings all carry id + created_at +
# updated_at + version (PRD §2.5).

class Member(TypedDict, total=False):
    id: str
    member_ref: str
    full_name: str
    program: str
    enrollment_status: str
    open_case_count: int
    ctm_linked_case_count: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    npi: str
    legal_name: str
    contract_status: str
    w9_on_file: bool
    created_at: str
    updated_at: str
    version: int


class DeadlinePolicy(TypedDict, total=False):
    id: str
    program: str
    case_kind: str
    priority_track: str
    resolution_hours: int
    extension_hours: int
    effectuation_hours: int
    business_hours_only: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class GrievanceAppealCase(TypedDict, total=False):
    id: str
    member_id: str
    provider_id: Optional[str]
    case_kind: str
    priority_track: str
    expedited_requested: bool
    expedited_justification: Optional[str]
    status: str
    decision_outcome: Optional[str]
    received_at: str
    acknowledged_at: Optional[str]
    decided_at: Optional[str]
    notified_at: Optional[str]
    closed_at: Optional[str]
    extension_applied: bool
    resolution_due_at: Optional[str]
    effectuation_due_at: Optional[str]
    ctm_linked: bool
    reopened_from_case_id: Optional[str]
    overdue: bool
    created_at: str
    updated_at: str
    version: int


# CaseEvent is an append-only snapshot: id + created_at only (PRD §2.5) —
# NO updated_at, NO version.
class CaseEvent(TypedDict, total=False):
    id: str
    case_id: str
    event_type: str
    actor_role: str
    actor_id: str
    body: Optional[str]
    occurred_at: str
    created_at: str


class ClinicalReview(TypedDict, total=False):
    id: str
    case_id: str
    reviewer_physician_id: Optional[str]
    status: str
    determination: Optional[str]
    medical_necessity_score: Optional[float]
    superseded_by_review_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict, total=False):
    id: str
    case_id: str
    recipient_kind: str
    notification_kind: str
    status: str
    required_elements: List[str]
    supplied_elements: List[str]
    completeness_score: float
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IndependentReviewReferral(TypedDict, total=False):
    id: str
    case_id: str
    ire_organization_code: str
    status: str
    forwarded_at: str
    ire_decision: Optional[str]
    ire_decision_received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Effectuation(TypedDict, total=False):
    id: str
    case_id: str
    referral_id: Optional[str]
    status: str
    payment_amount_cents: int
    timeliness_percent: Optional[float]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reopening(TypedDict, total=False):
    id: str
    case_id: str
    request_reason: str
    status: str
    requested_at: str
    decided_at: Optional[str]
    spawned_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# AuditUniverseRecord is an append-only snapshot: id + created_at only (PRD §2.5).
class AuditUniverseRecord(TypedDict, total=False):
    id: str
    report_period: str
    case_id: str
    case_kind: str
    priority_track: str
    resolution_timely: bool
    effectuation_timely: Optional[bool]
    snapshot_at: str
    created_at: str
