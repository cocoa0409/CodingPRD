"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Entities with the "four common properties" (id, created_at, updated_at,
  version): Donor, Beneficiary, Account, Withdrawal, RecurringPlan,
  BeneficiaryChangeRequest, StateRule.
- Append-only / recompute-in-place entities that carry ONLY id and
  created_at: Contribution, EducationExpense, TaxReport.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DONOR = "Donor"
    BENEFICIARY = "Beneficiary"
    PLAN_ADMINISTRATOR = "PlanAdministrator"


# ---------------------------------------------------------------------------
# Status enums — PRD §3 (state machines)
# ---------------------------------------------------------------------------
class AccountStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class ContributionStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ContributionKind(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    RECURRING = "RECURRING"


class WithdrawalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    REJECTED = "REJECTED"
    DISBURSED = "DISBURSED"
    CLASSIFIED = "CLASSIFIED"
    REPORTED = "REPORTED"


class WithdrawalRejectedReason(str, Enum):
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    ACCOUNT_RESTRICTED = "ACCOUNT_RESTRICTED"
    K12_CAP_WOULD_EXCEED = "K12_CAP_WOULD_EXCEED"
    EXPENSE_RECEIPT_MISSING = "EXPENSE_RECEIPT_MISSING"


class ExpenseCategory(str, Enum):
    POST_SECONDARY_TUITION = "POST_SECONDARY_TUITION"
    ROOM_AND_BOARD = "ROOM_AND_BOARD"
    BOOKS_SUPPLIES = "BOOKS_SUPPLIES"
    K_12 = "K_12"
    NON_QUALIFIED = "NON_QUALIFIED"


class RecurringPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class BeneficiaryChangeRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BeneficiaryChangeRequestRejectionReason(str, Enum):
    RELATIONSHIP_NOT_PERMITTED = "RELATIONSHIP_NOT_PERMITTED"
    GENERATION_SKIP = "GENERATION_SKIP"
    ACCOUNT_NOT_OPEN = "ACCOUNT_NOT_OPEN"
    IDENTICAL_TO_CURRENT = "IDENTICAL_TO_CURRENT"


class RelationshipFamilyCode(str, Enum):
    SELF = "SELF"
    CHILD = "CHILD"
    SIBLING = "SIBLING"
    NIECE_NEPHEW = "NIECE_NEPHEW"
    PARENT = "PARENT"
    COUSIN = "COUSIN"
    SPOUSE = "SPOUSE"
    IN_LAW = "IN_LAW"
    FIRST_COUSIN_ONCE_REMOVED = "FIRST_COUSIN_ONCE_REMOVED"


class CadenceDays(int, Enum):
    WEEKLY = 7
    BIWEEKLY = 14
    MONTHLY = 30
    QUARTERLY = 90
    ANNUAL = 365


class StateRuleParity(str, Enum):
    IN_STATE_ONLY = "IN_STATE_ONLY"
    PARITY = "PARITY"


# ---------------------------------------------------------------------------
# Entities carrying the four common fields (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Donor(TypedDict, total=False):
    id: str
    full_name: str
    state_of_residence: str
    ssn_last_four: str
    ytd_contribution_total_cents: int
    ytd_state_deduction_used_cents: int
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    ssn_last_four: str
    relationship_family_code: str
    k12_ytd_qualified_cents: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    primary_donor_id: str
    beneficiary_id: str
    state_plan_code: str
    status: str
    basis_balance_cents: int
    earnings_balance_cents: int
    total_balance_cents: int
    lifetime_contribution_cap_cents: int
    state_rule_version_at_open: int
    created_at: str
    updated_at: str
    version: int


class Withdrawal(TypedDict, total=False):
    id: str
    account_id: str
    requested_amount_cents: int
    expense_category: str
    status: str
    basis_portion_cents: Optional[int]
    earnings_portion_cents: Optional[int]
    qualified_amount_cents: Optional[int]
    non_qualified_amount_cents: Optional[int]
    penalty_cents: Optional[int]
    rejected_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecurringPlan(TypedDict, total=False):
    id: str
    account_id: str
    donor_id: str
    amount_cents: int
    cadence_days: int
    next_run_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BeneficiaryChangeRequest(TypedDict, total=False):
    id: str
    account_id: str
    current_beneficiary_id: str
    proposed_beneficiary_id: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateRule(TypedDict, total=False):
    id: str
    state_code: str
    deduction_cap_cents: int
    parity: str
    lifetime_aggregate_cap_cents: int
    k12_qualified: bool
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only / recompute-in-place entities — id + created_at ONLY
# (no updated_at, no version per PRD §2.4)
# ---------------------------------------------------------------------------
class Contribution(TypedDict, total=False):
    id: str
    account_id: str
    donor_id: str
    amount_cents: int
    contribution_kind: str
    recurring_plan_id: Optional[str]
    status: str
    settled_at: Optional[str]
    created_at: str


class EducationExpense(TypedDict, total=False):
    id: str
    withdrawal_id: str
    institution_name: str
    category: str
    amount_cents: int
    incurred_on: str
    created_at: str


class TaxReport(TypedDict, total=False):
    id: str
    account_id: str
    tax_year: int
    gross_distribution_cents: int
    earnings_cents: int
    basis_cents: int
    total_penalty_cents: int
    locked: bool
    created_at: str


__all__ = [
    "UserRole",
    "AccountStatus",
    "ContributionStatus",
    "ContributionKind",
    "WithdrawalStatus",
    "WithdrawalRejectedReason",
    "ExpenseCategory",
    "RecurringPlanStatus",
    "BeneficiaryChangeRequestStatus",
    "BeneficiaryChangeRequestRejectionReason",
    "RelationshipFamilyCode",
    "CadenceDays",
    "StateRuleParity",
    "Donor",
    "Beneficiary",
    "Account",
    "Withdrawal",
    "RecurringPlan",
    "BeneficiaryChangeRequest",
    "StateRule",
    "Contribution",
    "EducationExpense",
    "TaxReport",
]
