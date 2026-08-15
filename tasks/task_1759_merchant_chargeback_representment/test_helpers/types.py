"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# --- Enums ---

class UserRole(str, Enum):
    ACQUIRER_OPS = "AcquirerOps"
    MERCHANT_USER = "MerchantUser"
    RISK_OFFICER = "RiskOfficer"
    FINANCE_OPS = "FinanceOps"


class MerchantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    HIGH_RISK = "HIGH_RISK"


class ReserveMode(str, Enum):
    FIXED_TIER = "FIXED_TIER"
    EXPOSURE_BASED = "EXPOSURE_BASED"


class Network(str, Enum):
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"


class ReasonCategory(str, Enum):
    FRAUD = "FRAUD"
    AUTHORIZATION = "AUTHORIZATION"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    CONSUMER_DISPUTE = "CONSUMER_DISPUTE"


class TransactionStatus(str, Enum):
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    CHARGED_BACK = "CHARGED_BACK"


class CaseStatus(str, Enum):
    RECEIVED = "RECEIVED"
    MERCHANT_NOTIFIED = "MERCHANT_NOTIFIED"
    REPRESENTED = "REPRESENTED"
    DECIDED_WON = "DECIDED_WON"
    DECIDED_LOST = "DECIDED_LOST"
    MERCHANT_ACCEPTED = "MERCHANT_ACCEPTED"
    PRE_ARBITRATION = "PRE_ARBITRATION"
    EXPIRED = "EXPIRED"
    REVERSED = "REVERSED"


class FundsStatus(str, Enum):
    MERCHANT_DEBITED = "MERCHANT_DEBITED"
    FUNDS_RETURNED = "FUNDS_RETURNED"
    DEBIT_FINAL = "DEBIT_FINAL"
    NOT_DEBITED = "NOT_DEBITED"


class EvidenceType(str, Enum):
    RECEIPT = "RECEIPT"
    AVS_MATCH = "AVS_MATCH"
    CVV_MATCH = "CVV_MATCH"
    DELIVERY_PROOF = "DELIVERY_PROOF"
    SIGNED_AGREEMENT = "SIGNED_AGREEMENT"
    REFUND_PROOF = "REFUND_PROOF"
    PRIOR_TXN_HISTORY = "PRIOR_TXN_HISTORY"
    IP_DEVICE_LOG = "IP_DEVICE_LOG"
    CARDHOLDER_COMMUNICATION = "CARDHOLDER_COMMUNICATION"


class EvidenceStatus(str, Enum):
    DRAFT = "DRAFT"
    ATTACHED = "ATTACHED"
    WITHDRAWN = "WITHDRAWN"


class RepresentmentStatus(str, Enum):
    ASSEMBLED = "ASSEMBLED"
    SUBMITTED = "SUBMITTED"
    WON = "WON"
    PARTIAL_WON = "PARTIAL_WON"
    LOST = "LOST"
    RETURNED_FOR_CURE = "RETURNED_FOR_CURE"
    SUPERSEDED = "SUPERSEDED"


class FeeKind(str, Enum):
    CHARGEBACK_FEE = "CHARGEBACK_FEE"
    PROGRAM_FINE = "PROGRAM_FINE"
    ARBITRATION_FEE = "ARBITRATION_FEE"


class FeeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class LedgerEntryType(str, Enum):
    HOLD = "HOLD"
    RELEASE = "RELEASE"
    FORFEIT = "FORFEIT"


class LedgerSourceKind(str, Enum):
    TRANSACTION_SETTLEMENT = "TRANSACTION_SETTLEMENT"
    CHARGEBACK_RECEIPT = "CHARGEBACK_RECEIPT"
    CHARGEBACK_WON = "CHARGEBACK_WON"
    CHARGEBACK_LOST = "CHARGEBACK_LOST"
    SCHEDULED_RELEASE = "SCHEDULED_RELEASE"


class ProgramCode(str, Enum):
    VDMP_STANDARD = "VDMP_STANDARD"
    VDMP_EXCESSIVE = "VDMP_EXCESSIVE"
    ECM = "ECM"
    HECM = "HECM"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMEDIATION = "REMEDIATION"
    EXITED = "EXITED"


class RootCauseCode(str, Enum):
    FRAUD_GAP = "FRAUD_GAP"
    FULFILLMENT_GAP = "FULFILLMENT_GAP"
    CUSTOMER_SERVICE_GAP = "CUSTOMER_SERVICE_GAP"
    POLICY_GAP = "POLICY_GAP"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"


class AlertType(str, Enum):
    FRAUD_ALERT = "FRAUD_ALERT"
    DISPUTE_ALERT = "DISPUTE_ALERT"
    REFUND_OPPORTUNITY = "REFUND_OPPORTUNITY"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACTIONED_REFUND = "ACTIONED_REFUND"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"


class ModuleCode(str, Enum):
    CHARGEBACK_BASICS = "CHARGEBACK_BASICS"
    EVIDENCE_BEST_PRACTICE = "EVIDENCE_BEST_PRACTICE"
    FRAUD_PREVENTION = "FRAUD_PREVENTION"


class AssignedReason(str, Enum):
    PROGRAM_ENROLLMENT = "PROGRAM_ENROLLMENT"


# --- Entity TypedDicts ---
# Entities with the full common field set carry id + created_at + updated_at + version.
# ReasonCodeRule, ReserveLedgerEntry, and RatioSnapshot are immutable once created
# and therefore carry only id + created_at (PRD §2.4).


class Merchant(TypedDict, total=False):
    id: str
    legal_name: str
    merchant_category_code: str
    risk_tier: str
    reserve_mode: str
    reserve_rate_bps: int
    status: str
    clearing_balance_cents: int
    current_count_ratio_bps: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ReasonCodeRule(TypedDict, total=False):
    id: str
    network: str
    reason_code: str
    category: str
    required_evidence_types: List[str]
    merchant_response_days: int
    representment_days: int
    chargeback_fee_cents: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str


class Transaction(TypedDict, total=False):
    id: str
    merchant_id: str
    external_ref: str
    network: str
    amount_cents: int
    occurred_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict, total=False):
    id: str
    merchant_id: str
    transaction_external_ref: str
    transaction_id: str
    network_case_id: str
    reason_code: str
    network: str
    amount_cents: int
    received_at: str
    merchant_notified_at: Optional[str]
    merchant_response_due_at: Optional[str]
    representment_due_at: str
    case_status: str
    funds_status: str
    recredited_cents: int
    is_ratio_counted: bool
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    chargeback_id: str
    evidence_type: str
    document_uri: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Representment(TypedDict, total=False):
    id: str
    chargeback_id: str
    evidence_item_ids: List[str]
    status: str
    cure_count: int
    submitted_at: Optional[str]
    won_amount_cents: Optional[int]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict, total=False):
    id: str
    merchant_id: str
    chargeback_id: Optional[str]
    enrollment_id: Optional[str]
    kind: str
    amount_cents: int
    status: str
    assessed_by_user_id: str
    waived_by_user_id: Optional[str]
    settled_at: Optional[str]
    waived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReserveAccount(TypedDict, total=False):
    id: str
    merchant_id: str
    held_cents: int
    target_cents: int
    last_recomputed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReserveLedgerEntry(TypedDict, total=False):
    id: str
    reserve_account_id: str
    entry_type: str
    amount_cents: int
    source_kind: str
    source_id: Optional[str]
    release_eligible_at: Optional[str]
    created_at: str


class RatioSnapshot(TypedDict, total=False):
    id: str
    merchant_id: str
    network: str
    period_month: str
    sales_count: int
    sales_amount_cents: int
    chargeback_count: int
    gross_chargeback_count: int
    count_ratio_bps: int
    gross_count_ratio_bps: int
    computed_at: str
    created_at: str


class ProgramEnrollment(TypedDict, total=False):
    id: str
    merchant_id: str
    network: str
    program_code: str
    enrolled_month: str
    exited_month: Optional[str]
    months_over_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RemediationPlan(TypedDict, total=False):
    id: str
    enrollment_id: str
    root_cause_codes: List[str]
    corrective_actions: List[str]
    status: str
    reviewed_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreventionAlert(TypedDict, total=False):
    id: str
    transaction_id: str
    merchant_id: str
    alert_type: str
    received_at: str
    response_due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EducationAssignment(TypedDict, total=False):
    id: str
    merchant_id: str
    enrollment_ref: Optional[str]
    module_code: str
    assigned_reason: str
    status: str
    assigned_at: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
