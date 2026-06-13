"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource shapes described in the PRD. Every entity except JournalLine
carries the full id/created_at/updated_at/version quartet; JournalLine is an
immutable detail row carrying only id and created_at (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    OWNER = "Owner"
    ACCOUNTANT = "Accountant"
    BOOKKEEPER = "Bookkeeper"
    AUDITOR = "Auditor"


# --- Status enums ---
class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class AccountingBasis(str, Enum):
    ACCRUAL = "ACCRUAL"
    CASH = "CASH"


class TrialBalanceStatus(str, Enum):
    BALANCED = "BALANCED"
    OUT_OF_BALANCE = "OUT_OF_BALANCE"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class JournalEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class JournalEntrySource(str, Enum):
    MANUAL = "MANUAL"
    BANK_FEED = "BANK_FEED"
    CLOSING = "CLOSING"
    REVERSAL = "REVERSAL"


class BankFeedTransactionStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    CATEGORIZED = "CATEGORIZED"
    EXCLUDED = "EXCLUDED"


class ReconciliationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    RECONCILED = "RECONCILED"
    ABANDONED = "ABANDONED"


class InvoiceDeliveryStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    VOID = "VOID"


class InvoicePaymentStatusAxis(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class InvoicePaymentStatus(str, Enum):
    CLEARED = "CLEARED"
    REVERSED = "REVERSED"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


# --- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ---
class Company(TypedDict, total=False):
    id: str
    legal_name: str
    base_currency: str
    accounting_basis: str
    current_period_id: Optional[str]
    retained_earnings_account_id: Optional[str]
    retained_earnings_cents: int
    trial_balance_status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    company_id: str
    parent_account_id: Optional[str]
    code: str
    name: str
    account_type: str
    is_cash: bool
    status: str
    posted_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class AccountingPeriod(TypedDict, total=False):
    id: str
    company_id: str
    period_label: str
    start_date: str
    end_date: str
    status: str
    close_checklist: list
    closing_journal_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JournalEntry(TypedDict, total=False):
    id: str
    company_id: str
    period_id: str
    entry_date: str
    memo: str
    source: str
    created_by_user_id: str
    reverses_journal_entry_id: Optional[str]
    total_debit_cents: int
    total_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only immutable detail row: ONLY id + created_at
class JournalLine(TypedDict, total=False):
    id: str
    journal_entry_id: str
    account_id: str
    debit_cents: int
    credit_cents: int
    line_memo: str
    created_at: str


class BankAccount(TypedDict, total=False):
    id: str
    company_id: str
    gl_account_id: str
    nickname: str
    last_reconciled_statement_balance_cents: int
    last_reconciled_through: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BankFeedTransaction(TypedDict, total=False):
    id: str
    company_id: str
    bank_account_id: str
    posted_date: str
    amount_cents: int
    bank_description: str
    counter_account_id: Optional[str]
    journal_entry_id: Optional[str]
    cleared: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Reconciliation(TypedDict, total=False):
    id: str
    company_id: str
    bank_account_id: str
    statement_start_date: str
    statement_end_date: str
    statement_opening_balance_cents: int
    statement_ending_balance_cents: int
    included_transaction_ids: list
    difference_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    company_id: str
    display_name: str
    tax_jurisdiction: str
    ar_account_id: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    company_id: str
    customer_id: str
    revenue_account_id: str
    tax_liability_account_id: str
    issue_date: str
    lines: list
    applied_tax_rate_bps: int
    taxable_subtotal_cents: int
    nontaxable_subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    delivery_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class InvoicePayment(TypedDict, total=False):
    id: str
    company_id: str
    invoice_id: str
    deposit_bank_account_id: str
    amount_cents: int
    status: str
    journal_entry_id: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    company_id: str
    display_name: str
    is_1099_eligible: bool
    ap_account_id: str
    ytd_1099_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Bill(TypedDict, total=False):
    id: str
    company_id: str
    vendor_id: str
    expense_account_id: str
    bill_date: str
    lines: list
    applied_tax_rate_bps: int
    subtotal_cents: int
    use_tax_cents: int
    total_cents: int
    amount_paid_cents: int
    paid_in_tax_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxRate(TypedDict, total=False):
    id: str
    company_id: str
    jurisdiction: str
    rate_bps: int
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int
