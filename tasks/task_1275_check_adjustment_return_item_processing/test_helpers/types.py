"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    OPERATIONS_ADMIN = "OperationsAdmin"
    ITEM_PROCESSOR = "ItemProcessor"
    ADJUSTMENT_ANALYST = "AdjustmentAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER_SERVICE = "CustomerService"
    CUSTOMER = "Customer"


class ClearingBankStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DepositorAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    HIGH_RISK = "HIGH_RISK"


class FreezeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class CheckItemStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PRESENTED = "PRESENTED"
    PAID = "PAID"
    RETURNED = "RETURNED"
    DUPLICATE_REJECTED = "DUPLICATE_REJECTED"
    DEPOSIT_REJECTED = "DEPOSIT_REJECTED"


class CaptureChannel(str, Enum):
    BRANCH = "BRANCH"
    ATM = "ATM"
    MOBILE = "MOBILE"
    RDC = "RDC"


class HoldSource(str, Enum):
    AUTO_LARGE_ITEM = "AUTO_LARGE_ITEM"
    MANUAL = "MANUAL"


class HoldDecisionValue(str, Enum):
    RELEASE_FUNDS = "RELEASE_FUNDS"
    EXTEND_HOLD = "EXTEND_HOLD"
    RETURN_ITEM = "RETURN_ITEM"


class HoldStatus(str, Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"
    EXPIRED = "EXPIRED"


class ReturnReasonCode(str, Enum):
    NSF = "NSF"
    STOP_PAYMENT = "STOP_PAYMENT"
    CLOSED_ACCOUNT = "CLOSED_ACCOUNT"
    MISSING_ENDORSEMENT = "MISSING_ENDORSEMENT"
    ALTERED_OR_FICTITIOUS = "ALTERED_OR_FICTITIOUS"
    IMAGE_NONCONFORMING = "IMAGE_NONCONFORMING"
    DUPLICATE_PRESENTMENT = "DUPLICATE_PRESENTMENT"
    REFER_TO_MAKER = "REFER_TO_MAKER"


class ReturnEventStatus(str, Enum):
    PENDING_CODING = "PENDING_CODING"
    CODED = "CODED"


class AdjustmentCaseType(str, Enum):
    RETURN_ITEM = "RETURN_ITEM"
    ENCODING_ERROR = "ENCODING_ERROR"
    IMAGE_WARRANTY = "IMAGE_WARRANTY"
    DUPLICATE_PRESENTMENT = "DUPLICATE_PRESENTMENT"
    LARGE_ITEM_REVIEW = "LARGE_ITEM_REVIEW"


class AdjustmentCaseStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class CaseDisposition(str, Enum):
    CREDIT_CUSTOMER = "CREDIT_CUSTOMER"
    DEBIT_CUSTOMER = "DEBIT_CUSTOMER"
    NO_ACTION = "NO_ACTION"


class AdjustmentClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"
    ESCALATED = "ESCALATED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ClaimSettleOutcome(str, Enum):
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class WarrantyClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    HONORED = "HONORED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    WRITTEN_OFF = "WRITTEN_OFF"


class WarrantySettleOutcome(str, Enum):
    HONORED = "HONORED"
    REJECTED = "REJECTED"


class NotificationType(str, Enum):
    RETURN_NOTICE = "RETURN_NOTICE"
    CASE_CLOSED = "CASE_CLOSED"
    DUPLICATE_NOTICE = "DUPLICATE_NOTICE"
    DEPOSIT_REJECTED_NOTICE = "DEPOSIT_REJECTED_NOTICE"
    LARGE_ITEM_HOLD_NOTICE = "LARGE_ITEM_HOLD_NOTICE"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    BREACHED = "BREACHED"


class FeeStatus(str, Enum):
    POSTED = "POSTED"
    WAIVED = "WAIVED"


class RecreditStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PROVISIONALLY_CREDITED = "PROVISIONALLY_CREDITED"
    CONFIRMED = "CONFIRMED"
    REVOKED = "REVOKED"


class RecreditFinalizeOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    REVOKED = "REVOKED"


class LedgerEntryType(str, Enum):
    OPENING_CREDIT = "OPENING_CREDIT"
    DEPOSIT_CREDIT = "DEPOSIT_CREDIT"
    PROVISIONAL_REVERSAL = "PROVISIONAL_REVERSAL"
    SETTLEMENT_CREDIT = "SETTLEMENT_CREDIT"
    ITEM_RETURN_DEBIT = "ITEM_RETURN_DEBIT"
    DUPLICATE_REVERSAL_CREDIT = "DUPLICATE_REVERSAL_CREDIT"
    FEE_DEBIT = "FEE_DEBIT"
    FEE_WAIVER_CREDIT = "FEE_WAIVER_CREDIT"
    RECREDIT_PROVISIONAL_CREDIT = "RECREDIT_PROVISIONAL_CREDIT"
    RECREDIT_CLAWBACK_DEBIT = "RECREDIT_CLAWBACK_DEBIT"
    ADJUSTMENT_CREDIT = "ADJUSTMENT_CREDIT"
    ADJUSTMENT_DEBIT = "ADJUSTMENT_DEBIT"


# --- Entity TypedDicts -------------------------------------------------------
# Clearing banks, depositor accounts, freezes, items, holds, return events,
# cases, claims, warranties, fees, and recredit requests carry the standard
# system-managed fields (id, created_at, updated_at, version). Notifications
# and ledger entries carry only id and created_at (PRD §2.5).


class ClearingBank(TypedDict, total=False):
    id: str
    name: str
    routing_number: str
    claim_window_business_days: int
    warranty_window_days: int
    daily_claim_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DepositorAccount(TypedDict, total=False):
    id: str
    customer_name: str
    account_number: str
    status: str
    risk_tier: str
    reg_cc_eligible: bool
    opening_balance_cents: int
    available_balance_cents: int
    settled_balance_cents: int
    returned_item_count_30d: int
    created_at: str
    updated_at: str
    version: int


class AccountFreeze(TypedDict, total=False):
    id: str
    depositor_account_id: str
    start_at: str
    end_at: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CheckItem(TypedDict, total=False):
    id: str
    depositor_account_id: str
    clearing_bank_id: str
    item_reference: str
    amount_cents: int
    encoded_amount_cents: int
    image_quality_score: int
    capture_channel: str
    status: str
    is_large_item: bool
    presentment_count: int
    duplicate_of_item_id: Optional[str]
    presented_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HoldDecision(TypedDict, total=False):
    id: str
    check_item_id: str
    source: str
    window_start_at: str
    hold_until: str
    decision: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnEvent(TypedDict, total=False):
    id: str
    check_item_id: str
    received_at: str
    reason_code: Optional[str]
    coded_at: Optional[str]
    re_presentment_eligible: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdjustmentCase(TypedDict, total=False):
    id: str
    case_type: str
    check_item_id: str
    return_event_id: Optional[str]
    status: str
    assigned_analyst_id: Optional[str]
    disposition: Optional[str]
    resolution_amount_cents: Optional[int]
    reopen_count: int
    escalated_at: Optional[str]
    resolved_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdjustmentClaim(TypedDict, total=False):
    id: str
    adjustment_case_id: str
    clearing_bank_id: str
    claimed_amount_cents: int
    created_by_user_id: str
    status: str
    submitted_at: Optional[str]
    clearing_bank_ref: Optional[str]
    recovered_amount_cents: Optional[int]
    settled_at: Optional[str]
    aging_calendar_days: int
    aging_business_days: int
    write_off_reason: Optional[str]
    written_off_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    adjustment_case_id: str
    claimed_amount_cents: int
    created_by_user_id: str
    status: str
    deadline_at: str
    submitted_at: Optional[str]
    recovered_amount_cents: Optional[int]
    settled_at: Optional[str]
    aging_calendar_days: int
    aging_business_days: int
    write_off_reason: Optional[str]
    written_off_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only / deliver-once resources: only id + created_at (no updated_at,
# no version) per PRD §2.5.
class CustomerNotification(TypedDict, total=False):
    id: str
    depositor_account_id: str
    adjustment_case_id: Optional[str]
    notification_type: str
    message: str
    due_at: str
    status: str
    delivered_at: Optional[str]
    created_at: str


class FeeAssessment(TypedDict, total=False):
    id: str
    depositor_account_id: str
    adjustment_case_id: Optional[str]
    return_event_id: Optional[str]
    fee_type: str
    amount_cents: int
    status: str
    waived_by_user_id: Optional[str]
    waive_reason: Optional[str]
    waived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecreditRequest(TypedDict, total=False):
    id: str
    depositor_account_id: str
    check_item_id: str
    claimed_amount_cents: int
    reason: str
    status: str
    principal_amount_cents: int
    interest_cents: int
    provisional_amount_cents: int
    submitted_at: str
    provisioned_at: Optional[str]
    provisioned_late: Optional[bool]
    breach_flagged: bool
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    id: str
    depositor_account_id: str
    entry_type: str
    amount_cents: int
    provisional: bool
    memo: Optional[str]
    check_item_id: Optional[str]
    adjustment_case_id: Optional[str]
    fee_assessment_id: Optional[str]
    recredit_request_id: Optional[str]
    created_at: str
