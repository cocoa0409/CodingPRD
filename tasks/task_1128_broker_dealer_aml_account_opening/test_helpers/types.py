"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    REGISTERED_REP = "RegisteredRep"
    AML_ANALYST = "AMLAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SAR_OFFICER = "SAROfficer"
    OPERATIONS_ANALYST = "OperationsAnalyst"
    INDEPENDENT_AUDITOR = "IndependentAuditor"
    SYSTEM_ADMIN = "SystemAdmin"


class RepStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CustomerType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    LEGAL_ENTITY = "LEGAL_ENTITY"


class CountryRiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    PROHIBITED = "PROHIBITED"


class AccountLifecycle(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"


class AmlPosture(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    SEVERE = "SEVERE"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    PROHIBITED = "PROHIBITED"


class RiskVariant(str, Enum):
    INITIAL = "INITIAL"
    ONGOING = "ONGOING"


class ExposureTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class DocumentType(str, Enum):
    GOVERNMENT_ID = "GOVERNMENT_ID"
    FORMATION_DOC = "FORMATION_DOC"
    PROOF_OF_ADDRESS = "PROOF_OF_ADDRESS"
    W9 = "W9"


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class CertificationStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class EddReviewStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REFRESH_DUE = "REFRESH_DUE"


class TxnType(str, Enum):
    DEPOSIT_CERT = "DEPOSIT_CERT"
    DEPOSIT_DTC = "DEPOSIT_DTC"
    BUY = "BUY"
    SELL = "SELL"
    WIRE_OUT = "WIRE_OUT"
    JOURNAL = "JOURNAL"


class TransactionStatus(str, Enum):
    POSTED = "POSTED"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"
    REVERSED = "REVERSED"


class RuleCode(str, Enum):
    LPS_LIQUIDATION = "LPS_LIQUIDATION"
    LPS_DEPOSIT_LIQUIDATE = "LPS_DEPOSIT_LIQUIDATE"
    WIRE_VELOCITY = "WIRE_VELOCITY"
    STRUCTURING = "STRUCTURING"


class AlertStatus(str, Enum):
    NEW = "NEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED_TO_CASE = "ESCALATED_TO_CASE"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class CasePriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    SAR_RECOMMENDED = "SAR_RECOMMENDED"
    DECIDED_FILED = "DECIDED_FILED"
    DECIDED_NO_FILE = "DECIDED_NO_FILE"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class SarStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    SUPERSEDED = "SUPERSEDED"


class FincenRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCAN_COMPLETE = "SCAN_COMPLETE"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    OVERDUE = "OVERDUE"


class MatchBasis(str, Enum):
    TAX_ID_EXACT = "TAX_ID_EXACT"
    NAME_DOB = "NAME_DOB"
    NAME_EXACT = "NAME_EXACT"


class MatchStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CONFIRMED = "CONFIRMED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    RESOLVED = "RESOLVED"


class DepositStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ELIGIBILITY_REVIEW = "ELIGIBILITY_REVIEW"
    AUTHENTICITY_REVIEW = "AUTHENTICITY_REVIEW"
    CLEARANCE_HOLD = "CLEARANCE_HOLD"
    READY_TO_ACCEPT = "READY_TO_ACCEPT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REJECTED_SUSPICIOUS = "REJECTED_SUSPICIOUS"
    RESUBMITTED = "RESUBMITTED"


class DepositOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    REJECT_SUSPICIOUS = "REJECT_SUSPICIOUS"


class RegistryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ScopeUnit(str, Enum):
    AML_PROGRAM = "AML_PROGRAM"
    CIP_PROCESS = "CIP_PROCESS"
    SANCTIONS_SCREENING = "SANCTIONS_SCREENING"
    TRANSACTION_MONITORING = "TRANSACTION_MONITORING"


class EngagementStatus(str, Enum):
    PLANNED = "PLANNED"
    FIELDWORK = "FIELDWORK"
    REPORTED = "REPORTED"
    CLOSED = "CLOSED"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    REMEDIATED = "REMEDIATED"
    ACCEPTED_RISK = "ACCEPTED_RISK"


# --- Entity TypedDicts (all resources carry id/created_at/updated_at/version, PRD §2.4) ---


class RegisteredRep(TypedDict, total=False):
    id: str
    full_name: str
    crd_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    registered_rep_id: str
    customer_type: str
    full_name: str
    tax_id: str
    country_risk_tier: str
    is_pep: bool
    date_of_birth: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrokerageAccount(TypedDict, total=False):
    id: str
    customer_id: str
    product_set: List[str]
    lifecycle_status: str
    aml_posture: str
    risk_score: int
    risk_tier: str
    risk_variant_used: str
    exposure_30d_amount: float
    exposure_tier: str
    wire_velocity_30d_amount: float
    open_alert_count: int
    open_case_count: int
    has_suspicion_flag: bool
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IdentificationDocument(TypedDict, total=False):
    id: str
    customer_id: str
    doc_type: str
    document_number: str
    expiry_date: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BeneficialOwnershipCertification(TypedDict, total=False):
    id: str
    customer_id: str
    no_25pct_owner_attested: bool
    status: str
    certified_at: Optional[str]
    total_ownership_pct: float
    covered_owner_count: int
    created_at: str
    updated_at: str
    version: int


class BeneficialOwner(TypedDict, total=False):
    id: str
    certification_id: str
    full_name: str
    ownership_pct: float
    is_control_person: bool
    is_entity_owner: bool
    tax_id: Optional[str]
    date_of_birth: Optional[str]
    address: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EDDReview(TypedDict, total=False):
    id: str
    account_id: str
    period_start: str
    period_end: str
    trigger_reason: str
    prior_review_id: Optional[str]
    status: str
    refresh_due_date: Optional[str]
    tier_at_completion: Optional[str]
    decision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecurityTransaction(TypedDict, total=False):
    id: str
    account_id: str
    txn_type: str
    security_id: Optional[str]
    quantity: Optional[float]
    unit_price: Optional[float]
    amount: float
    is_low_priced: bool
    status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringRule(TypedDict, total=False):
    id: str
    rule_code: str
    threshold_amount: float
    window_days: int
    min_transaction_count: int
    enabled: bool
    created_at: str
    updated_at: str
    version: int


class MonitoringAlert(TypedDict, total=False):
    id: str
    rule_id: Optional[str]
    rule_code: str
    account_id: str
    transaction_id: Optional[str]
    window_start: str
    window_end: str
    aggregate_amount: float
    severity: int
    status: str
    close_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AMLCase(TypedDict, total=False):
    id: str
    account_id: str
    origin_alert_id: Optional[str]
    priority: str
    status: str
    recommending_analyst_id: Optional[str]
    initial_detection_date: Optional[str]
    reopen_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SARFiling(TypedDict, total=False):
    id: str
    case_id: str
    prior_filing_id: Optional[str]
    narrative: str
    activity_start: str
    activity_end: str
    status: str
    filing_deadline: str
    filed_at: Optional[str]
    filed_late: Optional[bool]
    continuing_review_due_date: Optional[str]
    continuing_review_count: int
    last_continuing_review_at: Optional[str]
    review_overdue: bool
    created_at: str
    updated_at: str
    version: int


class FinCENRequest314A(TypedDict, total=False):
    id: str
    request_reference: str
    subjects: List[Dict[str, Any]]
    received_at: str
    response_deadline: str
    status: str
    match_count: int
    responded_at: Optional[str]
    responded_late: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class Match314A(TypedDict, total=False):
    id: str
    request_id: str
    account_id: str
    matched_subject_name: str
    match_basis: str
    status: str
    reviewed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhysicalCertificateDeposit(TypedDict, total=False):
    id: str
    account_id: str
    transaction_id: str
    certificate_number: str
    cusip: str
    security_name: str
    quantity: int
    unit_price: float
    has_restrictive_legend: bool
    is_low_priced: bool
    status: str
    hold_release_date: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LostStolenCertificateEntry(TypedDict, total=False):
    id: str
    certificate_number: str
    cusip: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEngagement(TypedDict, total=False):
    id: str
    scope_unit: str
    start_date: str
    end_date: str
    lead_auditor_id: str
    report_summary: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    engagement_id: str
    severity: str
    description: str
    remediation_deadline: str
    is_overdue: bool
    status: str
    remediation_note: Optional[str]
    submitted_by: Optional[str]
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
