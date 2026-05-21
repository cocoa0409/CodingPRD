"""Domain types: entity TypedDicts, status enums, role enum.

Two entities are append-only ledger lines per PRD §2.4:
"`TransferLink` (linking the `first_trip_id` and `second_trip_id` of a
paired transfer with an immutable `window_minutes`) and `FSAContribution`
(which records `account_id`, `amount_cents`, `contribution_month`, and
`status`, and which is reversed by appending a new contribution rather
than by mutating the original)."
Their TypedDicts therefore omit `updated_at` and `version`.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    RIDER = "Rider"
    AGENCY_OFFICER = "AgencyOfficer"
    EMPLOYER_ADMIN = "EmployerAdmin"
    AUDITOR = "Auditor"


# ===========================================================================
# Status enums — PRD §3
# ===========================================================================
class EmployerEnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FareCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DiscountClass(str, Enum):
    STANDARD = "STANDARD"
    REDUCED_FARE = "REDUCED_FARE"
    LOW_INCOME = "LOW_INCOME"


class ReducedFareProgramType(str, Enum):
    SENIOR = "SENIOR"
    DISABILITY = "DISABILITY"
    STUDENT = "STUDENT"


class ReducedFareCertificateStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class LowIncomeVerificationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class MobileWalletProvider(str, Enum):
    APPLE_PAY = "APPLE_PAY"
    GOOGLE_PAY = "GOOGLE_PAY"
    SAMSUNG_PAY = "SAMSUNG_PAY"


class MobilePaymentTokenStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class TripFareStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class TripTravelStatus(str, Enum):
    TAPPED_IN = "TAPPED_IN"
    COMPLETED = "COMPLETED"
    INCOMPLETE_FORCED = "INCOMPLETE_FORCED"


class FareCapScope(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"


class CommuterBenefitAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class FSAContributionStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class DisputeCaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED_REFUNDED = "RESOLVED_REFUNDED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"


class DisputeDecision(str, Enum):
    REFUND = "REFUND"
    REJECT = "REJECT"


# ===========================================================================
# Entity TypedDicts — common-fields entities carry id, created_at,
# updated_at, version. Append-only entities (TransferLink, FSAContribution)
# carry only id + created_at.
# ===========================================================================
class Rider(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    low_income_verified: bool
    employer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    enrollment_status: str
    monthly_contribution_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class FareCard(TypedDict, total=False):
    id: str
    rider_id: str
    discount_class: str
    status: str
    valid_from: str
    valid_until: str
    wallet_balance_cents: int
    mobile_token_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReducedFareCertificate(TypedDict, total=False):
    id: str
    rider_id: str
    program_type: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LowIncomeVerification(TypedDict, total=False):
    id: str
    rider_id: str
    declared_annual_income_cents: int
    verified_annual_income_cents: Optional[int]
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MobilePaymentToken(TypedDict, total=False):
    id: str
    rider_id: str
    wallet_provider: str
    device_fingerprint: str
    status: str
    bound_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict, total=False):
    id: str
    card_id: str
    idempotency_key: str
    tap_in_at: str
    tap_out_at: Optional[str]
    fare_status: str
    travel_status: str
    provisional_fare_cents: int
    settled_fare_cents: Optional[int]
    transfer_link_id: Optional[str]
    cap_period_id: str
    paid_from_fsa_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only — carries only id + created_at + entity-specific fields
class TransferLink(TypedDict, total=False):
    id: str
    first_trip_id: str
    second_trip_id: str
    window_minutes: int
    created_at: str


class FareCapPeriod(TypedDict, total=False):
    id: str
    card_id: str
    scope: str
    window_start: str
    window_end: str
    accumulated_cents: int
    cap_cents: int
    cap_reached_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommuterBenefitAccount(TypedDict, total=False):
    id: str
    rider_id: str
    employer_id: str
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only — carries only id + created_at + entity-specific fields
class FSAContribution(TypedDict, total=False):
    id: str
    account_id: str
    amount_cents: int
    contribution_month: str
    status: str
    created_at: str


class DisputeCase(TypedDict, total=False):
    id: str
    trip_id: str
    rider_id: str
    status: str
    refund_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


__all__ = [
    # Roles
    "UserRole",
    # Status enums
    "EmployerEnrollmentStatus",
    "FareCardStatus",
    "DiscountClass",
    "ReducedFareProgramType",
    "ReducedFareCertificateStatus",
    "LowIncomeVerificationStatus",
    "MobileWalletProvider",
    "MobilePaymentTokenStatus",
    "TripFareStatus",
    "TripTravelStatus",
    "FareCapScope",
    "CommuterBenefitAccountStatus",
    "FSAContributionStatus",
    "DisputeCaseStatus",
    "DisputeDecision",
    # Entities
    "Rider",
    "Employer",
    "FareCard",
    "ReducedFareCertificate",
    "LowIncomeVerification",
    "MobilePaymentToken",
    "Trip",
    "TransferLink",
    "FareCapPeriod",
    "CommuterBenefitAccount",
    "FSAContribution",
    "DisputeCase",
]
