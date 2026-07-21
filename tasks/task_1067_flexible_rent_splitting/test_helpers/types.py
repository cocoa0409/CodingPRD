"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    UNDERWRITER = "Underwriter"
    COLLECTIONS_AGENT = "CollectionsAgent"
    COLLECTIONS_MANAGER = "CollectionsManager"
    RENTER = "Renter"
    PROPERTY_MANAGER = "PropertyManager"


class PropertyStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RenterStatus(str, Enum):
    PROSPECT = "PROSPECT"
    UNDERWRITING = "UNDERWRITING"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class BillingCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REMITTED = "REMITTED"
    SETTLED = "SETTLED"
    DELINQUENT = "DELINQUENT"
    WRITTEN_OFF = "WRITTEN_OFF"
    CANCELLED = "CANCELLED"


class CycleMode(str, Enum):
    SPLIT = "SPLIT"
    DEFER = "DEFER"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    FAILED = "FAILED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class InstallmentKind(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    SPLIT = "SPLIT"
    DEFERRED = "DEFERRED"


class RemittanceStatus(str, Enum):
    SENT = "SENT"
    REVERSED = "REVERSED"


class AutopayMandateStatus(str, Enum):
    PAUSED = "PAUSED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class DelinquencyCaseStatus(str, Enum):
    OPEN = "OPEN"
    IN_OUTREACH = "IN_OUTREACH"
    PROMISE_TO_PAY = "PROMISE_TO_PAY"
    BROKEN_PROMISE = "BROKEN_PROMISE"
    RESOLVED = "RESOLVED"
    CHARGED_OFF = "CHARGED_OFF"


class RecoveryActionType(str, Enum):
    OUTREACH = "OUTREACH"
    PROMISE_SET = "PROMISE_SET"
    RETRY_CHARGE = "RETRY_CHARGE"
    NOTE = "NOTE"


class ReminderKind(str, Enum):
    OVERDUE = "OVERDUE"
    PROMISE_CONFIRMATION = "PROMISE_CONFIRMATION"
    CHARGE_OFF_NOTICE = "CHARGE_OFF_NOTICE"


class LedgerEntryType(str, Enum):
    REMITTANCE_ADVANCE = "REMITTANCE_ADVANCE"
    REPAYMENT = "REPAYMENT"
    FEE = "FEE"
    FEE_REFUND = "FEE_REFUND"
    LATE_FEE = "LATE_FEE"
    WRITE_OFF = "WRITE_OFF"
    REVERSAL = "REVERSAL"


# ---- Entities carrying full common fields (id/created_at/updated_at/version) ----

class Property(TypedDict):
    id: str
    landlord_name: str
    unit_label: str
    full_rent_cents: int
    rent_due_day: int
    remittance_account_ref: str
    integration_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Renter(TypedDict):
    id: str
    property_id: str
    email: str
    full_name: str
    portion_rent_cents: int
    status: str
    risk_band: Optional[str]
    approved_limit_cents: int
    autopay_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    renter_id: str
    reported_monthly_income_cents: int
    requested_split_count: int
    prior_delinquency_count: int
    status: str
    risk_score: int
    risk_band: str
    approved_limit_cents: int
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    renter_id: str
    property_id: str
    cycle_month: str
    cycle_start_date: str
    mode: str
    split_count: int
    deferred_amount_cents: int
    planned_defer_days: int
    full_rent_cents: int
    portion_cents: int
    fee_provisional_cents: int
    fee_final_cents: Optional[int]
    repaid_amount_cents: int
    net_remitted_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    cycle_id: str
    sequence_no: int
    due_date: str
    amount_cents: int
    kind: str
    attempt_count: int
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict):
    id: str
    cycle_id: str
    property_id: str
    amount_cents: int
    sent_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AutopayMandate(TypedDict):
    id: str
    renter_id: str
    method_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DelinquencyCase(TypedDict):
    id: str
    cycle_id: str
    renter_id: str
    recovery_round: int
    accrued_late_fee_cents: int
    principal_outstanding_cents: int
    reinstatement_amount_cents: int
    settlement_amount_cents: int
    promise_date: Optional[str]
    opened_at: str
    last_recovery_agent_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---- Append-only entities: ONLY id + created_at (no updated_at, no version) ----

class RecoveryAction(TypedDict):
    id: str
    case_id: str
    action_type: str
    agent_id: str
    promise_date: Optional[str]
    note: Optional[str]
    created_at: str


class Reminder(TypedDict):
    id: str
    renter_id: str
    cycle_id: str
    kind: str
    channel: str
    sent_at: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    cycle_id: str
    entry_type: str
    amount_cents: int
    memo: str
    created_at: str
