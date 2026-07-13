"""Domain types: entity TypedDicts, status enums, role enum.

Types mirror the Childcare Subsidy Voucher (CCDF) API resources described in the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — exactly four roles, spelled precisely)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    FAMILY = "Family"
    PROVIDER = "Provider"
    CASE_WORKER = "CaseWorker"
    PROGRAM_ADMIN = "ProgramAdmin"


# ---------------------------------------------------------------------------
# Enums for input/enum fields
# ---------------------------------------------------------------------------
class ActivityType(str, Enum):
    WORK = "WORK"
    EDUCATION = "EDUCATION"
    JOB_SEARCH = "JOB_SEARCH"


class DeterminationType(str, Enum):
    INITIAL = "INITIAL"
    REDETERMINATION = "REDETERMINATION"


class DeterminationResult(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ProviderType(str, Enum):
    CENTER = "CENTER"
    FAMILY_HOME = "FAMILY_HOME"


class CareLevel(str, Enum):
    INFANT = "INFANT"
    TODDLER = "TODDLER"
    PRESCHOOL = "PRESCHOOL"
    SCHOOL_AGE = "SCHOOL_AGE"


# ---------------------------------------------------------------------------
# Status enums (PRD state machines)
# ---------------------------------------------------------------------------
class FamilyStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    CLOSED = "CLOSED"


class DeterminationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class ProviderLicenseStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    LICENSED = "LICENSED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class AttendanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PaymentStatus(str, Enum):
    PAID = "PAID"
    REVERSED = "REVERSED"


class OverpaymentClaimStatus(str, Enum):
    OPEN = "OPEN"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    WAIVED = "WAIVED"


class OverpaymentClaimReason(str, Enum):
    PAYMENT_REVERSAL = "PAYMENT_REVERSAL"
    LICENSE_REVOKED = "LICENSE_REVOKED"
    INELIGIBLE_PERIOD = "INELIGIBLE_PERIOD"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#   Resources carrying the full common-field set: id, created_at, updated_at, version.
#   Lighter reference resources (ParentActivity, IncomeStandard, RateCeiling) carry
#   only id + created_at.
# ---------------------------------------------------------------------------
class Family(TypedDict):
    id: str
    applicant_name: str
    household_size: int
    monthly_gross_income_cents: int
    monthly_self_employment_income_cents: int
    state_code: str
    status: str
    active_authorization_id: Optional[str]
    total_copay_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class ParentActivity(TypedDict):
    id: str
    family_id: str
    activity_type: str
    weekly_hours: int
    created_at: str


class IncomeStandard(TypedDict):
    id: str
    household_size: int
    entry_monthly_limit_cents: int
    exit_monthly_limit_cents: int
    state_code: str
    created_at: str


class EligibilityDetermination(TypedDict):
    id: str
    family_id: str
    determination_type: str
    countable_income_cents: int
    income_eligible: bool
    activity_eligible: bool
    result: Optional[str]
    monthly_copay_cents: int
    effective_date: Optional[str]
    redetermination_due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    name: str
    provider_type: str
    published_daily_rate_cents: int
    license_expiry_date: str
    license_status: str
    state_code: str
    total_net_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class RateCeiling(TypedDict):
    id: str
    provider_type: str
    care_level: str
    max_daily_rate_cents: int
    effective_start: str
    effective_end: str
    state_code: str
    created_at: str


class Authorization(TypedDict):
    id: str
    family_id: str
    provider_id: str
    determination_id: str
    child_name: str
    care_level: str
    start_date: str
    end_date: str
    authorized_days_per_month: int
    authorized_daily_rate_cents: int
    monthly_copay_cents: int
    estimated_monthly_payment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict):
    id: str
    authorization_id: str
    service_month: str
    present_days: int
    absent_days: int
    payable_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    attendance_record_id: str
    provider_id: str
    family_id: str
    service_month: str
    gross_amount_cents: int
    copay_deducted_cents: int
    net_provider_payment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OverpaymentClaim(TypedDict):
    id: str
    provider_id: str
    payment_id: str
    amount_cents: int
    recovered_amount_cents: int
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int
