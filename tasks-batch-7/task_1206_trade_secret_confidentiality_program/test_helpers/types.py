"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class AssetStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class AssetClassification(str, Enum):
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"
    CROWN_JEWEL = "CROWN_JEWEL"


class ProtectionPosture(str, Enum):
    DEFICIENT = "DEFICIENT"
    ADEQUATE = "ADEQUATE"
    STRONG = "STRONG"


class MeasureType(str, Enum):
    POLICY = "POLICY"
    TRAINING = "TRAINING"
    PHYSICAL = "PHYSICAL"
    CONTRACTUAL = "CONTRACTUAL"
    TECHNICAL = "TECHNICAL"


class MeasureStatus(str, Enum):
    PLANNED = "PLANNED"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"
    LAPSED = "LAPSED"
    ABANDONED = "ABANDONED"


class CounterpartyType(str, Enum):
    VENDOR = "VENDOR"
    PARTNER = "PARTNER"
    CUSTOMER = "CUSTOMER"
    CONSULTANT = "CONSULTANT"


class CounterpartyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BARRED = "BARRED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class NdaStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    BREACH_ALLEGED = "BREACH_ALLEGED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class ObligationType(str, Enum):
    NON_DISCLOSURE = "NON_DISCLOSURE"
    NON_USE = "NON_USE"
    RETURN_OR_DESTROY = "RETURN_OR_DESTROY"
    NO_REVERSE_ENGINEERING = "NO_REVERSE_ENGINEERING"
    AUDIT_RIGHT = "AUDIT_RIGHT"


class ObligationStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    WAIVED = "WAIVED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"


class EmployeeStatus(str, Enum):
    PREBOARDING = "PREBOARDING"
    ACTIVE = "ACTIVE"
    NOTICE = "NOTICE"
    DEPARTED = "DEPARTED"


class AccessClearance(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    PRIVILEGED = "PRIVILEGED"


class DepartureType(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    INVOLUNTARY = "INVOLUNTARY"


class AcknowledgmentStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class ExitInterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    NO_SHOW = "NO_SHOW"
    CERTIFIED = "CERTIFIED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PROVISIONED = "PROVISIONED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class MarkingProtocol(str, Enum):
    STAMPED_CONFIDENTIAL = "STAMPED_CONFIDENTIAL"
    ORAL_WITH_FOLLOWUP = "ORAL_WITH_FOLLOWUP"
    ENCRYPTED_DELIVERY = "ENCRYPTED_DELIVERY"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"
    WITHDRAWN = "WITHDRAWN"
    EXECUTED = "EXECUTED"


class ReviewTriggerReason(str, Enum):
    VOLUNTARY_DEPARTURE = "VOLUNTARY_DEPARTURE"
    INVOLUNTARY_DEPARTURE = "INVOLUNTARY_DEPARTURE"
    POLICY = "POLICY"
    LITIGATION = "LITIGATION"


class ForensicReviewStatus(str, Enum):
    OPENED = "OPENED"
    IMAGING = "IMAGING"
    FINDINGS_DRAFTED = "FINDINGS_DRAFTED"
    COUNSEL_REVIEW = "COUNSEL_REVIEW"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    ESCALATED = "ESCALATED"


class ClaimType(str, Enum):
    CEASE_AND_DESIST = "CEASE_AND_DESIST"
    RETURN_OF_PROPERTY = "RETURN_OF_PROPERTY"
    PRESERVATION = "PRESERVATION"


class DemandLetterStatus(str, Enum):
    DRAFTED = "DRAFTED"
    COUNSEL_APPROVED = "COUNSEL_APPROVED"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLIED = "COMPLIED"
    IGNORED = "IGNORED"
    LITIGATION = "LITIGATION"
    WITHDRAWN = "WITHDRAWN"


class PreservationNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class EvidenceSource(str, Enum):
    FORENSIC_IMAGE = "FORENSIC_IMAGE"
    EMAIL_EXPORT = "EMAIL_EXPORT"
    ACCESS_LOG = "ACCESS_LOG"
    DEVICE_IMAGE = "DEVICE_IMAGE"
    MARKED_COPY = "MARKED_COPY"


class EvidenceStatus(str, Enum):
    COLLECTED = "COLLECTED"
    SEALED = "SEALED"
    RELEASED = "RELEASED"


class TrainingModule(str, Enum):
    BASIC_TS = "BASIC_TS"
    CLEAN_DESK = "CLEAN_DESK"
    ADVANCED_IP = "ADVANCED_IP"


class TrainingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    EXCUSED = "EXCUSED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    REPORTED = "REPORTED"
    REMEDIATING = "REMEDIATING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    IP_COUNSEL = "IPCounsel"
    SENIOR_COUNSEL = "SeniorCounsel"
    HR_PARTNER = "HRPartner"
    SECURITY_OFFICER = "SecurityOfficer"
    EMPLOYEE = "Employee"
    COUNTERPARTY_REP = "CounterpartyRep"


# All sixteen resource types carry id + created_at + updated_at + version (PRD §2.4).

class SecretAsset(TypedDict, total=False):
    id: str
    title: str
    description: str
    classification: str
    owner_department: str
    exposure_estimate_cents: int
    status: str
    score_operational: float
    score_documentary: float
    protection_posture: str
    active_grant_count: int
    created_at: str
    updated_at: str
    version: int


class ReasonableMeasure(TypedDict, total=False):
    id: str
    asset_id: str
    measure_type: str
    title: str
    evidence_uri: str
    status: str
    implemented_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    weight_points: int
    points_effective: float
    created_at: str
    updated_at: str
    version: int


class Counterparty(TypedDict, total=False):
    id: str
    legal_name: str
    counterparty_type: str
    status: str
    exposure_index_trailing: float
    exposure_index_lifetime: float
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class NdaAgreement(TypedDict, total=False):
    id: str
    counterparty_id: str
    supersedes_id: Optional[str]
    template_version: str
    governing_law: str
    effective_date: str
    expiry_date: str
    survival_months: int
    classification_ceiling: str
    status: str
    terminated_at: Optional[str]
    confidentiality_end: str
    obligations_total_count: int
    obligations_open_count: int
    obligations_fulfilled_count: int
    obligations_waived_count: int
    created_at: str
    updated_at: str
    version: int


class NdaObligation(TypedDict, total=False):
    id: str
    nda_id: str
    obligation_type: str
    due_at: Optional[str]
    status: str
    fulfilled_at: Optional[str]
    escalated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    department: str
    role_title: str
    access_clearance: str
    hired_at: str
    status: str
    departure_type: Optional[str]
    notice_given_at: Optional[str]
    departed_at: Optional[str]
    training_current: bool
    created_at: str
    updated_at: str
    version: int


class Acknowledgment(TypedDict, total=False):
    id: str
    employee_id: str
    policy_version: str
    due_at: str
    signed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExitInterview(TypedDict, total=False):
    id: str
    employee_id: str
    scheduled_start: str
    scheduled_end: str
    conducted_at: Optional[str]
    return_certification: bool
    obligations_reiterated: bool
    no_show_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict, total=False):
    id: str
    employee_id: str
    asset_id: str
    justification: str
    expires_at: str
    status: str
    requester_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureRequest(TypedDict, total=False):
    id: str
    requester_employee_id: str
    asset_id: str
    nda_id: str
    purpose: str
    marking_protocol: str
    planned_disclosure_date: str
    pinned_asset_version: Optional[int]
    pinned_nda_version: Optional[int]
    risk_score_provisional: Optional[float]
    risk_score_final: Optional[float]
    senior_endorsed: bool
    marking_evidence_uri: Optional[str]
    marking_sha256: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ForensicReview(TypedDict, total=False):
    id: str
    employee_id: str
    trigger_reason: str
    status: str
    exfil_indicator_count: int
    findings_notes: str
    reviewed_by_counsel_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DemandLetter(TypedDict, total=False):
    id: str
    forensic_review_id: str
    employee_id: str
    claim_lines: List[dict]
    response_deadline_days: int
    damages_estimate_cents: int
    drafted_by_user_id: str
    approved_by_user_id: Optional[str]
    issued_at: Optional[str]
    response_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PreservationNotice(TypedDict, total=False):
    id: str
    legal_matter_ref: str
    asset_ids: List[str]
    employee_ids: List[str]
    review_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    review_id: Optional[str]
    disclosure_id: Optional[str]
    source: str
    sha256: str
    byte_size: int
    sealed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict, total=False):
    id: str
    employee_id: str
    module: str
    due_at: str
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CleanDeskAudit(TypedDict, total=False):
    id: str
    department: str
    window_start: str
    window_end: str
    findings_count: Optional[int]
    critical_findings: Optional[int]
    resolved_critical_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
