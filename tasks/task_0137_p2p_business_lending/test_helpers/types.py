"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 common-fields split:

- Platform, Borrower, LoanListing, Investor, Investment, Loan,
  Installment, Payment, ComplianceOfficer carry id + created_at +
  updated_at + version. (PRD §2.4: "Most resources expose four common
  system fields ... id ... created_at ... updated_at ... version.")

- PlaidSnapshot and Disclosure are append-only by design and carry ONLY
  id + created_at. (PRD §2.4: "A PlaidSnapshot carries only id and
  created_at and has neither updated_at nor version ... A Disclosure
  likewise carries only id and created_at among the common fields ...
  neither updated_at nor version is exposed.")
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_OPERATOR = "PlatformOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BORROWER = "Borrower"
    INVESTOR = "Investor"


# ---------------------------------------------------------------------------
# Borrower — PRD §3.2
# ---------------------------------------------------------------------------
class BorrowerStatus(str, Enum):
    PENDING_KYC = "PENDING_KYC"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    UNGRADED = "UNGRADED"


# ---------------------------------------------------------------------------
# Investor — PRD §3.8
# ---------------------------------------------------------------------------
class InvestorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AccreditationStatus(str, Enum):
    ACCREDITED = "ACCREDITED"
    NON_ACCREDITED = "NON_ACCREDITED"


# ---------------------------------------------------------------------------
# LoanListing — PRD §3.3
# ---------------------------------------------------------------------------
class LoanListingStatus(str, Enum):
    OPEN = "OPEN"
    FUNDED = "FUNDED"
    ORIGINATED = "ORIGINATED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Investment — PRD §3.3, §3.4, §3.6
# ---------------------------------------------------------------------------
class InvestmentStatus(str, Enum):
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    CONVERTED = "CONVERTED"
    LOST = "LOST"


# ---------------------------------------------------------------------------
# Loan — PRD §3.4, §3.6
# ---------------------------------------------------------------------------
class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"
    CHARGED_OFF = "CHARGED_OFF"
    PAID_OFF = "PAID_OFF"


# ---------------------------------------------------------------------------
# Installment — PRD §3.4, §3.6
# ---------------------------------------------------------------------------
class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    PAID = "PAID"
    LATE = "LATE"
    WAIVED = "WAIVED"


# ---------------------------------------------------------------------------
# Payment — PRD §3.5
# ---------------------------------------------------------------------------
class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# Disclosure — PRD §3.7
# ---------------------------------------------------------------------------
class DisclosureKind(str, Enum):
    LISTING_OPENED = "LISTING_OPENED"
    LISTING_FUNDED = "LISTING_FUNDED"
    LOAN_ORIGINATED = "LOAN_ORIGINATED"
    DELINQUENCY_NOTICE = "DELINQUENCY_NOTICE"
    DEFAULT_NOTICE = "DEFAULT_NOTICE"
    CHARGE_OFF_NOTICE = "CHARGE_OFF_NOTICE"
    MATERIAL_AMENDMENT = "MATERIAL_AMENDMENT"


class DisclosureSubjectType(str, Enum):
    BORROWER = "BORROWER"
    LISTING = "LISTING"
    LOAN = "LOAN"
    INVESTMENT = "INVESTMENT"


# ---------------------------------------------------------------------------
# ComplianceOfficer — PRD §3.9
# ---------------------------------------------------------------------------
class ComplianceOfficerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# ===========================================================================
# Top-level resources (common_fields: true) — PRD §2.4
# Carry id + created_at + updated_at + version.
# ===========================================================================
class Platform(TypedDict, total=False):
    id: str
    name: str
    currency: str
    clock_day_index: int
    origination_fee_bps: int
    servicing_fee_bps: int
    late_fee_cents: int
    max_borrower_concentration_bps: int
    created_at: str
    updated_at: str
    version: int


class Borrower(TypedDict, total=False):
    id: str
    platform_id: str
    legal_name: str
    ein: str
    annual_revenue_cents: int
    requested_amount_cents: int
    plaid_snapshot_id: Optional[str]
    provisional_grade: str
    final_grade: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanListing(TypedDict, total=False):
    id: str
    borrower_id: str
    platform_id: str
    principal_cents: int
    term_months: int
    grade_at_listing: str
    interest_rate_bps: int
    pledged_cents: int
    funding_deadline_day_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict, total=False):
    id: str
    platform_id: str
    display_name: str
    accreditation_status: str
    committed_capital_cents: int
    cash_balance_cents: int
    outstanding_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Investment(TypedDict, total=False):
    id: str
    listing_id: str
    investor_id: str
    amount_cents: int
    status: str
    share_bps: int
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    listing_id: str
    borrower_id: str
    platform_id: str
    principal_cents: int
    interest_rate_bps: int
    term_months: int
    monthly_payment_cents: int
    principal_outstanding_cents: int
    accrued_late_fees_cents: int
    charged_off_loss_cents: int
    consecutive_missed_installments: int
    origination_day_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict, total=False):
    id: str
    loan_id: str
    sequence_number: int
    due_day_index: int
    scheduled_principal_cents: int
    scheduled_interest_cents: int
    paid_principal_cents: int
    paid_interest_cents: int
    paid_fees_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    loan_id: str
    borrower_id: str
    amount_cents: int
    received_on_day_index: int
    allocation: Any  # See PaymentAllocation below.
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentAllocation(TypedDict, total=False):
    fees_cents: int
    interest_cents: int
    principal_cents: int
    late_fees_cents: int
    unallocated_cents: int


class ComplianceOfficer(TypedDict, total=False):
    id: str
    platform_id: str
    display_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only resources (common_fields: false) — PRD §2.4
# Carry ONLY id + created_at.
# ===========================================================================
class PlaidSnapshot(TypedDict, total=False):
    id: str
    borrower_id: str
    pulled_on_day_index: int
    deposits_last_90d_cents: int
    avg_daily_balance_cents: int
    nsf_count_last_90d: int
    existing_debt_service_cents: int
    created_at: str
    # NO updated_at, NO version — PRD §2.4.


class Disclosure(TypedDict, total=False):
    id: str
    platform_id: str
    subject_type: str
    subject_id: str
    kind: str
    payload: Any
    published: bool
    published_on_day_index: Optional[int]
    created_at: str
    # NO updated_at, NO version — PRD §2.4.


__all__ = [
    "UserRole",
    "BorrowerStatus",
    "Grade",
    "InvestorStatus",
    "AccreditationStatus",
    "LoanListingStatus",
    "InvestmentStatus",
    "LoanStatus",
    "InstallmentStatus",
    "PaymentStatus",
    "DisclosureKind",
    "DisclosureSubjectType",
    "ComplianceOfficerStatus",
    "Platform",
    "Borrower",
    "LoanListing",
    "Investor",
    "Investment",
    "Loan",
    "Installment",
    "Payment",
    "PaymentAllocation",
    "ComplianceOfficer",
    "PlaidSnapshot",
    "Disclosure",
]
