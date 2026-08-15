"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the four system-managed properties of PRD §2.4
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PATIENT = "Patient"
    TRIAGE_NURSE = "TriageNurse"
    FRONT_DESK = "FrontDesk"
    PROVIDER = "Provider"
    BILLING_SPECIALIST = "BillingSpecialist"
    PRACTICE_ADMIN = "PracticeAdmin"


class StaffType(str, Enum):
    PROVIDER = "PROVIDER"
    NURSE = "NURSE"
    FRONT_DESK = "FRONT_DESK"
    BILLING_SPECIALIST = "BILLING_SPECIALIST"
    PRACTICE_ADMIN = "PRACTICE_ADMIN"


class PlanType(str, Enum):
    COPAY = "COPAY"
    COINSURANCE = "COINSURANCE"


class PoolKind(str, Enum):
    NURSE_TRIAGE = "NURSE_TRIAGE"
    PROVIDER_INBOX = "PROVIDER_INBOX"
    FRONT_DESK = "FRONT_DESK"
    BILLING = "BILLING"


class DeadlinePolicy(str, Enum):
    FROM_RECEIPT = "FROM_RECEIPT"
    FROM_TRIAGE = "FROM_TRIAGE"


class MessageStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    ASSIGNED = "ASSIGNED"
    IN_REVIEW = "IN_REVIEW"
    PENDING_CONSENT = "PENDING_CONSENT"
    PENDING_COSIGN = "PENDING_COSIGN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


# Statuses that count toward a staff member's open_inbox_count (PRD §2.11).
COUNTED_MESSAGE_STATUSES = [
    "ASSIGNED", "IN_REVIEW", "PENDING_CONSENT",
    "PENDING_COSIGN", "ESCALATED", "REOPENED",
]


class MessageUrgency(str, Enum):
    EMERGENT = "EMERGENT"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class MessageCategory(str, Enum):
    CLINICAL = "CLINICAL"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class BillingDisposition(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    BILLABLE_CANDIDATE = "BILLABLE_CANDIDATE"
    CHARGEABLE = "CHARGEABLE"
    NOT_BILLABLE = "NOT_BILLABLE"


class EntryKind(str, Enum):
    CLINICAL_REVIEW = "CLINICAL_REVIEW"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class ConsentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class ConsentDecision(str, Enum):
    GRANTED = "GRANTED"
    DECLINED = "DECLINED"


class ClaimCode(str, Enum):
    CPT_99421 = "CPT_99421"
    CPT_99422 = "CPT_99422"
    CPT_99423 = "CPT_99423"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOID = "VOID"


class AdjudicationOutcome(str, Enum):
    PAID = "PAID"
    DENIED = "DENIED"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class NoticeKind(str, Enum):
    EMERGENT_MISUSE = "EMERGENT_MISUSE"
    PORTAL_SCOPE_GUIDANCE = "PORTAL_SCOPE_GUIDANCE"
    BILLING_EXPLAINER = "BILLING_EXPLAINER"


class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class CosignAction(str, Enum):
    COSIGN = "COSIGN"
    RETURN = "RETURN"


class BurdenMetric(str, Enum):
    ATTRIBUTED = "ATTRIBUTED"
    TOUCHED = "TOUCHED"


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: Optional[str]
    plan_type: str
    copay_cents: Optional[int]
    coinsurance_pct: Optional[float]
    outstanding_billed_cents: int
    education_gate_open: bool
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    staff_type: str
    open_inbox_count: int
    inbox_overloaded: bool
    created_at: str
    updated_at: str
    version: int


class Pool(TypedDict, total=False):
    id: str
    name: str
    pool_kind: str
    target_minutes_emergent: int
    target_minutes_urgent: int
    target_minutes_routine: int
    deadline_policy: str
    created_at: str
    updated_at: str
    version: int


class CoverageWindow(TypedDict, total=False):
    id: str
    pool_id: str
    staff_id: str
    start_utc: str
    end_utc: str
    created_at: str
    updated_at: str
    version: int


class OnCallShift(TypedDict, total=False):
    id: str
    provider_id: str
    start_utc: str
    end_utc: str
    created_at: str
    updated_at: str
    version: int


class DelegationGrant(TypedDict, total=False):
    id: str
    delegator_provider_id: str
    delegate_staff_id: str
    pool_id: str
    start_utc: str
    end_utc: str
    status: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PortalMessage(TypedDict, total=False):
    id: str
    patient_id: str
    subject: str
    body: str
    received_at: str
    urgency: Optional[str]
    category: Optional[str]
    triaged_at: Optional[str]
    assigned_pool_id: Optional[str]
    assignee_id: Optional[str]
    pending_cosign_by_id: Optional[str]
    resolved_by_id: Optional[str]
    resolved_at: Optional[str]
    first_response_at: Optional[str]
    response_due_at: Optional[str]
    sla_breached: bool
    billing_disposition: str
    clinical_minutes_total: int
    reopen_count: int
    resolution_summary: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffTimeEntry(TypedDict, total=False):
    id: str
    message_id: str
    staff_id: str
    entry_kind: str
    minutes: int
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict, total=False):
    id: str
    message_id: str
    patient_id: str
    status: str
    disclosed_code: str
    disclosed_fee_cents: int
    requested_at: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EVisitClaim(TypedDict, total=False):
    id: str
    message_id: str
    patient_id: str
    rendering_provider_id: str
    code: str
    fee_cents: int
    patient_responsibility_cents: int
    status: str
    denial_reason: Optional[str]
    submitted_at: Optional[str]
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Escalation(TypedDict, total=False):
    id: str
    message_id: str
    provider_id: str
    reason: str
    status: str
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PatientEducationNotice(TypedDict, total=False):
    id: str
    message_id: str
    patient_id: str
    notice_kind: str
    blocking: bool
    body: str
    status: str
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BurdenSummary(TypedDict, total=False):
    open_inbox_count: int
    inbox_overloaded: bool
    attributed_resolutions: int
    touched_resolutions: int
    clinical_minutes: int
