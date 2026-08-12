"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.10, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    BUSINESS_SPONSOR = "BusinessSponsor"
    SCREENING_ANALYST = "ScreeningAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_REVIEWER = "FinanceReviewer"
    AUDIT_LEAD = "AuditLead"


class OnboardingStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENING = "SCREENING"
    DD_REVIEW = "DD_REVIEW"
    ENHANCED_REVIEW = "ENHANCED_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Industry(str, Enum):
    TECHNOLOGY = "TECHNOLOGY"
    LOGISTICS = "LOGISTICS"
    CONSULTING = "CONSULTING"
    CONSTRUCTION = "CONSTRUCTION"
    GOVERNMENT_RELATIONS = "GOVERNMENT_RELATIONS"


class Touchpoint(str, Enum):
    NONE = "NONE"
    INDIRECT = "INDIRECT"
    DIRECT = "DIRECT"


class CheckType(str, Enum):
    PEP = "PEP"
    ADVERSE_MEDIA = "ADVERSE_MEDIA"
    SANCTIONS = "SANCTIONS"


class CheckStatus(str, Enum):
    QUEUED = "QUEUED"
    CLEAR = "CLEAR"
    POTENTIAL_HIT = "POTENTIAL_HIT"
    HIT_CONFIRMED = "HIT_CONFIRMED"
    HIT_DISMISSED = "HIT_DISMISSED"


class QuestionnaireStatus(str, Enum):
    ISSUED = "ISSUED"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class FlagSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FlagSource(str, Enum):
    SCREENING = "SCREENING"
    QUESTIONNAIRE = "QUESTIONNAIRE"
    AUDIT = "AUDIT"
    SYSTEM = "SYSTEM"
    MANUAL = "MANUAL"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_ENHANCED_REVIEW = "UNDER_ENHANCED_REVIEW"
    CLEARED = "CLEARED"
    SUBSTANTIATED = "SUBSTANTIATED"


class CaseStatus(str, Enum):
    ENHANCED_DD = "ENHANCED_DD"
    DECIDED = "DECIDED"


class DecisionOutcome(str, Enum):
    APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
    REJECT = "REJECT"
    TERMINATE = "TERMINATE"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CLAUSES = "PENDING_CLAUSES"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class CertType(str, Enum):
    ANNUAL_ABAC = "ANNUAL_ABAC"
    CODE_OF_CONDUCT = "CODE_OF_CONDUCT"


class CertStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    LAPSED = "LAPSED"


class PaymentType(str, Enum):
    COMMISSION = "COMMISSION"
    SUCCESS_FEE = "SUCCESS_FEE"
    REIMBURSEMENT = "REIMBURSEMENT"


class PaymentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    REVERSED = "REVERSED"


class EntryType(str, Enum):
    GIFT = "GIFT"
    HOSPITALITY = "HOSPITALITY"
    TRAVEL = "TRAVEL"


class EntryStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"


class TriggerSource(str, Enum):
    SCHEDULED = "SCHEDULED"
    MANUAL = "MANUAL"


class CycleOutcome(str, Enum):
    REAFFIRM = "REAFFIRM"
    DOWNGRADE = "DOWNGRADE"
    TERMINATE = "TERMINATE"


class AuditStatus(str, Enum):
    NOTICED = "NOTICED"
    IN_FIELDWORK = "IN_FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class TrainingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"


# All resources carry the four common properties of PRD §2.4:
# id, created_at, updated_at, version.

class CountryRiskProfile(TypedDict, total=False):
    id: str
    country_code: str
    cpi_score: int
    sanctioned: bool
    created_at: str
    updated_at: str
    version: int


class RiskScoringPolicy(TypedDict, total=False):
    id: str
    policy_status: str
    w_country: int
    w_industry: int
    w_touchpoint: int
    tier_medium_min: int
    tier_high_min: int
    tier_critical_min: int
    commission_base_cap_pct: float
    commission_hard_cap_pct: float
    created_at: str
    updated_at: str
    version: int


class ThirdParty(TypedDict, total=False):
    id: str
    legal_name: str
    country_code: str
    industry: str
    government_touchpoint: str
    sponsor_user_id: str
    onboarding_status: str
    risk_score_provisional: Optional[int]
    risk_score_final: Optional[int]
    risk_tier: Optional[str]
    approval_tier_snapshot: Optional[str]
    approved_policy_id: Optional[str]
    diligence_expires_at: Optional[str]
    gov_gift_rolling_12m_cents: int
    created_at: str
    updated_at: str
    version: int


class ScreeningCheck(TypedDict, total=False):
    id: str
    third_party_id: str
    check_type: str
    check_status: str
    match_detail: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Questionnaire(TypedDict, total=False):
    id: str
    third_party_id: str
    questionnaire_status: str
    government_ownership_pct: Optional[int]
    has_facilitation_payments: Optional[bool]
    uses_sub_agents: Optional[bool]
    red_flag_count: Optional[int]
    return_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RedFlag(TypedDict, total=False):
    id: str
    third_party_id: str
    source_type: str
    source_ref_id: Optional[str]
    severity: str
    description: str
    flag_status: str
    escalated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscalationCase(TypedDict, total=False):
    id: str
    third_party_id: str
    case_status: str
    escalated_by_user_id: Optional[str]
    decision_outcome: Optional[str]
    conditions_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    third_party_id: str
    contract_status: str
    contract_value_cents: int
    start_date: str
    end_date: str
    clause_codes: list
    approved_payments_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    third_party_id: str
    cert_type: str
    cert_status: str
    document_ref: Optional[str]
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentRequest(TypedDict, total=False):
    id: str
    contract_id: str
    payment_type: str
    amount_cents: int
    ratio_pct: float
    enhanced_review_evidence: bool
    payment_status: str
    submitted_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GiftHospitalityEntry(TypedDict, total=False):
    id: str
    third_party_id: str
    entry_type: str
    recipient_is_government_official: bool
    value_cents: int
    fx_rate_to_usd: float
    value_usd_cents: int
    event_date: str
    entry_status: str
    requires_enhanced_approval: bool
    created_at: str
    updated_at: str
    version: int


class ReDiligenceCycle(TypedDict, total=False):
    id: str
    third_party_id: str
    cycle_status: str
    trigger_source: str
    due_date: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditExercise(TypedDict, total=False):
    id: str
    third_party_id: str
    audit_status: str
    notice_date: str
    fieldwork_start_date: str
    fieldwork_end_date: str
    findings_total: Optional[int]
    findings_substantiated_critical: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict, total=False):
    id: str
    assignee_user_id: str
    course_code: str
    due_date: str
    training_status: str
    created_at: str
    updated_at: str
    version: int
