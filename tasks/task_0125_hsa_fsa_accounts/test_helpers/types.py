"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 common-fields split:

- Top-level mutable resources — Account, AccountHolder, PlanYear,
  Dependent, Claim — carry id, created_at, updated_at, version.
- Append-only immutable entities — Contribution, QualifiedExpense,
  AuditEvent, OpsRun — carry ONLY id and created_at. They have no
  updated_at and no version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ACCOUNT_HOLDER = "AccountHolder"
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    CLAIM_ADJUDICATOR = "ClaimAdjudicator"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Account — PRD §3.1
# ---------------------------------------------------------------------------
class AccountType(str, Enum):
    HSA = "HSA"
    HEALTH_FSA = "HEALTH_FSA"
    DEPENDENT_CARE_FSA = "DEPENDENT_CARE_FSA"


class CoverageTier(str, Enum):
    SELF_ONLY = "SELF_ONLY"
    FAMILY = "FAMILY"


class YearEndPolicy(str, Enum):
    NONE = "NONE"
    GRACE_PERIOD = "GRACE_PERIOD"
    CARRYOVER = "CARRYOVER"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# AccountHolder — PRD §3.1
# ---------------------------------------------------------------------------
class TaxFilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    MARRIED_SEPARATE = "MARRIED_SEPARATE"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


# ---------------------------------------------------------------------------
# Dependent — PRD §3.1
# ---------------------------------------------------------------------------
class DependentRelationship(str, Enum):
    CHILD = "CHILD"
    SPOUSE = "SPOUSE"
    QUALIFYING_RELATIVE = "QUALIFYING_RELATIVE"


class DependentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# ---------------------------------------------------------------------------
# PlanYear — PRD §3.2
# ---------------------------------------------------------------------------
class PlanYearStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE_PERIOD = "GRACE_PERIOD"
    CARRYOVER_PENDING = "CARRYOVER_PENDING"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Contribution — PRD §3.3
# ---------------------------------------------------------------------------
class ContributionSource(str, Enum):
    PAYROLL = "PAYROLL"
    DIRECT = "DIRECT"
    EMPLOYER_MATCH = "EMPLOYER_MATCH"


class ContributionStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# QualifiedExpense — PRD §3.4
# ---------------------------------------------------------------------------
class QualifiedExpenseCategory(str, Enum):
    MEDICAL = "MEDICAL"
    VISION = "VISION"
    DENTAL = "DENTAL"
    OTC_MEDICATION = "OTC_MEDICATION"
    DEPENDENT_CARE = "DEPENDENT_CARE"
    NON_QUALIFIED = "NON_QUALIFIED"


# ---------------------------------------------------------------------------
# Claim — PRD §3.5
# ---------------------------------------------------------------------------
class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# OpsRun — PRD §3.7
# ---------------------------------------------------------------------------
class OpsRunKind(str, Enum):
    YEAR_END_CLOSE = "YEAR_END_CLOSE"
    GRACE_PERIOD_EXPIRY = "GRACE_PERIOD_EXPIRY"


# ---------------------------------------------------------------------------
# AuditEvent — PRD §2.8
# ---------------------------------------------------------------------------
class AuditEventType(str, Enum):
    ACCOUNT_OPENED = "ACCOUNT_OPENED"
    ACCOUNT_FROZEN = "ACCOUNT_FROZEN"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"
    CONTRIBUTION_POSTED = "CONTRIBUTION_POSTED"
    CONTRIBUTION_REVERSED = "CONTRIBUTION_REVERSED"
    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
    CLAIM_APPROVED = "CLAIM_APPROVED"
    CLAIM_PAID = "CLAIM_PAID"
    CLAIM_DENIED = "CLAIM_DENIED"
    CLAIM_REVERSED = "CLAIM_REVERSED"
    PLAN_YEAR_OPENED = "PLAN_YEAR_OPENED"
    GRACE_PERIOD_STARTED = "GRACE_PERIOD_STARTED"
    CARRYOVER_APPLIED = "CARRYOVER_APPLIED"
    YEAR_END_FORFEITURE = "YEAR_END_FORFEITURE"
    OPS_RUN_EXECUTED = "OPS_RUN_EXECUTED"


class AuditSubjectEntity(str, Enum):
    ACCOUNT = "ACCOUNT"
    CONTRIBUTION = "CONTRIBUTION"
    CLAIM = "CLAIM"
    PLAN_YEAR = "PLAN_YEAR"


# ===========================================================================
# Top-level mutable resources (common_fields: true) — PRD §2.4
# Carry id + created_at + updated_at + version.
# ===========================================================================
class Account(TypedDict, total=False):
    id: str
    account_holder_id: str
    account_type: str
    coverage_tier: Optional[str]
    account_holder_birth_date: str
    year_end_policy: str
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountHolder(TypedDict, total=False):
    id: str
    full_name: str
    ssn_last4: str
    tax_filing_status: str
    birth_date: str
    created_at: str
    updated_at: str
    version: int


class PlanYear(TypedDict, total=False):
    id: str
    account_id: str
    calendar_year: int
    status: str
    contribution_cap_cents: int
    catch_up_cap_cents: int
    contributions_ytd_cents: int
    claims_paid_ytd_cents: int
    provisional_balance_cents: int
    carryover_in_cents: int
    carryover_consumed_cents: int
    forfeited_cents: int
    grace_period_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dependent(TypedDict, total=False):
    id: str
    account_holder_id: str
    full_name: str
    birth_date: str
    relationship: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    account_id: str
    plan_year_id: Optional[str]
    service_date: str
    expense_code: str
    amount_cents: int
    dependent_id: Optional[str]
    status: str
    denial_reason: Optional[str]
    paid_amount_cents: Optional[int]
    reversed_from_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only immutable entities (common_fields: false) — PRD §2.4
# Carry ONLY id + created_at. No updated_at, no version.
# ===========================================================================
class Contribution(TypedDict, total=False):
    id: str
    plan_year_id: str
    amount_cents: int
    source: str
    posted_at: str
    status: str
    reversal_of_id: Optional[str]
    created_at: str


class QualifiedExpense(TypedDict, total=False):
    id: str
    code: str
    category: str
    eligible_account_types: List[str]
    requires_dependent: bool
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    account_id: str
    plan_year_id: Optional[str]
    event_type: str
    subject_entity: str
    subject_id: str
    actor_role: str
    actor_user_id: str
    cents_delta: int
    ops_run_index: Optional[int]
    occurred_at: str
    created_at: str


class OpsRun(TypedDict, total=False):
    id: str
    index: int
    as_of_date: str
    kind: str
    plan_years_affected: List[str]
    total_forfeited_cents: int
    created_at: str


# ---------------------------------------------------------------------------
# Read projections — PRD §3.8
# ---------------------------------------------------------------------------
class TaxForm(TypedDict, total=False):
    deductible_cents: int
    recapture_cents: int
    tax_basis_cents: int
    basis: str


class ClockState(TypedDict, total=False):
    now: str


__all__ = [
    "UserRole",
    "AccountType",
    "CoverageTier",
    "YearEndPolicy",
    "AccountStatus",
    "TaxFilingStatus",
    "DependentRelationship",
    "DependentStatus",
    "PlanYearStatus",
    "ContributionSource",
    "ContributionStatus",
    "QualifiedExpenseCategory",
    "ClaimStatus",
    "OpsRunKind",
    "AuditEventType",
    "AuditSubjectEntity",
    "Account",
    "AccountHolder",
    "PlanYear",
    "Dependent",
    "Claim",
    "Contribution",
    "QualifiedExpense",
    "AuditEvent",
    "OpsRun",
    "TaxForm",
    "ClockState",
]
