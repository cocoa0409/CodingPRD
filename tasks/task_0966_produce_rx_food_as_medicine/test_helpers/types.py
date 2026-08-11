"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    FUNDER_ANALYST = "FunderAnalyst"
    CLINIC_STAFF = "ClinicStaff"
    PARTICIPANT = "Participant"
    RETAILER_STAFF = "RetailerStaff"
    EDUCATOR = "Educator"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class FunderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FundingPoolStatus(str, Enum):
    PENDING = "PENDING"
    FUNDED = "FUNDED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ClinicStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RetailerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RetailerKind(str, Enum):
    GROCERY = "GROCERY"
    FARMERS_MARKET = "FARMERS_MARKET"
    MOBILE_MARKET = "MOBILE_MARKET"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ReferralPriority(str, Enum):
    STANDARD = "STANDARD"
    URGENT = "URGENT"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"


class EngagementTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class BenefitCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class RedemptionStatus(str, Enum):
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class RedemptionLineCategory(str, Enum):
    PRODUCE_ELIGIBLE = "PRODUCE_ELIGIBLE"
    STAPLE = "STAPLE"
    OTHER = "OTHER"


class EducationSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BiometricKind(str, Enum):
    A1C = "A1C"
    WEIGHT_KG = "WEIGHT_KG"
    SYSTOLIC_BP = "SYSTOLIC_BP"


class BiometricSource(str, Enum):
    CLINIC = "CLINIC"
    LAB_VERIFIED = "LAB_VERIFIED"
    SELF_REPORT = "SELF_REPORT"


class ReportBasis(str, Enum):
    ACCRUAL = "ACCRUAL"
    CASH = "CASH"


class FunderReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class RenewalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


# --- Entity TypedDicts ---
# Common fields (PRD §2.4): every resource carries id + created_at; most also
# carry updated_at + version. EducationCompletion and BiometricReading are
# append-only and carry ONLY id + created_at alongside their domain fields.


class Program(TypedDict, total=False):
    id: str
    name: str
    start_date: str
    end_date: str
    base_monthly_benefit_cents: int
    household_increment_cents: int
    max_household_size: int
    double_up_multiplier: float
    double_up_daily_cap_cents: int
    double_up_pool_cents: int
    double_up_matched_cents: int
    double_up_remaining_cents: int
    tier2_completions: int
    tier3_completions: int
    renewal_window_days: int
    outcome_improvement_threshold: float
    status: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Funder(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    total_commitment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingPool(TypedDict, total=False):
    id: str
    program_id: str
    funder_id: str
    committed_cents: int
    disbursed_cents: int
    reserved_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Clinic(TypedDict, total=False):
    id: str
    name: str
    npi_number: str
    max_active_referrals: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Retailer(TypedDict, total=False):
    id: str
    name: str
    kind: str
    double_up_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    clinic_id: str
    full_name: str
    date_of_birth: str
    household_size: int
    consent_status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    clinic_id: str
    patient_id: str
    program_id: str
    diagnosis_code: str
    priority: str
    decision_reason: Optional[str]
    appeal_reason: Optional[str]
    appeal_count: int
    enrollment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    program_id: str
    patient_id: str
    referral_id: str
    household_size: int
    engagement_tier: str
    lifetime_redeemed_cents: int
    lifetime_match_cents: int
    lapsed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitCycle(TypedDict, total=False):
    id: str
    program_id: str
    period_index: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict, total=False):
    id: str
    enrollment_id: str
    benefit_cycle_id: str
    face_value_cents: int
    redeemed_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RedemptionLine(TypedDict):
    category: str
    amount_cents: int


class Redemption(TypedDict, total=False):
    id: str
    retailer_id: str
    enrollment_id: str
    lines: List[RedemptionLine]
    subtotal_cents: int
    produce_eligible_cents: int
    match_cents: int
    voucher_applied_cents: int
    voucher_id: Optional[str]
    patient_pay_cents: int
    redeemed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EducationSession(TypedDict, total=False):
    id: str
    program_id: str
    topic: str
    venue: str
    starts_at: str
    ends_at: str
    capacity: int
    educator_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): NO updated_at, NO version.
class EducationCompletion(TypedDict, total=False):
    id: str
    enrollment_id: str
    session_id: str
    minutes_attended: int
    passed: bool
    created_at: str


# Append-only (PRD §2.4): NO updated_at, NO version.
class BiometricReading(TypedDict, total=False):
    id: str
    enrollment_id: str
    kind: str
    value: float
    measured_at: str
    source: str
    created_at: str


class FunderReport(TypedDict, total=False):
    id: str
    program_id: str
    funding_pool_id: str
    period_start: str
    period_end: str
    basis: str
    utilization_cents: int
    total_redeemed_cents: int
    total_match_cents: int
    active_enrollments: int
    a1c_improved_count: int
    revision_count: int
    return_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Renewal(TypedDict, total=False):
    id: str
    enrollment_id: str
    reason: str
    resubmit_count: int
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
