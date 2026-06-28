"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values match the Supplemental & Voluntary Benefits PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BENEFITS_ADMIN = "BenefitsAdmin"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    EMPLOYEE = "Employee"
    PAYROLL = "Payroll"
    SYSTEM = "System"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class EmployerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PolicyType(str, Enum):
    ACCIDENT = "ACCIDENT"
    CRITICAL_ILLNESS = "CRITICAL_ILLNESS"
    HOSPITAL_INDEMNITY = "HOSPITAL_INDEMNITY"


class PlanProductStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EnrollmentPeriodStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EmploymentStatus(str, Enum):
    EMPLOYED = "EMPLOYED"
    TERMINATED = "TERMINATED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class GiStatus(str, Enum):
    GUARANTEED_ISSUE = "GUARANTEED_ISSUE"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"


class EnrollmentLifecycleStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    PORTED = "PORTED"
    DECLINED = "DECLINED"


class EnrollmentFundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"


class PayrollOutcome(str, Enum):
    POSTED = "POSTED"
    FAILED = "FAILED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class DisbursementStatus(str, Enum):
    INITIATED = "INITIATED"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"


class PortabilityConversionStatus(str, Enum):
    CONVERTED = "CONVERTED"
    CANCELLED = "CANCELLED"


class Section125ElectionStatus(str, Enum):
    LOCKED = "LOCKED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at ONLY (BenefitScheduleItem)
# ---------------------------------------------------------------------------
class Employer(TypedDict):
    id: str
    legal_name: str
    section_125_plan_active: bool
    pay_periods_per_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanProduct(TypedDict):
    id: str
    employer_id: str
    policy_type: str
    product_name: str
    weekly_premium_cents: int
    eoi_surcharge_bps: int
    annual_benefit_cap_cents: int
    portability_loadup_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable append-only line, NO updated_at, NO version
class BenefitScheduleItem(TypedDict):
    id: str
    plan_product_id: str
    event_code: str
    flat_benefit_cents: int
    lifetime_max_occurrences: int
    is_wellness: bool
    created_at: str


class EnrollmentPeriod(TypedDict):
    id: str
    employer_id: str
    label: str
    gi_window_start: str
    gi_window_end: str
    benefit_year_start: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    employer_id: str
    full_name: str
    email: str
    employment_status: str
    total_weekly_deduction_cents: int
    created_at: str
    updated_at: str
    version: int


class DisbursementAccount(TypedDict):
    id: str
    employee_id: str
    routing_number: str
    account_last4: str
    verification_status: str
    is_default: bool
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    employee_id: str
    plan_product_id: str
    enrollment_period_id: str
    pretax: bool
    enrolled_at: str
    gi_status: str
    weekly_premium_cents: int
    weekly_deduction_cents: int
    benefit_paid_cents: int
    benefit_remaining_cents: int
    lifecycle_status: str
    funding_status: str
    created_at: str
    updated_at: str
    version: int


class PayrollDeduction(TypedDict):
    id: str
    enrollment_id: str
    pay_period_index: int
    amount_cents: int
    outcome: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    enrollment_id: str
    disbursement_account_id: str
    event_code: str
    event_date: str
    claimed_cents: int
    approved_cents: int
    paid_cents: int
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    claim_id: str
    disbursement_account_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PortabilityConversion(TypedDict):
    id: str
    enrollment_id: str
    expected_enrollment_version: int
    direct_bill_weekly_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Section125Election(TypedDict):
    id: str
    enrollment_id: str
    plan_year_label: str
    annual_pretax_amount_cents: int
    status: str
    qualifying_event: Optional[str]
    created_at: str
    updated_at: str
    version: int
