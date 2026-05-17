"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4, Borrower / LoanApplication / IncomeVerification /
AssetVerification / Appraisal / TitleSearch / RateLock / Disclosure are
common-fields entities (id + created_at + updated_at + version).
RateLockExtension and UDAAPReview are append-only and expose ONLY id +
created_at. SystemClock is a singleton and exposes only `now`.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    LOAN_OFFICER = "LoanOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BORROWER = "Borrower"
    ADMIN = "Admin"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class LoanApplicationStatus(str, Enum):
    INTAKE = "INTAKE"
    PRE_QUALIFIED = "PRE_QUALIFIED"
    UNDERWRITING = "UNDERWRITING"
    CONDITIONAL_APPROVAL = "CONDITIONAL_APPROVAL"
    CLEAR_TO_CLOSE = "CLEAR_TO_CLOSE"
    CLOSED = "CLOSED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class IncomeVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AssetVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AppraisalStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class TitleSearchStatus(str, Enum):
    ORDERED = "ORDERED"
    CLEAR = "CLEAR"
    ISSUES_FOUND = "ISSUES_FOUND"
    RESOLVED = "RESOLVED"


class RateLockStatus(str, Enum):
    LOCKED = "LOCKED"
    EXTENDED = "EXTENDED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"


class DisclosureStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class DisclosureKind(str, Enum):
    LOAN_ESTIMATE = "LOAN_ESTIMATE"
    CLOSING_DISCLOSURE = "CLOSING_DISCLOSURE"


class LoanPurpose(str, Enum):
    PURCHASE = "PURCHASE"
    REFINANCE = "REFINANCE"


class IncomeSourceType(str, Enum):
    W2 = "W2"
    SELF_EMPLOYED = "SELF_EMPLOYED"
    OTHER = "OTHER"


class AssetType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    INVESTMENT = "INVESTMENT"
    GIFT = "GIFT"


class UnderwriteDecision(str, Enum):
    APPROVE = "APPROVE"
    COUNTER_OFFER = "COUNTER_OFFER"
    DENY = "DENY"


class UDAAPOutcome(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    BLOCK = "BLOCK"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common-fields entities carry id + created_at +
# updated_at + version (PRD §2.4).
# ---------------------------------------------------------------------------
class Borrower(TypedDict, total=False):
    id: str
    full_name: str
    ssn_last4: str
    annual_income_cents: int
    credit_score: int
    state_code: str
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict, total=False):
    id: str
    borrower_id: str
    property_address: str
    sale_price_cents: int
    requested_loan_amount_cents: int
    loan_term_months: int
    loan_purpose: str
    status: str
    counter_offered_amount_cents: Optional[int]
    dti_ratio: Optional[float]
    ltv_ratio: Optional[float]
    pmi_required: bool
    assigned_loan_officer_id: str
    compliance_reviewer_id: Optional[str]
    trid_clock_started_at: Optional[str]
    closing_eligible_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeVerification(TypedDict, total=False):
    id: str
    application_id: str
    source_type: str
    documented_annual_cents: int
    status: str
    verifier_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssetVerification(TypedDict, total=False):
    id: str
    application_id: str
    asset_type: str
    balance_cents: int
    status: str
    verifier_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict, total=False):
    id: str
    application_id: str
    appraised_value_cents: Optional[int]
    report_date: str
    valid_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleSearch(TypedDict, total=False):
    id: str
    application_id: str
    status: str
    defects_found: List[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateLock(TypedDict, total=False):
    id: str
    application_id: str
    locked_rate_bps: int
    locked_at: str
    lock_expires_at: str
    lock_fee_cents: int
    extension_fee_paid_cents: int
    refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Disclosure(TypedDict, total=False):
    id: str
    application_id: str
    kind: str
    version: int  # NOTE: domain version per (application_id, kind);
    # the entity also exposes the OCC version field via common_fields
    # — implementations may serialize them differently per PRD §2.4.
    issued_at: str
    apr_bps: int
    total_loan_costs_cents: int
    total_other_costs_cents: int
    cash_to_close_cents: int
    waiting_period_started_at: str
    eligible_to_consummate_at: Optional[str]
    status: str
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str


# common_fields: false — append-only, only id + created_at.
class RateLockExtension(TypedDict, total=False):
    id: str
    rate_lock_id: str
    extra_days: int
    fee_cents: int
    granted_at: str
    created_at: str


# common_fields: false — append-only, only id + created_at.
class UDAAPReview(TypedDict, total=False):
    id: str
    application_id: str
    reviewer_user_id: str
    outcome: str
    notes: Optional[str]
    created_at: str


# Singleton — only `now`.
class SystemClock(TypedDict, total=False):
    now: str


__all__ = [
    "UserRole",
    "LoanApplicationStatus",
    "IncomeVerificationStatus",
    "AssetVerificationStatus",
    "AppraisalStatus",
    "TitleSearchStatus",
    "RateLockStatus",
    "DisclosureStatus",
    "DisclosureKind",
    "LoanPurpose",
    "IncomeSourceType",
    "AssetType",
    "UnderwriteDecision",
    "UDAAPOutcome",
    "Borrower",
    "LoanApplication",
    "IncomeVerification",
    "AssetVerification",
    "Appraisal",
    "TitleSearch",
    "RateLock",
    "Disclosure",
    "RateLockExtension",
    "UDAAPReview",
    "SystemClock",
]
