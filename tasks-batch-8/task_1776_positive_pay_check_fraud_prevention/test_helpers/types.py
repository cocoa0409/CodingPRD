"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    BANK_TREASURY_MANAGER = "BankTreasuryManager"
    BANK_OPS = "BankOps"
    CUSTOMER_ADMIN = "CustomerAdmin"
    CUSTOMER_MANAGER = "CustomerManager"
    CUSTOMER_DECISION_MAKER = "CustomerDecisionMaker"
    CUSTOMER_VIEWER = "CustomerViewer"


class EnrollmentTier(str, Enum):
    POSITIVE_PAY = "POSITIVE_PAY"
    PAYEE_POSITIVE_PAY = "PAYEE_POSITIVE_PAY"
    REVERSE_POSITIVE_PAY = "REVERSE_POSITIVE_PAY"


class DefaultDecision(str, Enum):
    PAY = "PAY"
    RETURN = "RETURN"


class DeadlineMode(str, Enum):
    SAME_DAY_CUTOFF = "SAME_DAY_CUTOFF"
    ROLLING_HOURS = "ROLLING_HOURS"


class EnrollmentStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EnrollmentUserRole(str, Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    DECISION_MAKER = "DECISION_MAKER"
    VIEWER = "VIEWER"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVIEW_HOLD = "REVIEW_HOLD"
    CLOSED = "CLOSED"


class IssueFileStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED = "REJECTED"


class IssuedCheckStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CONSUMED = "CONSUMED"
    VOIDED = "VOIDED"
    STALE_DATED = "STALE_DATED"


class PresentedItemStatus(str, Enum):
    RECEIVED = "RECEIVED"
    EXCEPTION_HELD = "EXCEPTION_HELD"
    PAID = "PAID"
    RETURNED = "RETURNED"
    DEFAULT_PAID = "DEFAULT_PAID"
    DEFAULT_RETURNED = "DEFAULT_RETURNED"
    REVERSED = "REVERSED"


class MatchResult(str, Enum):
    CLEAN = "CLEAN"
    NO_ISSUE_RECORD = "NO_ISSUE_RECORD"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    PAYEE_MISMATCH = "PAYEE_MISMATCH"
    VOIDED_ITEM = "VOIDED_ITEM"
    STALE_DATED_ITEM = "STALE_DATED_ITEM"
    DUPLICATE_PRESENTMENT = "DUPLICATE_PRESENTMENT"
    REVERSE_REVIEW = "REVERSE_REVIEW"
    ACCOUNT_HOLD_REVIEW = "ACCOUNT_HOLD_REVIEW"


class ExceptionReason(str, Enum):
    NO_ISSUE_RECORD = "NO_ISSUE_RECORD"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    PAYEE_MISMATCH = "PAYEE_MISMATCH"
    VOIDED_ITEM = "VOIDED_ITEM"
    STALE_DATED_ITEM = "STALE_DATED_ITEM"
    DUPLICATE_PRESENTMENT = "DUPLICATE_PRESENTMENT"
    REVERSE_REVIEW = "REVERSE_REVIEW"
    ACCOUNT_HOLD_REVIEW = "ACCOUNT_HOLD_REVIEW"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    DECISIONED_PAY = "DECISIONED_PAY"
    DECISIONED_RETURN = "DECISIONED_RETURN"
    DEFAULTED_PAY = "DEFAULTED_PAY"
    DEFAULTED_RETURN = "DEFAULTED_RETURN"


class AchRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    RETIRED = "RETIRED"


class FeeType(str, Enum):
    EXCEPTION_FEE = "EXCEPTION_FEE"
    RETURN_FEE = "RETURN_FEE"
    ADJUSTMENT = "ADJUSTMENT"
    MINIMUM_TOPUP = "MINIMUM_TOPUP"


class FeeStatus(str, Enum):
    ACCRUED = "ACCRUED"
    BILLED = "BILLED"
    WAIVED = "WAIVED"


class CaseStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_BANK_LIABLE = "RESOLVED_BANK_LIABLE"
    RESOLVED_CUSTOMER_LIABLE = "RESOLVED_CUSTOMER_LIABLE"
    RESOLVED_SHARED = "RESOLVED_SHARED"
    WITHDRAWN = "WITHDRAWN"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ClaimReason(str, Enum):
    FORGED_SIGNATURE = "FORGED_SIGNATURE"
    ALTERED_AMOUNT = "ALTERED_AMOUNT"
    COUNTERFEIT = "COUNTERFEIT"
    UNAUTHORIZED_PAYEE = "UNAUTHORIZED_PAYEE"


class Channel(str, Enum):
    TELLER = "TELLER"
    REMOTE_DEPOSIT = "REMOTE_DEPOSIT"
    CLEARING = "CLEARING"


class TreasuryEnrollment(TypedDict, total=False):
    id: str
    business_name: str
    tier: str
    default_decision: str
    deadline_mode: str
    decision_window_hours: int
    amount_tolerance_cents: int
    payee_score_threshold: int
    stale_days: int
    loss_suspension_threshold_cents: Optional[int]
    status: str
    open_exception_count: int
    provisional_credit_outstanding_cents: int
    ytd_bank_loss_cents: int
    created_at: str
    updated_at: str
    version: int


class EnrollmentUser(TypedDict, total=False):
    id: str
    enrollment_id: str
    display_name: str
    user_role: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    enrollment_id: str
    account_number: str
    payment_review_threshold_cents: Optional[int]
    status: str
    cumulative_paid_cents: int
    cumulative_reversed_cents: int
    net_settled_cents: int
    created_at: str
    updated_at: str
    version: int


class IssueFileUpload(TypedDict, total=False):
    id: str
    enrollment_id: str
    account_id: str
    uploaded_by_user_id: str
    file_reference: str
    payload_hash: str
    row_count: int
    accepted_row_count: int
    rejected_row_count: int
    row_errors: list
    status: str
    created_at: str
    updated_at: str
    version: int


class IssuedCheck(TypedDict, total=False):
    id: str
    account_id: str
    issue_file_id: str
    check_number: str
    amount_cents: int
    payee_name: str
    issue_date: str
    status: str
    consumed_by_item_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PresentedItem(TypedDict, total=False):
    id: str
    account_id: str
    check_number: str
    amount_cents: int
    payee_name_raw: str
    channel: str
    presented_at: str
    idempotency_key: Optional[str]
    status: str
    match_result: str
    match_score: Optional[int]
    exception_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExceptionItem(TypedDict, total=False):
    id: str
    enrollment_id: str
    account_id: str
    presented_item_id: str
    issued_check_id: Optional[str]
    reason: str
    status: str
    default_decision_snapshot: str
    decision_deadline_at: str
    extended_once: bool
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    liability_party: Optional[str]
    fee_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AchDebitRule(TypedDict, total=False):
    id: str
    account_id: str
    rule_type: str
    originator_company_id: str
    sec_code: str
    max_amount_cents: Optional[int]
    effective_start_date: str
    effective_end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeLedgerEntry(TypedDict, total=False):
    id: str
    enrollment_id: str
    exception_id: Optional[str]
    period: str
    fee_type: str
    amount_cents: int
    status: str
    waived_from_status: Optional[str]
    waived_by: Optional[str]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiabilityCase(TypedDict, total=False):
    id: str
    enrollment_id: str
    presented_item_id: str
    filed_by_user_id: str
    claim_reason: str
    claim_amount_cents: int
    status: str
    assigned_bank_user_id: Optional[str]
    provisional_credit_cents: int
    bank_liability_cents: Optional[int]
    customer_liability_cents: Optional[int]
    resolved_by_bank_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict, total=False):
    id: str
    enrollment_id: str
    trainer_id: str
    scheduled_start: str
    scheduled_end: str
    attendee_user_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# OpsRun is an immutable checkpoint receipt (common_fields: false) — it carries
# only id and created_at, never updated_at or version (PRD §2.4).
class OpsRun(TypedDict, total=False):
    id: str
    kind: str
    enrollment_id: Optional[str]
    period: Optional[str]
    status: str
    exceptions_defaulted: int
    checks_staled: int
    ach_rules_expired: int
    sessions_marked_no_show: int
    fees_billed: int
    adjustment_cents: int
    minimum_topup_cents: int
    created_at: str
