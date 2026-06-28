"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as the PRD names them. Entities that the PRD
describes as leaner (BillingCode, TrustTransaction) carry only id + created_at —
no updated_at, no version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BILLING_CLERK = "BillingClerk"
    ATTORNEY = "Attorney"


# --- Status enums ---
class ClientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ClientType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    ORGANIZATION = "ORGANIZATION"


class TimekeeperRoleKind(str, Enum):
    PARTNER = "PARTNER"
    ASSOCIATE = "ASSOCIATE"
    PARALEGAL = "PARALEGAL"


class MatterStatus(str, Enum):
    INTAKE = "INTAKE"
    CONFLICT_PENDING = "CONFLICT_PENDING"
    CONFLICT_CLEARED = "CONFLICT_CLEARED"
    CONFLICT_BLOCKED = "CONFLICT_BLOCKED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ConflictResult(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    WAIVED = "WAIVED"


class EntryStatus(str, Enum):
    CAPTURED = "CAPTURED"
    INVOICED = "INVOICED"
    WRITTEN_DOWN = "WRITTEN_DOWN"


class BillingCodeKind(str, Enum):
    TASK = "TASK"
    ACTIVITY = "ACTIVITY"
    EXPENSE = "EXPENSE"


class InvoiceBillingStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"
    VOID = "VOID"


class InvoiceCollectionStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    IN_COLLECTIONS = "IN_COLLECTIONS"
    SETTLED = "SETTLED"


class TrustTransactionKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    DISBURSEMENT = "DISBURSEMENT"
    SWEEP_TO_OPERATING = "SWEEP_TO_OPERATING"


class TrustTransactionStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class RetainerHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"
    CARD = "CARD"


# --- Entity TypedDicts (common_fields: true) ---
class Client(TypedDict):
    id: str
    display_name: str
    client_type: str
    status: str
    ar_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Timekeeper(TypedDict):
    id: str
    full_name: str
    role_kind: str
    standard_rate_cents: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Matter(TypedDict):
    id: str
    client_id: str
    responsible_timekeeper_id: str
    title: str
    matter_rate_cents: Optional[int]
    status: str
    wip_fees_cents: int
    wip_expenses_cents: int
    created_at: str
    updated_at: str
    version: int


class ConflictCheck(TypedDict):
    id: str
    matter_id: str
    adverse_party_client_id: Optional[str]
    adverse_party_name: str
    result: str
    matched_client_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    matter_id: str
    timekeeper_id: str
    worked_at: str
    minutes: int
    utbms_task_code: str
    utbms_activity_code: str
    resolved_rate_cents: int
    billable_amount_cents: int
    status: str
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpenseEntry(TypedDict):
    id: str
    matter_id: str
    utbms_expense_code: str
    amount_cents: int
    status: str
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    matter_id: str
    client_id: str
    issue_date: str
    net_terms_days: int
    fees_subtotal_cents: int
    expenses_subtotal_cents: int
    written_off_cents: int
    total_cents: int
    amount_paid_cents: int
    billing_status: str
    collection_status: str
    created_at: str
    updated_at: str
    version: int


class TrustAccount(TypedDict):
    id: str
    name: str
    book_balance_cents: int
    bank_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ClientTrustLedger(TypedDict):
    id: str
    trust_account_id: str
    client_id: str
    balance_cents: int
    retainer_floor_cents: int
    created_at: str
    updated_at: str
    version: int


class RetainerHold(TypedDict):
    id: str
    client_trust_ledger_id: str
    amount_cents: int
    hold_start_at: str
    hold_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Leaner entities (common_fields: false) — id + created_at ONLY ---
class BillingCode(TypedDict):
    id: str
    code: str
    kind: str
    label: str
    created_at: str


class TrustTransaction(TypedDict):
    id: str
    client_trust_ledger_id: str
    kind: str
    amount_cents: int
    status: str
    invoice_id: Optional[str]
    initiated_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
