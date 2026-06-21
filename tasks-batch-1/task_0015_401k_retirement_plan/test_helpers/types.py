"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums (PRD §3) ──────────────────────────────────────────────────

class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    TERMINATED = "TERMINATED"


class ParticipantEnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ContributionPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REVERSED = "REVERSED"


class LoanStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISBURSED = "DISBURSED"
    REPAID = "REPAID"
    DEFAULTED = "DEFAULTED"


class HardshipWithdrawalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class RMDDistributionStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    MISSED = "MISSED"


class MatchFormula(str, Enum):
    TIERED = "TIERED"
    SAFE_HARBOR_ENHANCED = "SAFE_HARBOR_ENHANCED"


class VestingSchedule(str, Enum):
    CLIFF_3 = "CLIFF_3"
    GRADED_6 = "GRADED_6"


class HardshipCategory(str, Enum):
    MEDICAL_EXPENSES = "MEDICAL_EXPENSES"
    PRIMARY_RESIDENCE_PURCHASE = "PRIMARY_RESIDENCE_PURCHASE"
    TUITION_PAYMENT = "TUITION_PAYMENT"
    EVICTION_PREVENTION = "EVICTION_PREVENTION"
    FUNERAL_EXPENSES = "FUNERAL_EXPENSES"


class RMDVariant(str, Enum):
    UNIFORM_LIFETIME = "UNIFORM_LIFETIME"
    JOINT_LIFE = "JOINT_LIFE"


class UserRole(str, Enum):
    PLAN_ADMIN = "PlanAdmin"
    PARTICIPANT = "Participant"
    CUSTODIAN = "Custodian"


# ─── Entity TypedDicts (PRD §3) ─────────────────────────────────────────────

class Plan(TypedDict):
    id: str
    name: str
    plan_year: int
    match_formula: str
    vesting_schedule: str
    annual_compensation_limit_cents: int
    annual_deferral_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    plan_id: str
    full_name: str
    date_of_birth: str
    hire_date: str
    annual_compensation_cents: int
    deferral_rate_bps: int
    enrollment_status: str
    employee_balance_cents: int
    employer_balance_cents: int
    years_of_service: int
    vested_employer_balance_cents: int
    outstanding_loan_principal_cents: int
    created_at: str
    updated_at: str
    version: int


class ContributionPeriod(TypedDict):
    id: str
    participant_id: str
    period_end_date: str
    gross_compensation_cents: int
    employee_contribution_cents: int
    employer_match_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    participant_id: str
    principal_cents: int
    term_months: int
    annual_interest_rate_bps: int
    monthly_payment_cents: int
    outstanding_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HardshipWithdrawal(TypedDict):
    id: str
    participant_id: str
    requested_amount_cents: int
    hardship_category: str
    approved_amount_cents: int
    ten_percent_penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RMDDistribution(TypedDict):
    id: str
    participant_id: str
    distribution_year: int
    prior_year_end_balance_cents: int
    rmd_variant: str
    spouse_date_of_birth: Optional[str]
    required_amount_cents: int
    distributed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# VestingEvent is immutable / append-only (PRD §2.4, §3.7): id + created_at only.
class VestingEvent(TypedDict):
    id: str
    participant_id: str
    as_of_date: str
    years_of_service_after: int
    vested_pct_bps_after: int
    created_at: str
