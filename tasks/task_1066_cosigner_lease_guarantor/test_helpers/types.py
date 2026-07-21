"""Domain types: entity TypedDicts, status enums, and the role enum.

All names mirror the PRD's resource and field vocabulary.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    UNDERWRITER = "Underwriter"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    RECOVERY_AGENT = "RecoveryAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    LANDLORD = "Landlord"
    APPLICANT = "Applicant"


# --- Status / posture enums ---
class PortfolioPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"


class ApplicantStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    DECLINED = "DECLINED"


class LandlordStatus(str, Enum):
    ACTIVE = "ACTIVE"


class GuaranteeStatus(str, Enum):
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXHAUSTED = "EXHAUSTED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class LandlordAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class RecoveryPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class RecoveryInstallmentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ComplianceReviewStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    UPHELD = "UPHELD"


# --- Value enums ---
class EmploymentType(str, Enum):
    SALARIED = "SALARIED"
    SELF_EMPLOYED = "SELF_EMPLOYED"
    RETIRED = "RETIRED"
    UNEMPLOYED = "UNEMPLOYED"


class RiskTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class PayoutVariant(str, Enum):
    CHRONOLOGICAL = "CHRONOLOGICAL"
    ACCELERATED = "ACCELERATED"


class LedgerEntryType(str, Enum):
    FEE_CHARGED = "FEE_CHARGED"
    CLAIM_PAYOUT = "CLAIM_PAYOUT"
    COVERAGE_RESET = "COVERAGE_RESET"


class LedgerDirection(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class ComplianceReason(str, Enum):
    KYC_MISMATCH = "KYC_MISMATCH"
    SANCTIONS_HIT = "SANCTIONS_HIT"
    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"
    AUTO_DEFAULT_TRIGGER = "AUTO_DEFAULT_TRIGGER"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class Portfolio(TypedDict):
    id: str
    name: str
    exposure_cap_cents: int
    total_active_coverage_cents: int
    total_outstanding_recovery_cents: int
    risk_weighted_exposure_cents: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    annual_income_cents: int
    credit_score: int
    monthly_obligations_cents: int
    employment_type: str
    risk_tier: Optional[str]
    debt_to_income: Optional[float]
    default_count: int
    open_recovery_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Landlord(TypedDict):
    id: str
    legal_name: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Guarantee(TypedDict):
    id: str
    portfolio_id: str
    applicant_id: str
    landlord_id: Optional[str]
    unit_id: str
    monthly_rent_cents: int
    coverage_months: int
    term_months: int
    lease_start_date: str
    lease_end_date: str
    per_month_coverage_cents: int
    total_coverage_cents: int
    remaining_coverage_cents: Optional[int]
    paid_out_cents: int
    risk_tier: Optional[str]
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    rent_to_income_ratio: Optional[float]
    fee_paid: bool
    underwritten_by_user_id: Optional[str]
    renewal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LandlordAgreement(TypedDict):
    id: str
    guarantee_id: str
    landlord_id: str
    unit_id: str
    coverage_start_date: str
    coverage_end_date: str
    max_coverage_cents: int
    notice_period_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    guarantee_id: str
    landlord_id: Optional[str]
    default_date: str
    missed_months: int
    acceleration_requested: bool
    payout_variant: Optional[str]
    payout_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryPlan(TypedDict):
    id: str
    claim_id: str
    applicant_id: str
    principal_cents: int
    recovered_cents: int
    outstanding_cents: int
    monthly_installment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryInstallment(TypedDict):
    id: str
    recovery_plan_id: str
    amount_cents: int
    received_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReview(TypedDict):
    id: str
    guarantee_id: str
    reason: str
    opened_by_user_id: str
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only journal record, carries ONLY id + created_at
class LedgerEntry(TypedDict):
    id: str
    guarantee_id: str
    entry_type: str
    amount_cents: int
    direction: str
    balance_after_cents: Optional[int]
    created_at: str
