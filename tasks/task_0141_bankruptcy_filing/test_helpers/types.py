"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Debtor, Case, Creditor, Claim, Plan carry id, created_at, updated_at,
  and version (PRD §2.4: "The mutable entities — Debtor, Case, Creditor,
  Claim, and Plan — additionally carry updated_at ... and version").
- Schedule, MeansTestResult, TrusteePayment, CollectionAction are
  append-only / snapshot rows carrying only id and created_at (PRD §2.4:
  "Schedule rows are immutable snapshots ... each Schedule carries only
  id and created_at; updated_at and version are absent.
  MeansTestResult rows ... carry only id and created_at. TrusteePayment
  rows are append-only ledger entries and carry only id and created_at.
  CollectionAction rows ... carry only id and created_at as their
  bookkeeping fields.").
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DEBTOR = "Debtor"
    TRUSTEE = "Trustee"
    CREDITOR = "Creditor"
    JUDGE = "Judge"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    MEETING_SCHEDULED = "MEETING_SCHEDULED"
    MEETING_HELD = "MEETING_HELD"
    PLAN_PROPOSED = "PLAN_PROPOSED"
    PLAN_CONFIRMED = "PLAN_CONFIRMED"
    IN_REPAYMENT = "IN_REPAYMENT"
    DISCHARGED = "DISCHARGED"
    DISMISSED = "DISMISSED"
    WITHDRAWN_PRE_FILE = "WITHDRAWN_PRE_FILE"


class ChapterKind(str, Enum):
    CHAPTER_7 = "CHAPTER_7"
    CHAPTER_13 = "CHAPTER_13"


class CreditorType(str, Enum):
    SECURED = "SECURED"
    PRIORITY = "PRIORITY"
    GENERAL_UNSECURED = "GENERAL_UNSECURED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"
    DISCHARGED = "DISCHARGED"
    NON_DISCHARGEABLE_REMAINS = "NON_DISCHARGEABLE_REMAINS"


class PlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    WITHDRAWN = "WITHDRAWN"


class TrusteePaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    MISSED = "MISSED"


class CollectionActionKind(str, Enum):
    GARNISH = "GARNISH"
    LIEN = "LIEN"
    LAWSUIT = "LAWSUIT"
    DUNNING_LETTER = "DUNNING_LETTER"


class CollectionActionOutcome(str, Enum):
    PROCESSED = "PROCESSED"
    REJECTED_STAY = "REJECTED_STAY"


class ScheduleType(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"
    H = "H"
    I = "I"
    J = "J"


# ---------------------------------------------------------------------------
# Entities carrying id, created_at, updated_at, version — PRD §2.4
# ---------------------------------------------------------------------------
class Debtor(TypedDict, total=False):
    id: str
    full_name: str
    household_size: int
    state_code: str
    total_cases_filed: int
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    debtor_id: str
    chapter_requested: str
    chapter_effective: Optional[str]
    status: str
    automatic_stay_active: bool
    filing_date: Optional[str]
    meeting_341_date: Optional[str]
    schedule_completeness: List[str]
    means_test_result_id: Optional[str]
    total_unsecured_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class Creditor(TypedDict, total=False):
    id: str
    name: str
    creditor_type: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    case_id: str
    creditor_id: str
    claim_class: str
    amount_cents: int
    is_dischargeable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict, total=False):
    id: str
    case_id: str
    proposed_monthly_payment_cents: int
    plan_months: int
    planned_total_cents: int
    paid_to_date_cents: int
    missed_payment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lean entities — id + created_at ONLY (no updated_at, no version)
# PRD §2.4.
# ---------------------------------------------------------------------------
class Schedule(TypedDict, total=False):
    id: str
    case_id: str
    schedule_type: str
    line_items: list
    total_cents: int
    superseded_by_id: Optional[str]
    created_at: str


class MeansTestResult(TypedDict, total=False):
    id: str
    case_id: str
    current_monthly_income_cents: int
    cmi_annualized_cents: int
    state_median_annual_cents: int
    presumption_of_abuse: bool
    allowed_monthly_expenses_cents: int
    disposable_monthly_income_cents: int
    required_plan_months: int
    minimum_plan_total_cents: int
    created_at: str


class TrusteePayment(TypedDict, total=False):
    id: str
    plan_id: str
    sequence_number: int
    amount_cents: int
    status: str
    applied_at: str
    created_at: str


class CollectionAction(TypedDict, total=False):
    id: str
    creditor_id: str
    case_id: str
    action_kind: str
    outcome: str
    rejected_reason: str
    created_at: str


__all__ = [
    "UserRole",
    "CaseStatus",
    "ChapterKind",
    "CreditorType",
    "ClaimStatus",
    "PlanStatus",
    "TrusteePaymentStatus",
    "CollectionActionKind",
    "CollectionActionOutcome",
    "ScheduleType",
    "Debtor",
    "Case",
    "Creditor",
    "Claim",
    "Plan",
    "Schedule",
    "MeansTestResult",
    "TrusteePayment",
    "CollectionAction",
]
