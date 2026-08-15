"""Domain types: entity structures, status enums, role enum (PRD §2.1, §2.4, §3).

Append-only records (ReassessmentSchedule, VendorContact) carry only
``id`` and ``created_at`` per PRD §2.4 — their structures deliberately omit
``updated_at`` and ``version``.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RISK_ANALYST = "RiskAnalyst"
    SECURITY_APPROVER = "SecurityApprover"
    VENDOR_CONTACT = "VendorContact"


class Tier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"


class VendorPosture(str, Enum):
    ONBOARDING = "ONBOARDING"
    ASSESSING = "ASSESSING"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    SUSPENDED = "SUSPENDED"
    OFFBOARDING = "OFFBOARDING"
    OFFBOARDED = "OFFBOARDED"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    SCORED = "SCORED"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    REMEDIATION = "REMEDIATION"
    RISK_ACCEPTANCE_REVIEW = "RISK_ACCEPTANCE_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ResponseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class EvidenceKind(str, Enum):
    SOC2_TYPE1 = "SOC2_TYPE1"
    SOC2_TYPE2 = "SOC2_TYPE2"
    ISO27001 = "ISO27001"
    PENTEST = "PENTEST"
    OTHER = "OTHER"


class EvidenceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVIEWED_CLEAN = "REVIEWED_CLEAN"
    REVIEWED_WITH_EXCEPTIONS = "REVIEWED_WITH_EXCEPTIONS"
    REJECTED = "REJECTED"


class ExceptionSource(str, Enum):
    QUESTIONNAIRE = "QUESTIONNAIRE"
    EVIDENCE = "EVIDENCE"
    MONITORING = "MONITORING"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    IN_REMEDIATION = "IN_REMEDIATION"
    CLOSED_REMEDIATED = "CLOSED_REMEDIATED"
    CLOSED_ACCEPTED = "CLOSED_ACCEPTED"
    CLOSED_FALSE_POSITIVE = "CLOSED_FALSE_POSITIVE"


class PlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AcceptanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AddendumStatus(str, Enum):
    REQUIRED = "REQUIRED"
    DRAFTED = "DRAFTED"
    SIGNED = "SIGNED"
    WAIVED = "WAIVED"


class AlertSignal(str, Enum):
    BREACH_REPORT = "BREACH_REPORT"
    CERT_LAPSE = "CERT_LAPSE"
    FINANCIAL_DISTRESS = "FINANCIAL_DISTRESS"
    NEGATIVE_NEWS = "NEGATIVE_NEWS"
    SCAN_FINDING = "SCAN_FINDING"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"
    ESCALATED = "ESCALATED"


class DisclosureStatus(str, Enum):
    DISCLOSED = "DISCLOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AttestationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ScheduleKind(str, Enum):
    TIER_CADENCE = "TIER_CADENCE"
    ALERT_ESCALATION = "ALERT_ESCALATION"
    ACCEPTANCE_EXPIRY = "ACCEPTANCE_EXPIRY"
    OFFBOARDING_SLIP = "OFFBOARDING_SLIP"


# --- Entity structures -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# Fields that may legitimately be null (e.g. active_cycle_id, scores before
# they are computed) are typed Optional. total=False keeps the structures
# descriptive rather than prescriptive; assertions.py enforces the contract.


class Vendor(TypedDict, total=False):
    id: str
    legal_name: str
    data_sensitivity: str
    access_level: str
    criticality: str
    current_tier: str
    posture: str
    active_cycle_id: Optional[str]
    risk_score: float
    next_reassessment_due: Optional[str]
    offboarding_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssessmentTierPolicy(TypedDict, total=False):
    id: str
    name: str
    active: bool
    tier_matrix: Dict[str, Any]
    tier1_reassessment_months: int
    tier2_reassessment_months: int
    tier3_reassessment_months: int
    tier4_reassessment_months: int
    created_at: str
    updated_at: str
    version: int


class QuestionnaireTemplate(TypedDict, total=False):
    id: str
    title: str
    applies_to_tiers: List[str]
    items: List[Dict[str, Any]]
    status: str
    published_version: int
    created_at: str
    updated_at: str
    version: int


class AssessmentCycle(TypedDict, total=False):
    id: str
    vendor_id: str
    template_id: str
    template_version: int
    tier_at_issue: str
    status: str
    issued_at: Optional[str]
    response_due_at: Optional[str]
    questionnaire_score: Optional[float]
    evidence_score: Optional[float]
    composite_score: Optional[float]
    open_exception_count: int
    acceptance_required: bool
    created_at: str
    updated_at: str
    version: int


class QuestionnaireResponse(TypedDict, total=False):
    id: str
    cycle_id: str
    submitted_by: str
    answers: List[Dict[str, Any]]
    status: str
    submitted_at: Optional[str]
    raw_score: Optional[float]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class EvidenceArtifact(TypedDict, total=False):
    id: str
    cycle_id: str
    kind: str
    period_start: str
    period_end: str
    issued_by: str
    status: str
    coverage_gap_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ExceptionFinding(TypedDict, total=False):
    id: str
    cycle_id: str
    source: str
    evidence_artifact_id: Optional[str]
    severity: str
    description: str
    status: str
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationPlan(TypedDict, total=False):
    id: str
    cycle_id: str
    exception_ids: List[str]
    tasks: List[Dict[str, Any]]
    status: str
    approved_by: Optional[str]
    completed_task_keys: List[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskAcceptance(TypedDict, total=False):
    id: str
    cycle_id: str
    exception_ids: List[str]
    justification: str
    compensating_controls: List[str]
    expires_at: str
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractAddendum(TypedDict, total=False):
    id: str
    vendor_id: str
    cycle_id: str
    clause_set: List[str]
    status: str
    signed_at: Optional[str]
    waived_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringAlert(TypedDict, total=False):
    id: str
    vendor_id: str
    signal: str
    severity: str
    detected_at: str
    status: str
    disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubprocessorDisclosure(TypedDict, total=False):
    id: str
    vendor_id: str
    subprocessor_name: str
    data_categories: List[str]
    region: str
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OffboardingAttestation(TypedDict, total=False):
    id: str
    vendor_id: str
    data_returned: bool
    data_destroyed: bool
    destruction_method: Optional[str]
    attested_by: str
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only event log (PRD §2.4): ONLY id + created_at, never mutated.
class ReassessmentScheduleEvent(TypedDict, total=False):
    id: str
    vendor_id: str
    kind: str
    previous_due: Optional[str]
    new_due: Optional[str]
    reason_ref: Optional[str]
    created_at: str


# Append-only contact record (PRD §2.4): ONLY id + created_at.
class VendorContact(TypedDict, total=False):
    id: str
    vendor_id: str
    email: str
    full_name: str
    is_primary: bool
    created_at: str
