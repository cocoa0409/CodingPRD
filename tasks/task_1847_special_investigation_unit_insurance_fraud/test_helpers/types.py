"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class SIUCaseStatus(str, Enum):
    INTAKE = "INTAKE"
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    EUO_PENDING = "EUO_PENDING"
    DECISION_PENDING = "DECISION_PENDING"
    CLOSED_SUBSTANTIATED = "CLOSED_SUBSTANTIATED"
    CLOSED_UNSUBSTANTIATED = "CLOSED_UNSUBSTANTIATED"
    CLOSED_INSUFFICIENT = "CLOSED_INSUFFICIENT"
    REFERRED_TO_BUREAU = "REFERRED_TO_BUREAU"


class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    UNDER_SIU_REVIEW = "UNDER_SIU_REVIEW"
    PAYMENT_DELAYED = "PAYMENT_DELAYED"
    DENIED = "DENIED"
    PAID = "PAID"
    CLOSED = "CLOSED"


class PaymentHoldReason(str, Enum):
    SIU_INVESTIGATION = "SIU_INVESTIGATION"
    EUO_NONAPPEARANCE = "EUO_NONAPPEARANCE"
    FRAUD_CONFIRMED = "FRAUD_CONFIRMED"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    DUPLICATE_LINKED = "DUPLICATE_LINKED"


class ScoreBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class InvestigatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REASSIGNED = "REASSIGNED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class EvidenceStatus(str, Enum):
    LOGGED = "LOGGED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADMITTED = "ADMITTED"
    EXCLUDED = "EXCLUDED"
    SEALED = "SEALED"


class EvidenceType(str, Enum):
    STATEMENT = "STATEMENT"
    SURVEILLANCE = "SURVEILLANCE"
    RECORDS = "RECORDS"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    PRIOR_CLAIM_HISTORY = "PRIOR_CLAIM_HISTORY"


class Materiality(str, Enum):
    IMMATERIAL = "IMMATERIAL"
    SUPPORTING = "SUPPORTING"
    SUBSTANTIVE = "SUBSTANTIVE"


class EUOSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NOTICE_SENT = "NOTICE_SENT"
    CONDUCTED = "CONDUCTED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"


class BureauReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED_BY_BUREAU = "REJECTED_BY_BUREAU"
    LATE_FILED = "LATE_FILED"


class EscalationStatus(str, Enum):
    MONITORING = "MONITORING"
    ESCALATED_TO_NICB = "ESCALATED_TO_NICB"
    CLEARED = "CLEARED"
    MERGED_INTO_RING = "MERGED_INTO_RING"


class LedgerStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    FULLY_RECOVERED = "FULLY_RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    RETURNED = "RETURNED"
    REVERSED = "REVERSED"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"
    WIRE = "WIRE"
    WAGE_GARNISHMENT = "WAGE_GARNISHMENT"
    POLICY_OFFSET = "POLICY_OFFSET"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED_BY_REGULATOR = "REJECTED_BY_REGULATOR"


class ReportType(str, Enum):
    QUARTERLY_SIU_ACTIVITY = "QUARTERLY_SIU_ACTIVITY"
    ANNUAL_ANTI_FRAUD_PLAN = "ANNUAL_ANTI_FRAUD_PLAN"
    BUREAU_LATE_FILING_SUMMARY = "BUREAU_LATE_FILING_SUMMARY"


class SubmittedByRole(str, Enum):
    ADJUSTER = "ADJUSTER"
    PROVIDER = "PROVIDER"
    EXTERNAL_TIP = "EXTERNAL_TIP"
    AUTOMATED_RULE = "AUTOMATED_RULE"


class UserRole(str, Enum):
    ADJUSTER = "Adjuster"
    SIU_MANAGER = "SIUManager"
    SIU_INVESTIGATOR = "SIUInvestigator"
    SIU_COMPLIANCE_OFFICER = "SIUComplianceOfficer"


# ---- Entity TypedDicts (all entities carry common_fields: true) ----

class SIUCase(TypedDict, total=False):
    id: str
    claim_id: str
    opened_by_referral_id: str
    case_number: str
    status: str
    priority: str
    suspicion_score: int
    investigation_deadline_at: str
    decision_due_at: Optional[str]
    assigned_investigator_id: Optional[str]
    substantiated_fraud_cents: int
    euo_required: bool
    bureau_referral_required: bool
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_number: str
    state_code: str
    adjuster_id: str
    claimed_amount_cents: int
    status: str
    payment_hold_reason: Optional[str]
    paid_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Adjuster(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    state_licenses: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class RedFlagReferral(TypedDict, total=False):
    id: str
    claim_id: str
    submitted_by_role: str
    red_flag_codes: List[str]
    narrative: str
    suspicion_score: int
    score_band: str
    status: str
    decline_reason: Optional[str]
    duplicate_of_referral_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investigator(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    badge_number: str
    state_certifications: List[str]
    max_active_cases: int
    active_case_count: int
    status: str
    training_current_through: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    case_id: str
    investigator_id: str
    assigned_by_user_id: str
    status: str
    assigned_at: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Evidence(TypedDict, total=False):
    id: str
    case_id: str
    submitted_by_investigator_id: str
    evidence_type: str
    collected_at: str
    custodian: str
    materiality: str
    fraud_amount_cents: int
    status: str
    sealed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EUOSession(TypedDict, total=False):
    id: str
    case_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    location: str
    insured_attendee_name: str
    status: str
    notice_sent_at: Optional[str]
    conducted_at: Optional[str]
    transcript_received: bool
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class FraudBureauReferral(TypedDict, total=False):
    id: str
    case_id: str
    state_code: str
    filed_at: Optional[str]
    deadline_at: str
    status: str
    ack_received_at: Optional[str]
    late_filing: bool
    created_at: str
    updated_at: str
    version: int


class ProviderPattern(TypedDict, total=False):
    id: str
    provider_npi: str
    provider_name: str
    ring_signature: str
    linked_case_ids: List[str]
    pattern_score: int
    escalation_status: str
    parent_pattern_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestitutionLedger(TypedDict, total=False):
    id: str
    case_id: str
    target_amount_cents: int
    recovered_amount_cents: int
    outstanding_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryPayment(TypedDict, total=False):
    id: str
    ledger_id: str
    amount_cents: int
    received_at: str
    method: str
    status: str
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    investigator_id: str
    course_code: str
    completed_at: str
    valid_until: str
    credit_hours: int
    created_at: str
    updated_at: str
    version: int


class RegulatoryReport(TypedDict, total=False):
    id: str
    period_start_at: str
    period_end_at: str
    state_code: str
    report_type: str
    total_cases_opened: int
    total_cases_closed_substantiated: int
    total_restitution_recovered_cents: int
    late_bureau_filings: int
    status: str
    created_at: str
    updated_at: str
    version: int
