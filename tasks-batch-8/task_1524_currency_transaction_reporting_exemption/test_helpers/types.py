"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, Any


class BranchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CustomerType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS_NONLISTED = "BUSINESS_NONLISTED"
    BUSINESS_LISTED = "BUSINESS_LISTED"
    BANK = "BANK"
    GOVERNMENT_AGENCY = "GOVERNMENT_AGENCY"
    PAYROLL_CUSTOMER = "PAYROLL_CUSTOMER"


class CashDirection(str, Enum):
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"


class CashTransactionStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class InstrumentType(str, Enum):
    CASHIERS_CHECK = "CASHIERS_CHECK"
    MONEY_ORDER = "MONEY_ORDER"
    TRAVELERS_CHECK = "TRAVELERS_CHECK"


class InstrumentSaleStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class CTRStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    FILED = "FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    AMENDMENT_REQUIRED = "AMENDMENT_REQUIRED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class FilingType(str, Enum):
    INITIAL = "INITIAL"
    CORRECTION = "CORRECTION"


class FilingChannel(str, Enum):
    EFILE = "EFILE"
    PAPER = "PAPER"


class ExemptionPhase(str, Enum):
    PHASE_I = "PHASE_I"
    PHASE_II = "PHASE_II"


class ExemptionStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    REVIEW_DUE = "REVIEW_DUE"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class RevocationReason(str, Enum):
    REVIEW_FAILED = "REVIEW_FAILED"
    MANUAL_REVOKE = "MANUAL_REVOKE"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    REFERRED = "REFERRED"
    DISMISSED = "DISMISSED"


class DetectionSource(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class ReviewOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Regulator(str, Enum):
    FINCEN = "FINCEN"
    OCC = "OCC"
    FDIC = "FDIC"
    STATE = "STATE"


class ExamCaseStatus(str, Enum):
    OPEN = "OPEN"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class FindingSeverity(str, Enum):
    OBSERVATION = "OBSERVATION"
    DEFICIENCY = "DEFICIENCY"
    VIOLATION = "VIOLATION"


class FindingTargetType(str, Enum):
    CTR = "CTR"
    EXEMPTION_DESIGNATION = "EXEMPTION_DESIGNATION"
    STRUCTURING_ALERT = "STRUCTURING_ALERT"
    MONETARY_INSTRUMENT_SALE = "MONETARY_INSTRUMENT_SALE"
    CASH_TRANSACTION = "CASH_TRANSACTION"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATED = "REMEDIATED"
    VERIFIED = "VERIFIED"


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    BRANCH_MANAGER = "BranchManager"
    TELLER = "Teller"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    BSA_OFFICER = "BSAOfficer"
    EXAMINER = "Examiner"


# --- Entity TypedDicts (common_fields: true unless noted) ---

class Branch(TypedDict, total=False):
    id: str
    name: str
    branch_code: str
    region: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    tin: Optional[str]
    customer_type: str
    account_opened_date: str
    status: str
    structuring_referral_count: int
    active_exemption_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CashTransaction(TypedDict, total=False):
    id: str
    customer_id: str
    branch_id: str
    direction: str
    amount_cents: int
    occurred_at: str
    business_date: str
    conductor_name: Optional[str]
    status: str
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonetaryInstrumentSale(TypedDict, total=False):
    id: str
    customer_id: str
    branch_id: str
    instrument_type: str
    amount_cents: int
    occurred_at: str
    business_date: str
    purchaser_name: Optional[str]
    purchaser_tin: Optional[str]
    purchaser_address: Optional[str]
    purchaser_id_number: Optional[str]
    record_required: bool
    fee_cents: int
    retention_until: str
    status: str
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DailyCashAggregation(TypedDict, total=False):
    id: str
    customer_id: str
    business_date: str
    total_cash_in_cents: int
    total_cash_out_cents: int
    transaction_count: int
    instrument_sale_count: int
    instrument_fee_total_cents: int
    raw_reportable_in: bool
    raw_reportable_out: bool
    covered_in: bool
    covered_out: bool
    ctr_required: bool
    last_recomputed_at: str
    created_at: str
    updated_at: str
    version: int


class CTR(TypedDict, total=False):
    id: str
    customer_id: str
    business_date: str
    filing_type: str
    prior_ctr_id: Optional[str]
    amendment_reason: Optional[str]
    snapshot_cash_in_cents: int
    snapshot_cash_out_cents: int
    due_date_efile: str
    due_date_paper: str
    status: str
    validated_by_id: Optional[str]
    filed_by_id: Optional[str]
    filing_channel: Optional[str]
    filed_at: Optional[str]
    filed_late: Optional[bool]
    is_late: bool
    acknowledged_at: Optional[str]
    regulator_tracking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExemptionDesignation(TypedDict, total=False):
    id: str
    customer_id: str
    phase: str
    covers_cash_in: bool
    covers_cash_out: bool
    stock_exchange: Optional[str]
    note: Optional[str]
    status: str
    requested_by_id: str
    designated_by_officer_id: Optional[str]
    designated_at: Optional[str]
    last_reviewed_at: Optional[str]
    review_due_date: Optional[str]
    revocation_reason: Optional[str]
    eligibility_snapshot: Optional[dict]
    created_at: str
    updated_at: str
    version: int


class StructuringAlert(TypedDict, total=False):
    id: str
    customer_id: str
    detection_source: str
    window_start_date: str
    window_end_date: str
    detected_amount_cents: int
    distinct_day_count: int
    distinct_branch_count: int
    risk_score: int
    status: str
    note: Optional[str]
    referred_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExaminationCase(TypedDict, total=False):
    id: str
    regulator: str
    case_number: str
    scope_start_date: str
    scope_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExaminationFinding(TypedDict, total=False):
    id: str
    case_id: str
    severity: str
    target_type: str
    target_id: str
    description: str
    status: str
    remediation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# AuditEvent: common_fields=false — append-only, NO updated_at, NO version
class AuditEvent(TypedDict, total=False):
    id: str
    sequence_no: int
    actor_role: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    details: dict
    prev_hash: str
    event_hash: str
    created_at: str
