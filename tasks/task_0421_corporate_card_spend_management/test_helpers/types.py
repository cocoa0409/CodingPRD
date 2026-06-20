"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Entities marked immutable in the PRD
(the Receipt) carry only `id` and `created_at` — no `updated_at`, no `version`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (the X-User-Role header values)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    FINANCE_ADMIN = "FinanceAdmin"
    APPROVER = "Approver"
    CARDHOLDER_EMPLOYEE = "CardholderEmployee"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CompanyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BillingModel(str, Enum):
    CHARGE = "CHARGE"
    CREDIT = "CREDIT"


class SpendPolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class EmployeeRole(str, Enum):
    CARDHOLDER = "CARDHOLDER"
    APPROVER = "APPROVER"
    FINANCE_ADMIN = "FINANCE_ADMIN"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class GlAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CardFormFactor(str, Enum):
    VIRTUAL = "VIRTUAL"
    PHYSICAL = "PHYSICAL"


class CardStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    TERMINATED = "TERMINATED"


class AuthStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ReviewStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    NEEDS_RECEIPT = "NEEDS_RECEIPT"
    MATCHED = "MATCHED"
    APPROVED = "APPROVED"
    FLAGGED = "FLAGGED"


class MatchResult(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"


class ApprovalRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReimbursementClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DUE = "DUE"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"


class RepaymentStatus(str, Enum):
    INITIATED = "INITIATED"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class SpendAuthorizationScope(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    CARD = "CARD"


class SpendAuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"


class ErpSyncBatchStatus(str, Enum):
    BUILT = "BUILT"
    POSTED = "POSTED"
    DISCARDED = "DISCARDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields:true carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Company(TypedDict):
    id: str
    legal_name: str
    currency: str
    credit_limit_cents: int
    billing_model: str
    minimum_payment_pct: float
    reward_rate_default_bps: int
    available_credit_cents: int
    clock_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpendPolicy(TypedDict):
    id: str
    company_id: str
    name: str
    per_transaction_limit_cents: int
    approval_threshold_cents: int
    blocked_mcc_codes: List[str]
    mcc_reward_overrides: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    company_id: str
    email: str
    full_name: str
    employee_role: str
    manager_employee_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GlAccount(TypedDict):
    id: str
    company_id: str
    gl_code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Card(TypedDict):
    id: str
    company_id: str
    employee_id: str
    spend_policy_id: str
    form_factor: str
    card_limit_cents: int
    held_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    card_id: str
    company_id: str
    statement_id: Optional[str]
    merchant_name: str
    mcc_code: str
    amount_cents: int
    settled_amount_cents: Optional[int]
    gl_account_id: Optional[str]
    reward_points_cents: int
    auth_status: str
    review_status: str
    created_at: str
    updated_at: str
    version: int


# Receipt is immutable (common_fields:false) — id + created_at only.
class Receipt(TypedDict):
    id: str
    company_id: str
    transaction_id: str
    amount_cents: int
    merchant_name: str
    match_result: str
    created_at: str


class ApprovalRequest(TypedDict):
    id: str
    transaction_id: str
    company_id: str
    requester_employee_id: str
    approver_employee_id: Optional[str]
    decision_note: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict):
    id: str
    company_id: str
    employee_id: str
    gl_account_id: str
    merchant_name: str
    amount_cents: int
    receipt_amount_cents: int
    reimbursable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict):
    id: str
    company_id: str
    cycle_index: int
    opened_at: Optional[str]
    closed_at: Optional[str]
    due_at: Optional[str]
    closing_balance_cents: int
    minimum_due_cents: int
    amount_repaid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Repayment(TypedDict):
    id: str
    statement_id: str
    company_id: str
    amount_cents: int
    expected_statement_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RewardAccount(TypedDict):
    id: str
    company_id: str
    accrued_points_cents: int
    redeemed_points_cents: int
    balance_points_cents: int
    created_at: str
    updated_at: str
    version: int


class SpendAuthorization(TypedDict):
    id: str
    company_id: str
    scope: str
    employee_id: str
    card_id: Optional[str]
    budget_cents: int
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ErpSyncBatch(TypedDict):
    id: str
    company_id: str
    statement_id: str
    entry_count: int
    total_debits_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
