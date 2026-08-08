"""Domain types: entity TypedDicts, status enums, role enum.

Furnished Midterm Housing API. All entities carry the common quartet
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    HOST = "Host"
    TENANT = "Tenant"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---- Enums -----------------------------------------------------------------

class HostPayoutAccountStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class TenantType(str, Enum):
    TRAVEL_NURSE = "TRAVEL_NURSE"
    RELOCATION = "RELOCATION"
    OTHER = "OTHER"


class TenantVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VerificationDocType(str, Enum):
    GOVERNMENT_ID = "GOVERNMENT_ID"
    EMPLOYMENT_LETTER = "EMPLOYMENT_LETTER"
    ASSIGNMENT_CONTRACT = "ASSIGNMENT_CONTRACT"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class UnitStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"


class RentBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ExtensionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class DepositStatus(str, Enum):
    HELD = "HELD"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    FORFEITED = "FORFEITED"


class DamageClaimStatus(str, Enum):
    FILED = "FILED"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class CoiPolicyStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class TurnoverStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    REVERSED = "REVERSED"
    VOIDED = "VOIDED"


class PayoutBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TaxExemptReason(str, Enum):
    MID_TERM_30_DAY = "MID_TERM_30_DAY"
    NONE = "NONE"


# ---- Entity TypedDicts (all common_fields: true) ---------------------------

class Host(TypedDict):
    id: str
    display_name: str
    email: str
    payout_account_status: str
    status: str
    projected_payout_cents: int
    payout_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    full_name: str
    email: str
    tenant_type: str
    verification_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Verification(TypedDict):
    id: str
    tenant_id: str
    doc_type: str
    document_ref: str
    status: str
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    host_id: str
    title: str
    address: str
    monthly_rate_cents: int
    cleaning_fee_cents: int
    deposit_cents: int
    utilities_included: bool
    cleaning_included: bool
    requires_coi: bool
    min_term_days: int
    max_term_days: int
    turnover_buffer_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    unit_id: str
    tenant_id: str
    start_date: str
    end_date: str
    term_days: int
    rent_cents: int
    cleaning_charge_cents: int
    gross_rent_cents: int
    rent_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Extension(TypedDict):
    id: str
    booking_id: str
    expected_booking_version: int
    new_end_date: str
    added_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    booking_id: str
    amount_cents: int
    held_cents: int
    refunded_cents: int
    forfeited_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    deposit_id: str
    expected_deposit_version: int
    claimed_cents: int
    approved_cents: int
    description: str
    tenant_response: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoiPolicy(TypedDict):
    id: str
    booking_id: str
    coverage_cents: int
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Turnover(TypedDict):
    id: str
    unit_id: str
    booking_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    booking_id: str
    host_id: str
    gross_rent_cents: int
    platform_fee_cents: int
    deposit_adjustment_cents: int
    net_cents: int
    payout_basis: str
    scheduled_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxAssessment(TypedDict):
    id: str
    booking_id: str
    assessed_term_days: int
    taxable: bool
    occupancy_tax_cents: int
    exempt_reason: str
    created_at: str
    updated_at: str
    version: int
