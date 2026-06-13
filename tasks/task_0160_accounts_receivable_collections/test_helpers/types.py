"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD's Accounts Receivable & Collections contract exactly.
Durable resources carry id/created_at/updated_at/version; the two lighter records
(DunningNotice, CashForecast) carry only id/created_at.
"""
from enum import Enum
from typing import TypedDict, List


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    AR_MANAGER = "AR_MANAGER"
    AR_CLERK = "AR_CLERK"
    COLLECTIONS_AGENT = "COLLECTIONS_AGENT"
    AUDITOR = "AUDITOR"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class CreditStatus(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    HOLD = "HOLD"


class CollectionStage(str, Enum):
    CURRENT = "CURRENT"
    DUNNING = "DUNNING"
    COLLECTIONS = "COLLECTIONS"
    WRITEOFF = "WRITEOFF"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    B1_30 = "B1_30"
    B31_60 = "B31_60"
    B61_90 = "B61_90"
    B91_PLUS = "B91_PLUS"


class PaymentStatus(str, Enum):
    UNAPPLIED = "UNAPPLIED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    FULLY_APPLIED = "FULLY_APPLIED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_CREDIT = "RESOLVED_CREDIT"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DisputeReasonCode(str, Enum):
    PRICING = "PRICING"
    SHORTAGE = "SHORTAGE"
    DAMAGE = "DAMAGE"
    DUPLICATE = "DUPLICATE"
    QUALITY = "QUALITY"


class PromiseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    KEPT = "KEPT"
    BROKEN = "BROKEN"
    CANCELLED = "CANCELLED"


class WriteOffReasonCode(str, Enum):
    UNCOLLECTIBLE = "UNCOLLECTIBLE"
    SETTLEMENT = "SETTLEMENT"
    BANKRUPTCY = "BANKRUPTCY"
    SMALL_BALANCE = "SMALL_BALANCE"


class DunningPauseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class ForecastMethod(str, Enum):
    EXPECTED = "EXPECTED"
    CONSERVATIVE = "CONSERVATIVE"


# --------------------------------------------------------------------------- #
# Durable entities — id + created_at + updated_at + version
# --------------------------------------------------------------------------- #
class Customer(TypedDict):
    id: str
    name: str
    currency: str
    credit_limit_cents: int
    credit_status: str
    collection_stage: str
    exposure_cents: int
    total_open_balance_cents: int
    bad_debt_total_cents: int
    manual_hold: bool
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    customer_id: str
    invoice_date: str
    due_date: str
    face_amount_cents: int
    balance_cents: int
    disputed_amount_cents: int
    status: str
    aging_bucket: str
    dunning_stage_index: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    customer_id: str
    amount_cents: int
    received_at: str
    applied_cents: int
    unapplied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentApplication(TypedDict):
    id: str
    payment_id: str
    invoice_id: str
    applied_cents: int
    short_pay_cents: int
    reversed: bool
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    reason_code: str
    status: str
    resolution_credit_cents: int
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class PromiseToPay(TypedDict):
    id: str
    customer_id: str
    promised_amount_cents: int
    coverage_start: str
    coverage_end: str
    status: str
    applied_payment_cents: int
    created_at: str
    updated_at: str
    version: int


class WriteOff(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    reason_code: str
    approved: bool
    created_at: str
    updated_at: str
    version: int


class DunningSequence(TypedDict):
    id: str
    name: str
    active: bool
    steps: List[dict]
    created_at: str
    updated_at: str
    version: int


class DunningPause(TypedDict):
    id: str
    customer_id: str
    pause_start: str
    pause_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict):
    id: str
    customer_id: str
    period_end: str
    opening_balance_cents: int
    new_charges_cents: int
    finance_charge_cents: int
    closing_balance_cents: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Lighter records — id + created_at ONLY (no updated_at, no version)
# --------------------------------------------------------------------------- #
class DunningNotice(TypedDict):
    id: str
    invoice_id: str
    sequence_id: str
    step_index: int
    severity: int
    priority_score: float
    created_at: str


class CashForecast(TypedDict):
    id: str
    customer_id: str
    horizon_days: int
    method: str
    projected_cents: float
    created_at: str
