"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 — common-fields vs append-only entities:

    Every resource that carries the standard envelope of common fields
    exposes four server-managed properties: id, created_at, updated_at,
    and version. WageRecord, WorkSearchEntry, and BenefitPayment are
    append-only and carry only id + created_at (no updated_at, no
    version). SystemClock is a single-row singleton carrying only its
    'now' field.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CLAIMANT = "Claimant"
    ADJUDICATOR = "Adjudicator"
    APPEAL_OFFICER = "AppealOfficer"
    EMPLOYER_AGENT = "EmployerAgent"
    SYSTEM_ADMIN = "SystemAdmin"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ADJUDICATION = "PENDING_ADJUDICATION"
    MONETARILY_ELIGIBLE = "MONETARILY_ELIGIBLE"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXTENDED = "EXTENDED"
    CLOSED = "CLOSED"


class BasePeriodVariant(str, Enum):
    STANDARD = "STANDARD"
    ALTERNATE = "ALTERNATE"


class WeeklyCertificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    OVERPAID = "OVERPAID"


class ContactMethod(str, Enum):
    ONLINE_APPLICATION = "ONLINE_APPLICATION"
    IN_PERSON = "IN_PERSON"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    REFERRAL = "REFERRAL"


class BenefitPaymentStatus(str, Enum):
    ISSUED = "ISSUED"
    REVERSED = "REVERSED"


class OverpaymentClassification(str, Enum):
    AGENCY_ERROR = "AGENCY_ERROR"
    NON_FRAUD = "NON_FRAUD"
    FRAUD = "FRAUD"


class OverpaymentStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    REPAID = "REPAID"
    WAIVED = "WAIVED"
    WRITTEN_OFF = "WRITTEN_OFF"


class AppealSubjectType(str, Enum):
    MONETARY_DETERMINATION = "MONETARY_DETERMINATION"
    WEEKLY_DENIAL = "WEEKLY_DENIAL"
    OVERPAYMENT_ASSESSMENT = "OVERPAYMENT_ASSESSMENT"


class AppealStatus(str, Enum):
    FILED = "FILED"
    IN_HEARING = "IN_HEARING"
    SUSTAINED = "SUSTAINED"
    REVERSED = "REVERSED"
    WITHDRAWN = "WITHDRAWN"
    DISMISSED_LATE = "DISMISSED_LATE"


class EmployerChargeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"
    RELIEVED = "RELIEVED"


class PandemicExtensionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Common-fields entities — PRD §2.4: id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class Claimant(TypedDict, total=False):
    id: str
    ssn_last4: str
    full_name: str
    state_residence: str
    date_of_birth: str
    lifetime_overpayment_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict, total=False):
    id: str
    ein: str
    legal_name: str
    reserve_ratio_basis_cents: int
    taxable_payroll_cents: int
    experience_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    claimant_id: str
    filing_date: str
    benefit_year_start: str
    benefit_year_end: str
    base_period_variant: str
    base_period_total_wages_cents: int
    high_quarter_wages_cents: int
    weekly_benefit_amount_cents: int
    max_weeks_of_eligibility: int
    status: str
    weeks_paid: int
    weeks_remaining: int
    pandemic_extension_weeks_granted: int
    extension_id: Optional[str]
    assigned_adjudicator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WeeklyCertification(TypedDict, total=False):
    id: str
    claim_id: str
    week_ending_date: str
    status: str
    earnings_reported_cents: int
    able_and_available: bool
    work_search_count: int
    payable_amount_cents: int
    payment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Overpayment(TypedDict, total=False):
    id: str
    claim_id: str
    certification_id: Optional[str]
    principal_cents: int
    balance_cents: int
    classification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    claim_id: str
    subject_type: str
    subject_id: str
    subject_locked_version: int
    assigned_adjudicator_id: str
    assigned_appeal_officer_id: str
    filed_at: str
    deadline_at: str
    status: str
    decision_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmployerCharge(TypedDict, total=False):
    id: str
    employer_id: str
    claim_id: str
    payment_id: str
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PandemicExtension(TypedDict, total=False):
    id: str
    program_name: str
    effective_start: str
    effective_end: str
    extra_weeks: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — PRD §2.4: id + created_at only (no updated_at,
# no version).
# ---------------------------------------------------------------------------
class WageRecord(TypedDict, total=False):
    id: str
    claimant_id: str
    employer_id: str
    quarter_year: int
    quarter_index: int
    wages_cents: int
    created_at: str


class WorkSearchEntry(TypedDict, total=False):
    id: str
    certification_id: str
    contact_date: str
    employer_name: str
    contact_method: str
    created_at: str


class BenefitPayment(TypedDict, total=False):
    id: str
    claim_id: str
    certification_id: str
    amount_cents: int
    issued_at: str
    status: str
    reversed_reason: Optional[str]
    created_at: str


# ---------------------------------------------------------------------------
# Singleton — PRD §2.9
# ---------------------------------------------------------------------------
class SystemClock(TypedDict, total=False):
    now: str


__all__ = [
    "UserRole",
    "ClaimStatus",
    "BasePeriodVariant",
    "WeeklyCertificationStatus",
    "ContactMethod",
    "BenefitPaymentStatus",
    "OverpaymentClassification",
    "OverpaymentStatus",
    "AppealSubjectType",
    "AppealStatus",
    "EmployerChargeStatus",
    "PandemicExtensionStatus",
    "Claimant",
    "Employer",
    "Claim",
    "WeeklyCertification",
    "Overpayment",
    "Appeal",
    "EmployerCharge",
    "PandemicExtension",
    "WageRecord",
    "WorkSearchEntry",
    "BenefitPayment",
    "SystemClock",
]
