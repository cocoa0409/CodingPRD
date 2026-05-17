"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4, Plan/Participant/Loan/HardshipWithdrawal/RMDSchedule are
common-fields entities and carry id + created_at + updated_at + version.
ContributionRecord, VestingSnapshot, LoanRepayment, and PlanClock are
ledger-style append-only entities and carry ONLY id + created_at — no
updated_at, no version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    PAYROLL_PROCESSOR = "PayrollProcessor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PARTICIPANT = "Participant"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class ParticipantStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LoanStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    SATISFIED = "SATISFIED"
    DEFAULTED = "DEFAULTED"
    REJECTED = "REJECTED"


class HardshipStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RMDStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FULFILLED = "FULFILLED"
    MISSED = "MISSED"


class ContributionStatus(str, Enum):
    POSTED = "POSTED"


class LoanRepaymentStatus(str, Enum):
    POSTED = "POSTED"


class MatchFormulaType(str, Enum):
    SAFE_HARBOR_BASIC = "SAFE_HARBOR_BASIC"
    TIERED = "TIERED"


class VestingScheduleType(str, Enum):
    CLIFF = "CLIFF"
    GRADED = "GRADED"


class HardshipReasonCode(str, Enum):
    MEDICAL = "MEDICAL"
    EDUCATION = "EDUCATION"
    PRIMARY_RESIDENCE = "PRIMARY_RESIDENCE"
    FUNERAL = "FUNERAL"
    EVICTION = "EVICTION"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
class TieredBracket(TypedDict, total=False):
    employee_deferral_pct_up_to: float
    match_rate_pct: float


# common_fields: true — id + created_at + updated_at + version
class Plan(TypedDict, total=False):
    id: str
    plan_name: str
    plan_year: int
    match_formula_type: str
    tiered_brackets: Optional[List[TieredBracket]]
    vesting_schedule_type: str
    cliff_years: Optional[int]
    graded_percentages: Optional[List[int]]
    rmd_age: int
    current_vesting_epoch: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Participant(TypedDict, total=False):
    id: str
    plan_id: str
    employee_external_id: str
    date_of_birth: str
    hire_date: str
    annual_compensation_cents: int
    elected_deferral_pct: float
    deferral_suspended_until: Optional[str]
    vested_pct_snapshot: float
    vesting_epoch_at_snapshot: int
    cumulative_employee_contribution_cents: int
    cumulative_employer_match_cents: int
    total_account_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger row
class ContributionRecord(TypedDict, total=False):
    id: str
    plan_id: str
    participant_id: str
    pay_period_end: str
    gross_pay_cents: int
    employee_amount_cents: int
    employer_match_cents: int
    status: str
    created_at: str


# common_fields: false — append-only audit row
class VestingSnapshot(TypedDict, total=False):
    id: str
    plan_id: str
    participant_id: str
    vesting_epoch: int
    service_years_completed: int
    vested_pct: float
    vested_balance_cents: int
    created_at: str


# common_fields: true
class Loan(TypedDict, total=False):
    id: str
    plan_id: str
    participant_id: str
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    term_months: int
    monthly_payment_cents: Optional[int]
    outstanding_principal_cents: int
    payments_made: int
    origination_date: Optional[str]
    next_due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger
class LoanRepayment(TypedDict, total=False):
    id: str
    plan_id: str
    participant_id: str
    loan_id: str
    payment_amount_cents: int
    principal_cents: int
    posted_on: str
    status: str
    created_at: str


# common_fields: true
class HardshipWithdrawal(TypedDict, total=False):
    id: str
    plan_id: str
    participant_id: str
    requested_amount_cents: int
    hardship_reason_code: str
    approved_amount_cents: int
    vested_balance_cents_at_request: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class RMDSchedule(TypedDict, total=False):
    id: str
    plan_id: str
    participant_id: str
    rmd_year: int
    prior_year_end_balance_cents: int
    distribution_period_factor: float
    required_amount_cents: int
    due_date: str
    distributed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — singleton, id + created_at only
class PlanClock(TypedDict, total=False):
    id: str
    plan_id: str
    current_date: str
    created_at: str


__all__ = [
    "UserRole",
    "PlanStatus",
    "ParticipantStatus",
    "LoanStatus",
    "HardshipStatus",
    "RMDStatus",
    "ContributionStatus",
    "LoanRepaymentStatus",
    "MatchFormulaType",
    "VestingScheduleType",
    "HardshipReasonCode",
    "TieredBracket",
    "Plan",
    "Participant",
    "ContributionRecord",
    "VestingSnapshot",
    "Loan",
    "LoanRepayment",
    "HardshipWithdrawal",
    "RMDSchedule",
    "PlanClock",
]
