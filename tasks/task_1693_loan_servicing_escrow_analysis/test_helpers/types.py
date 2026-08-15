"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ESCROW_ANALYST = "EscrowAnalyst"
    DISBURSEMENT_PROCESSOR = "DisbursementProcessor"
    PAYEE_VERIFIER = "PayeeVerifier"
    INSURANCE_SPECIALIST = "InsuranceSpecialist"
    BORROWER = "Borrower"


class LoanStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class AccountStatus(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class HoldStatus(str, Enum):
    NONE = "NONE"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"


class LedgerEntryType(str, Enum):
    DEPOSIT = "DEPOSIT"
    DISBURSEMENT = "DISBURSEMENT"
    DISBURSEMENT_RETURN = "DISBURSEMENT_RETURN"
    ADVANCE_ISSUED = "ADVANCE_ISSUED"
    ADVANCE_RECOVERY = "ADVANCE_RECOVERY"
    SURPLUS_REFUND = "SURPLUS_REFUND"
    FORCE_PLACEMENT_CHARGE = "FORCE_PLACEMENT_CHARGE"
    FORCE_PLACEMENT_REFUND = "FORCE_PLACEMENT_REFUND"
    ERROR_CORRECTION = "ERROR_CORRECTION"


class ExpenseType(str, Enum):
    PROPERTY_TAX = "PROPERTY_TAX"
    HAZARD_INSURANCE = "HAZARD_INSURANCE"
    FLOOD_INSURANCE = "FLOOD_INSURANCE"
    PMI = "PMI"


class LineItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class PayeeType(str, Enum):
    TAX_AUTHORITY = "TAX_AUTHORITY"
    INSURANCE_CARRIER = "INSURANCE_CARRIER"
    PMI_PROVIDER = "PMI_PROVIDER"


class VerificationStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BLOCKED = "BLOCKED"
    RELEASED = "RELEASED"
    CLEARED = "CLEARED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class PolicyType(str, Enum):
    HAZARD = "HAZARD"
    FLOOD = "FLOOD"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    NOTICE_1_SENT = "NOTICE_1_SENT"
    NOTICE_2_SENT = "NOTICE_2_SENT"
    FORCE_PLACED = "FORCE_PLACED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"
    EXPIRED_CLOSED = "EXPIRED_CLOSED"


class DayCountConvention(str, Enum):
    ACT_365 = "ACT_365"
    CONTRACT_30_360 = "CONTRACT_30_360"


class TaxRecordStatus(str, Enum):
    MONITORING = "MONITORING"
    DUE_SOON = "DUE_SOON"
    DELINQUENT = "DELINQUENT"
    PENALTY_ACCRUING = "PENALTY_ACCRUING"
    REDEMPTION_RISK = "REDEMPTION_RISK"
    PAID_CURRENT = "PAID_CURRENT"
    PAID_DELINQUENT = "PAID_DELINQUENT"


class PenaltyMethod(str, Enum):
    SIMPLE = "SIMPLE"
    COMPOUND = "COMPOUND"


class AnalysisMethod(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    LEDGER_ACTUAL = "LEDGER_ACTUAL"


class AnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    STATEMENT_ISSUED = "STATEMENT_ISSUED"
    EFFECTIVE = "EFFECTIVE"
    REOPENED = "REOPENED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class NoticeType(str, Enum):
    PAYMENT_CHANGE = "PAYMENT_CHANGE"
    SHORTAGE = "SHORTAGE"
    DEFICIENCY = "DEFICIENCY"
    SURPLUS = "SURPLUS"


class ShortageOption(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    SPREAD_12 = "SPREAD_12"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class AdvanceReason(str, Enum):
    DISBURSEMENT_SHORTFALL = "DISBURSEMENT_SHORTFALL"
    FORCE_PLACEMENT_PREMIUM = "FORCE_PLACEMENT_PREMIUM"
    MANUAL_CORRECTION = "MANUAL_CORRECTION"


class AdvanceStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ErrorType(str, Enum):
    DISBURSEMENT_FAILURE = "DISBURSEMENT_FAILURE"
    DISBURSEMENT_AMOUNT_ERROR = "DISBURSEMENT_AMOUNT_ERROR"
    UNTIMELY_DISBURSEMENT = "UNTIMELY_DISBURSEMENT"
    FORCE_PLACEMENT_ERROR = "FORCE_PLACEMENT_ERROR"
    ANALYSIS_ERROR = "ANALYSIS_ERROR"
    PAYMENT_APPLICATION_ERROR = "PAYMENT_APPLICATION_ERROR"
    OTHER_COVERED = "OTHER_COVERED"


class CaseStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    EXTENDED = "EXTENDED"
    RESOLVED_CORRECTED = "RESOLVED_CORRECTED"
    RESOLVED_NO_ERROR = "RESOLVED_NO_ERROR"
    DISMISSED_NOT_COVERED = "DISMISSED_NOT_COVERED"


class CaseOutcome(str, Enum):
    CORRECTED = "CORRECTED"
    NO_ERROR = "NO_ERROR"
    DISMISSED = "DISMISSED"


class Timeliness(str, Enum):
    ON_TIME = "ON_TIME"
    LATE = "LATE"


# --- Entity TypedDicts ---
# All entities except EscrowLedgerEntry carry id/created_at/updated_at/version
# (PRD §2.4). Ledger entries are immutable and carry only id + created_at.


class Loan(TypedDict):
    id: str
    loan_number: str
    borrower_name: str
    principal_balance_cents: int
    monthly_pi_cents: int
    escrow_required: bool
    closing_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict):
    id: str
    loan_id: str
    account_status: str
    hold_status: str
    balance_cents: int
    target_cushion_cents: int
    monthly_escrow_cents: int
    next_analysis_due_date: str
    last_analysis_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EscrowLedgerEntry(TypedDict):
    # Append-only: only id + created_at, NO updated_at / version (PRD §2.4).
    id: str
    escrow_account_id: str
    entry_type: str
    amount_cents: int
    effective_date: str
    running_balance_cents: int
    source_entity_type: str
    source_entity_id: str
    note: str
    created_at: str


class EscrowLineItem(TypedDict):
    id: str
    escrow_account_id: str
    payee_id: str
    expense_type: str
    expected_annual_amount_cents: int
    installments_per_year: int
    first_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payee(TypedDict):
    id: str
    payee_type: str
    legal_name: str
    remit_to_address: str
    ach_routing_mask: str
    created_by_user_id: str
    verification_status: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    verification_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    escrow_account_id: str
    line_item_id: str
    payee_id: str
    amount_cents: int
    due_date: str
    scheduled_release_date: str
    status: str
    scheduled_by_user_id: str
    released_by_user_id: Optional[str]
    released_at: Optional[str]
    cleared_at: Optional[str]
    returned_at: Optional[str]
    late_release: bool
    ledger_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    loan_id: str
    policy_type: str
    carrier_name: str
    policy_number: str
    coverage_start_date: str
    coverage_end_date: str
    annual_premium_cents: int
    status: str
    notice_1_sent_at: Optional[str]
    notice_2_sent_at: Optional[str]
    force_placed_at: Optional[str]
    fp_premium_cents: Optional[int]
    fp_coverage_end: Optional[str]
    day_count_convention: str
    fp_refund_cents: Optional[int]
    refund_processed_at: Optional[str]
    refund_timeliness: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxMonitoringRecord(TypedDict):
    id: str
    loan_id: str
    parcel_number: str
    tax_year: int
    installment_sequence: int
    amount_due_cents: int
    due_date: str
    grace_period_days: int
    monthly_penalty_rate_bps: int
    penalty_method: str
    status: str
    delinquent_since: Optional[str]
    accrued_penalty_cents: int
    paid_via_disbursement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscrowAnalysisCycle(TypedDict):
    id: str
    escrow_account_id: str
    analysis_year: int
    projection_start_date: str
    method: str
    status: str
    window_end_date: str
    computed_at: Optional[str]
    statement_issued_at: Optional[str]
    statement_due_date: Optional[str]
    statement_timeliness: Optional[str]
    start_balance_cents: Optional[int]
    projected_annual_disbursements_cents: Optional[int]
    cushion_target_cents: Optional[int]
    lowest_projected_balance_cents: Optional[int]
    shortage_cents: int
    deficiency_cents: int
    surplus_cents: int
    base_monthly_escrow_cents: Optional[int]
    spread_monthly_cents: int
    spread_first_month_cents: int
    new_monthly_escrow_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PaymentChangeNotice(TypedDict):
    id: str
    analysis_id: str
    notice_type: str
    old_monthly_escrow_cents: int
    new_monthly_escrow_cents: int
    shortage_option: Optional[str]
    effective_date: str
    send_by_date: str
    sent_at: Optional[str]
    timeliness: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EscrowAdvance(TypedDict):
    id: str
    escrow_account_id: str
    disbursement_id: Optional[str]
    reason: str
    amount_cents: int
    recovered_cents: int
    written_off_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ErrorResolutionCase(TypedDict):
    id: str
    loan_id: str
    error_type: str
    description: str
    asserted_amount_cents: Optional[int]
    status: str
    received_at: str
    acknowledged_at: Optional[str]
    ack_deadline: str
    ack_timeliness: Optional[str]
    assigned_to_user_id: Optional[str]
    resolution_deadline: str
    resolved_at: Optional[str]
    resolution_timeliness: Optional[str]
    resolved_by_user_id: Optional[str]
    outcome: Optional[str]
    correction_amount_cents: Optional[int]
    resolution_note: str
    created_at: str
    updated_at: str
    version: int
