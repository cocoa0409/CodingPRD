"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.6 — primary resources (Plan, OfferingPeriod, Enrollment,
Purchase, Disposition) carry id + created_at + updated_at + version.
PRD §2.6 also notes that `Contribution` and `Form3922` carry ONLY
id + created_at — both `updated_at` and `version` are absent on those
rows. `SystemClock` is a singleton with no id, updated_at, or version.
The TypedDicts below mirror that exactly.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    PAYROLL_AGENT = "PayrollAgent"
    PARTICIPANT = "Participant"
    TAX_AUTHORITY = "TaxAuthority"


# ===========================================================================
# Status enums — PRD §2.11
# ===========================================================================
class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class OfferingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PURCHASED = "PURCHASED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class ContributionStatus(str, Enum):
    POSTED = "POSTED"
    REFUNDED = "REFUNDED"
    CONSUMED = "CONSUMED"


class HoldingPeriodStatus(str, Enum):
    WITHIN_BOTH = "WITHIN_BOTH"
    PAST_ONE_YEAR_FROM_PURCHASE = "PAST_ONE_YEAR_FROM_PURCHASE"
    QUALIFYING_MATURE = "QUALIFYING_MATURE"


class DispositionPurchaseStatus(str, Enum):
    HELD = "HELD"
    DISPOSED_QUALIFYING = "DISPOSED_QUALIFYING"
    DISPOSED_DISQUALIFYING = "DISPOSED_DISQUALIFYING"


class DispositionStatus(str, Enum):
    REPORTED = "REPORTED"
    AMENDED = "AMENDED"
    VOIDED = "VOIDED"


class DispositionClassification(str, Enum):
    QUALIFYING = "QUALIFYING"
    DISQUALIFYING = "DISQUALIFYING"


# ===========================================================================
# Entity TypedDicts
# ===========================================================================

# Common-fields primary resources — id + created_at + updated_at + version.
class Plan(TypedDict, total=False):
    id: str
    name: str
    status: str
    offering_period_months: int
    max_contribution_rate_bp: int
    annual_accrual_cap_cents: int
    lookback_enabled: bool
    discount_bp: int
    effective_date: str
    created_at: str
    updated_at: str
    version: int


class OfferingPeriod(TypedDict, total=False):
    id: str
    plan_id: str
    sequence_number: int
    start_date: str
    end_date: str
    grant_date_fmv_cents: Optional[int]
    purchase_date_fmv_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    offering_period_id: str
    participant_id: str
    contribution_rate_bp: int
    status: str
    ytd_accrual_cents: int
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict, total=False):
    id: str
    plan_id: str
    offering_period_id: str
    enrollment_id: str
    participant_id: str
    purchase_date: str
    contributions_used_cents: int
    chosen_fmv_cents: int
    purchase_price_cents: int
    shares_purchased: int
    refund_cents: int
    holding_period_status: str
    disposition_status: str
    created_at: str
    updated_at: str
    version: int


class Disposition(TypedDict, total=False):
    id: str
    purchase_id: str
    participant_id: str
    disposition_date: str
    shares_disposed: int
    sale_price_per_share_cents: int
    classification: str
    ordinary_income_cents: int
    capital_gain_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only / leaf entities — id + created_at ONLY (PRD §2.6).
class Contribution(TypedDict, total=False):
    id: str
    enrollment_id: str
    pay_period_end: str
    gross_pay_cents: int
    amount_cents: int
    status: str
    created_at: str


class Form3922(TypedDict, total=False):
    id: str
    purchase_id: str
    participant_id: str
    grant_date: str
    purchase_date: str
    fmv_grant_date_cents: int
    fmv_purchase_date_cents: int
    exercise_price_per_share_cents: int
    shares_transferred: int
    legal_title_date: str
    issuance_timestamp: str
    created_at: str


# SystemClock singleton — no id / updated_at / version (PRD §2.6, §2.9).
class SystemClock(TypedDict, total=False):
    current_time: str
    last_sweep_at: Optional[str]


__all__ = [
    "UserRole",
    "PlanStatus",
    "OfferingPeriodStatus",
    "EnrollmentStatus",
    "ContributionStatus",
    "HoldingPeriodStatus",
    "DispositionPurchaseStatus",
    "DispositionStatus",
    "DispositionClassification",
    "Plan",
    "OfferingPeriod",
    "Enrollment",
    "Purchase",
    "Disposition",
    "Contribution",
    "Form3922",
    "SystemClock",
]
