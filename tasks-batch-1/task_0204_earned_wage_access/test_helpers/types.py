"""Domain types: entity TypedDicts, status enums, role enum for the Earned Wage Access API."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PAYROLL_OFFICER = "PayrollOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    WORKER = "Worker"


# --- Status enums ---
class EmployerPosture(str, Enum):
    HEALTHY = "HEALTHY"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PayFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    SEMIMONTHLY = "SEMIMONTHLY"


class PolicyTier(str, Enum):
    PROBATION = "PROBATION"
    STANDARD = "STANDARD"
    SENIOR = "SENIOR"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PayPeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    DISBURSED = "DISBURSED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AdvanceEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    ON_HOLD = "ON_HOLD"


class TimeEntryStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class AdvanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    RECOUPING = "RECOUPING"
    SETTLED = "SETTLED"
    DEFAULTED = "DEFAULTED"
    DECLINED = "DECLINED"
    WRITTEN_OFF = "WRITTEN_OFF"


class DisbursementSpeed(str, Enum):
    STANDARD = "STANDARD"
    INSTANT = "INSTANT"


class RepaymentBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class RepaymentAppliedTo(str, Enum):
    FEE = "FEE"
    PRINCIPAL = "PRINCIPAL"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"


class StatementOutcome(str, Enum):
    CLEAN = "CLEAN"
    DISCREPANCY = "DISCREPANCY"


# --- Entity TypedDicts (common_fields: true => id, created_at, updated_at, version) ---


class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    state_code: str
    pay_frequency: str
    funding_balance_cents: int
    max_advance_pct_of_available: float
    per_period_advance_cap_count: int
    cooling_off_hours: int
    posture: str
    outstanding_principal_cents: int
    created_at: str
    updated_at: str
    version: int


class AdvanceLimitPolicy(TypedDict, total=False):
    id: str
    employer_id: str
    tier: str
    min_tenure_days: int
    per_advance_floor_cents: int
    per_advance_ceiling_cents: int
    cumulative_period_ceiling_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict, total=False):
    id: str
    employer_id: str
    expedite_flat_fee_cents: int
    expedite_pct_fee: float
    max_total_fee_cents: int
    tip_allowed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PayPeriod(TypedDict, total=False):
    id: str
    employer_id: str
    period_index: int
    start_at: str
    end_at: str
    gross_accrued_cents: int
    status: str
    locked_at: Optional[str]
    disbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict, total=False):
    id: str
    employer_id: str
    external_payroll_ref: str
    full_name: str
    hourly_rate_cents: int
    hire_date: str
    tenure_days: int
    employment_status: str
    advance_eligibility: str
    period_advance_count: int
    net_available_earnings_cents: int
    lifetime_advanced_cents: int
    created_at: str
    updated_at: str
    version: int


class Advance(TypedDict, total=False):
    id: str
    employer_id: str
    worker_id: str
    pay_period_id: str
    requested_principal_cents: int
    principal_cents: int
    disbursement_speed: str
    tip_cents: int
    expedite_fee_cents: int
    total_fee_cents: int
    disbursed_amount_cents: int
    recoup_target_cents: int
    amount_recouped_cents: int
    principal_outstanding_cents: int
    requested_at: str
    disbursed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepaymentBatch(TypedDict, total=False):
    id: str
    pay_period_id: str
    employer_id: str
    total_recouped_cents: int
    advance_count: int
    posted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconciliationStatement(TypedDict, total=False):
    id: str
    pay_period_id: str
    employer_id: str
    expected_recoup_cents: int
    actual_recouped_cents: int
    written_off_cents: int
    drift_cents: int
    outcome: str
    signed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entities (common_fields: false => only id + created_at) ---


class TimeEntry(TypedDict, total=False):
    id: str
    pay_period_id: str
    worker_id: str
    shift_start_at: str
    shift_end_at: str
    hours_worked: float
    gross_earned_cents: int
    status: str
    created_at: str


class Repayment(TypedDict, total=False):
    id: str
    advance_id: str
    repayment_batch_id: str
    amount_cents: int
    applied_to: str
    created_at: str
