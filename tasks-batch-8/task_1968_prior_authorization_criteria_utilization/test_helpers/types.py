"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    UM_ADMIN = "UMAdmin"
    CLINICAL_POLICY_EDITOR = "ClinicalPolicyEditor"
    INTAKE_SPECIALIST = "IntakeSpecialist"
    CLINICAL_REVIEWER = "ClinicalReviewer"
    MEDICAL_DIRECTOR = "MedicalDirector"
    APPEALS_CLERK = "AppealsClerk"
    APPEALS_REVIEWER = "AppealsReviewer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class LineOfBusiness(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"


class Urgency(str, Enum):
    STANDARD = "STANDARD"
    URGENT = "URGENT"


class IntakeChannel(str, Enum):
    PORTAL = "PORTAL"
    FAX = "FAX"
    PHONE = "PHONE"
    EDI = "EDI"


class GoldCardStatus(str, Enum):
    NOT_GOLD_CARDED = "NOT_GOLD_CARDED"
    GOLD_CARDED = "GOLD_CARDED"
    SUSPENDED = "SUSPENDED"


class CriteriaSetStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class GuidelineVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class RequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    AUTO_APPROVED = "AUTO_APPROVED"
    PENDED_REVIEW = "PENDED_REVIEW"
    ESCALATED_MD = "ESCALATED_MD"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class DeterminationOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReasonCode(str, Enum):
    GOLD_CARD_AUTO = "GOLD_CARD_AUTO"
    AUTO_RULE = "AUTO_RULE"
    MEDICAL_NECESSITY_MET = "MEDICAL_NECESSITY_MET"
    MEDICAL_NECESSITY_NOT_MET = "MEDICAL_NECESSITY_NOT_MET"
    INSUFFICIENT_INFO = "INSUFFICIENT_INFO"
    EXPERIMENTAL_INVESTIGATIONAL = "EXPERIMENTAL_INVESTIGATIONAL"


class DecidedByRole(str, Enum):
    SYSTEM_RULE = "SYSTEM_RULE"
    CLINICAL_REVIEWER = "CLINICAL_REVIEWER"
    MEDICAL_DIRECTOR = "MEDICAL_DIRECTOR"


class DeterminationStatus(str, Enum):
    FINAL = "FINAL"
    OVERTURNED = "OVERTURNED"
    VOID = "VOID"


class PeerToPeerStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AppealStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_REVIEW = "IN_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


class GoldCardDecision(str, Enum):
    GRANTED = "GRANTED"
    REINSTATED = "REINSTATED"


class ArrangementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FindingType(str, Enum):
    COMPLIANT = "COMPLIANT"
    NOTICE_DEFICIENT = "NOTICE_DEFICIENT"
    CRITERIA_MISAPPLIED = "CRITERIA_MISAPPLIED"
    TAT_VIOLATION = "TAT_VIOLATION"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ComplianceEventType(str, Enum):
    AUTO_APPROVAL_FIRED = "AUTO_APPROVAL_FIRED"
    TAT_BREACHED = "TAT_BREACHED"
    GOLD_CARD_GRANTED = "GOLD_CARD_GRANTED"
    GOLD_CARD_SUSPENDED = "GOLD_CARD_SUSPENDED"
    DELEGATION_SUSPENDED = "DELEGATION_SUSPENDED"
    DETERMINATION_VOIDED = "DETERMINATION_VOIDED"
    APPEAL_OVERTURNED = "APPEAL_OVERTURNED"


# Common-fields entities: id + created_at + updated_at + version (PRD §2.4).

class Provider(TypedDict, total=False):
    id: str
    npi: str
    name: str
    specialty: Optional[str]
    gold_card_status: str
    gold_card_service_category: Optional[str]
    rolling_determination_count: int
    rolling_approval_count: int
    rolling_approval_rate: Optional[float]
    lifetime_determination_count: int
    lifetime_approval_count: int
    lifetime_approval_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ClinicalCriteriaSet(TypedDict, total=False):
    id: str
    name: str
    line_of_business: str
    service_category: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GuidelineVersion(TypedDict, total=False):
    id: str
    criteria_set_id: str
    version_label: str
    content: str
    auto_approve_eligible: bool
    effective_from: str
    effective_until: Optional[str]
    supersedes_version_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PriorAuthRequest(TypedDict, total=False):
    id: str
    provider_id: str
    member_ref: str
    criteria_set_id: str
    guideline_version_id: str
    service_code: str
    urgency: str
    intake_channel: str
    documentation_complete: bool
    status: str
    received_at: str
    due_at: str
    determined_at: Optional[str]
    escalated_by_user_id: Optional[str]
    is_tat_breached: bool
    created_at: str
    updated_at: str
    version: int


class Determination(TypedDict, total=False):
    id: str
    request_id: str
    outcome: str
    reason_code: str
    decided_by_role: str
    decided_by_user_id: Optional[str]
    guideline_version_id: str
    notice_text: str
    issued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PeerToPeerConference(TypedDict, total=False):
    id: str
    request_id: str
    md_user_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    determination_id: str
    appeal_reason: str
    received_at: str
    due_at: str
    status: str
    reviewer_id: Optional[str]
    decided_at: Optional[str]
    is_tat_breached: bool
    created_at: str
    updated_at: str
    version: int


class DelegationArrangement(TypedDict, total=False):
    id: str
    delegating_plan_name: str
    criteria_set_id: str
    status: str
    open_deficiency_count: int
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    arrangement_id: str
    determination_id: str
    finding_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only snapshot/audit entities (PRD §2.4): id + created_at ONLY —
# no updated_at, no version.

class GoldCardEvaluation(TypedDict, total=False):
    id: str
    created_at: str
    provider_id: str
    service_category: str
    window_start: str
    window_end: str
    window_determination_count: int
    window_approval_rate: float
    decision: str


class ComplianceEvent(TypedDict, total=False):
    id: str
    created_at: str
    event_type: str
    request_id: Optional[str]
    provider_id: Optional[str]
    details: str
