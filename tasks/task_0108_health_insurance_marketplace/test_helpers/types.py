"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Resources that participate in update workflows (Application,
  HouseholdMember, Plan, SEPEvent, Enrollment) carry id, created_at,
  updated_at, and version. PRD §2.4: "Resources whose data evolves after
  creation — Application, HouseholdMember, Plan, SEPEvent, Enrollment —
  also carry an updated_at timestamp (same format) and an integer
  version field that begins at 1 and increments by exactly 1 on every
  successful mutation."

- Append-only resources (IncomeRecord, Insurer, PlanVariant,
  PremiumInvoice) carry only id and created_at. PRD §2.4: "Append-only
  resources — IncomeRecord, Insurer, PlanVariant, PremiumInvoice — carry
  only id and created_at; they have no updated_at field and no version
  field, because corrections are made by writing a new row rather than
  mutating an existing one."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    MARKETPLACE_ADMIN = "MarketplaceAdmin"
    INSURER = "Insurer"
    CUSTOMER_SERVICE = "CustomerService"


# ---------------------------------------------------------------------------
# Application — PRD §3.1, §3.3
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ELIGIBILITY_DETERMINED = "ELIGIBILITY_DETERMINED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class EnrollmentWindow(str, Enum):
    OEP = "OEP"
    SEP = "SEP"
    CLOSED = "CLOSED"


class CsrEligibility(str, Enum):
    NONE = "NONE"
    CSR_73 = "CSR_73"
    CSR_87 = "CSR_87"
    CSR_94 = "CSR_94"
    CSR_PLUS = "CSR_PLUS"


# ---------------------------------------------------------------------------
# HouseholdMember — PRD §3.1
# ---------------------------------------------------------------------------
class FilerType(str, Enum):
    PRIMARY_FILER = "PRIMARY_FILER"
    SPOUSE = "SPOUSE"
    DEPENDENT = "DEPENDENT"


# ---------------------------------------------------------------------------
# IncomeRecord — PRD §3.1
# ---------------------------------------------------------------------------
class IncomeSourceType(str, Enum):
    WAGES = "WAGES"
    SELF_EMPLOYMENT = "SELF_EMPLOYMENT"
    SOCIAL_SECURITY = "SOCIAL_SECURITY"
    INTEREST_DIVIDEND = "INTEREST_DIVIDEND"
    RETIREMENT = "RETIREMENT"
    RENTAL = "RENTAL"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# SEPEvent — PRD §3.4
# ---------------------------------------------------------------------------
class SepEventType(str, Enum):
    LOSS_OF_COVERAGE = "LOSS_OF_COVERAGE"
    MARRIAGE = "MARRIAGE"
    BIRTH_ADOPTION = "BIRTH_ADOPTION"
    MOVE = "MOVE"
    INCOME_CHANGE = "INCOME_CHANGE"
    MEDICAID_LOSS = "MEDICAID_LOSS"
    GAINED_CITIZENSHIP = "GAINED_CITIZENSHIP"


class SepEventStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Plan — PRD §3.5
# ---------------------------------------------------------------------------
class PlanTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class CsrLevel(str, Enum):
    STANDARD = "STANDARD"
    CSR_73 = "CSR_73"
    CSR_87 = "CSR_87"
    CSR_94 = "CSR_94"
    CSR_PLUS = "CSR_PLUS"


# ---------------------------------------------------------------------------
# Enrollment — PRD §3.6, §3.7
# ---------------------------------------------------------------------------
class CoverageStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    GRACE_PERIOD = "GRACE_PERIOD"
    TERMINATED = "TERMINATED"


class PaymentStatus(str, Enum):
    AWAITING_BINDER = "AWAITING_BINDER"
    CURRENT = "CURRENT"
    DELINQUENT_M1 = "DELINQUENT_M1"
    DELINQUENT_M2 = "DELINQUENT_M2"
    DELINQUENT_M3 = "DELINQUENT_M3"


class TerminatedReason(str, Enum):
    NON_PAYMENT = "NON_PAYMENT"
    APPLICANT_CANCELLED = "APPLICANT_CANCELLED"
    SEP_REVOKED = "SEP_REVOKED"
    COVERAGE_YEAR_ENDED = "COVERAGE_YEAR_ENDED"


# ---------------------------------------------------------------------------
# PremiumInvoice — PRD §3.7
# ---------------------------------------------------------------------------
class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    VOIDED = "VOIDED"


# ===========================================================================
# Entities carrying common fields (id, created_at, updated_at, version) —
# Application, HouseholdMember, Plan, SEPEvent, Enrollment.
# ===========================================================================
class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    coverage_year: int
    status: str
    filing_state: str
    enrollment_window: str
    household_size: int
    total_magi_cents: Optional[int]
    fpl_percentage: Optional[float]
    csr_eligibility: str
    aptc_estimated_cents: Optional[int]
    aptc_reconciled_cents: Optional[int]
    pinned_fpl_table_version: Optional[int]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HouseholdMember(TypedDict, total=False):
    id: str
    application_id: str
    filer_type: str
    date_of_birth: str
    include_in_household: bool
    include_in_magi: bool
    is_tobacco_user: bool
    medicaid_eligible: Optional[bool]
    member_magi_cents: int
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict, total=False):
    id: str
    insurer_id: str
    coverage_year: int
    filing_state: str
    tier: str
    base_monthly_premium_cents: int
    is_benchmark_silver: bool
    status: str
    catalog_version: int
    created_at: str
    updated_at: str
    version: int


class SEPEvent(TypedDict, total=False):
    id: str
    application_id: str
    event_type: str
    event_date: str
    reported_at: str
    status: str
    window_opens_on: Optional[str]
    window_closes_on: Optional[str]
    effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    application_id: str
    plan_variant_id: str
    pinned_plan_catalog_version: int
    coverage_status: str
    payment_status: str
    coverage_start_date: str
    coverage_end_date: Optional[str]
    monthly_premium_gross_cents: int
    monthly_aptc_applied_cents: int
    monthly_net_premium_cents: int
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only entities — id + created_at ONLY (no updated_at, no version).
# PRD §2.4: "Append-only resources — IncomeRecord, Insurer, PlanVariant,
# PremiumInvoice — carry only id and created_at; they have no updated_at
# field and no version field."
# ===========================================================================
class IncomeRecord(TypedDict, total=False):
    id: str
    member_id: str
    source_type: str
    amount_cents: int
    effective_date: str
    superseded_by_id: Optional[str]
    created_at: str


class Insurer(TypedDict, total=False):
    id: str
    name: str
    filing_states: List[str]
    contact_phone: str
    created_at: str


class PlanVariant(TypedDict, total=False):
    id: str
    plan_id: str
    csr_level: str
    actuarial_value: float
    out_of_pocket_max_cents: int
    created_at: str


class PremiumInvoice(TypedDict, total=False):
    id: str
    enrollment_id: str
    billing_month: str
    gross_amount_cents: int
    aptc_amount_cents: int
    net_amount_cents: int
    due_date: str
    status: str
    paid_at: Optional[str]
    created_at: str


__all__ = [
    "UserRole",
    "ApplicationStatus",
    "EnrollmentWindow",
    "CsrEligibility",
    "FilerType",
    "IncomeSourceType",
    "SepEventType",
    "SepEventStatus",
    "PlanTier",
    "PlanStatus",
    "CsrLevel",
    "CoverageStatus",
    "PaymentStatus",
    "TerminatedReason",
    "InvoiceStatus",
    "Application",
    "HouseholdMember",
    "Plan",
    "SEPEvent",
    "Enrollment",
    "IncomeRecord",
    "Insurer",
    "PlanVariant",
    "PremiumInvoice",
]
