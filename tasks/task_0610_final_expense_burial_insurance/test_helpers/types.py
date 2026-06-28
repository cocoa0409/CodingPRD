"""Domain types: entity TypedDicts, status enums, role enum.

Models the Final Expense & Burial Insurance API resources described in the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles                                                                        #
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    POLICY_ADMIN = "PolicyAdmin"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    POLICYHOLDER = "Policyholder"


# --------------------------------------------------------------------------- #
# Status / enum value sets                                                     #
# --------------------------------------------------------------------------- #
class BenefitType(str, Enum):
    GUARANTEED_ISSUE = "GUARANTEED_ISSUE"
    GRADED_BENEFIT = "GRADED_BENEFIT"
    LEVEL_BENEFIT = "LEVEL_BENEFIT"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REFERRED = "REFERRED"
    DECLINED = "DECLINED"
    ISSUED = "ISSUED"
    WITHDRAWN = "WITHDRAWN"


class RatingClass(str, Enum):
    STANDARD = "STANDARD"
    TOBACCO = "TOBACCO"
    SUBSTANDARD = "SUBSTANDARD"
    DECLINE = "DECLINE"


class DeclineReason(str, Enum):
    AGE_OUT_OF_BAND = "AGE_OUT_OF_BAND"
    KNOCKOUT_CONDITION = "KNOCKOUT_CONDITION"
    FACE_OUT_OF_RANGE = "FACE_OUT_OF_RANGE"


class CoverageStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"
    SURRENDERED = "SURRENDERED"
    RESCINDED = "RESCINDED"


class PaymentStatus(str, Enum):
    CURRENT = "CURRENT"
    GRACE = "GRACE"
    DELINQUENT = "DELINQUENT"


class BeneficiaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class FuneralHomeAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class PremiumPaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PolicyLoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    CALLED = "CALLED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONTESTING = "CONTESTING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PayoutBasis(str, Enum):
    FULL_FACE = "FULL_FACE"
    GRADED_REFUND = "GRADED_REFUND"


class DenialReason(str, Enum):
    MISREPRESENTATION = "MISREPRESENTATION"
    POLICY_NOT_IN_FORCE = "POLICY_NOT_IN_FORCE"
    EXCLUDED_CAUSE = "EXCLUDED_CAUSE"


class Relationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    SIBLING = "SIBLING"
    PARENT = "PARENT"
    ESTATE = "ESTATE"
    OTHER = "OTHER"


class Gender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class CertifiedCause(str, Enum):
    ILLNESS = "ILLNESS"
    ACCIDENT = "ACCIDENT"
    HOMICIDE = "HOMICIDE"
    SUICIDE = "SUICIDE"
    UNDETERMINED = "UNDETERMINED"


class MannerOfDeath(str, Enum):
    NATURAL = "NATURAL"
    ACCIDENTAL = "ACCIDENTAL"


class LedgerEntryType(str, Enum):
    PREMIUM_POSTED = "PREMIUM_POSTED"
    PREMIUM_REVERSED = "PREMIUM_REVERSED"
    LOAN_DISBURSED = "LOAN_DISBURSED"
    LOAN_REPAID = "LOAN_REPAID"
    CASH_VALUE_ACCRUED = "CASH_VALUE_ACCRUED"
    BENEFIT_PAID = "BENEFIT_PAID"
    LOAN_OFFSET = "LOAN_OFFSET"


# --------------------------------------------------------------------------- #
# Entity TypedDicts                                                            #
# --------------------------------------------------------------------------- #

# common_fields: true -> id + created_at + updated_at + version
class ProductPlan(TypedDict, total=False):
    id: str
    name: str
    benefit_type: str
    min_issue_age: int
    max_issue_age: int
    graded_period_months: int
    contestability_period_months: int
    graded_refund_apr: float
    base_monthly_rate_per_1000_cents: int
    face_tiers: List[dict]
    age_bands: List[dict]
    cash_value_factor_per_1000_cents: int
    cash_value_vesting_years: int
    max_loan_to_cash_value_pct: float
    loan_apr: float
    loan_cooldown_days: int
    surrender_charge_tiers: List[dict]
    grace_period_days: int
    reinstatement_window_days: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    gender: str
    tobacco_use: bool
    state_code: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    product_plan_id: str
    requested_face_amount_cents: int
    rating_class: Optional[str]
    attained_age: Optional[int]
    quoted_monthly_premium_cents: int
    decline_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only (no updated_at, no version)
class HealthQuestionnaire(TypedDict, total=False):
    id: str
    application_id: str
    terminal_illness: bool
    aids_hiv: bool
    nursing_home_confined: bool
    major_condition_last_2y: bool
    knockout_triggered: bool
    created_at: str


class Policy(TypedDict, total=False):
    id: str
    application_id: str
    product_plan_id: str
    applicant_id: str
    policyholder_user_id: str
    face_amount_cents: int
    monthly_premium_cents: int
    benefit_type: str
    issue_date: str
    paid_through_date: str
    due_date: str
    coverage_status: str
    payment_status: str
    total_premiums_paid_cents: int
    gross_cash_value_cents: int
    outstanding_loan_balance_cents: int
    net_cash_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict, total=False):
    id: str
    policy_id: str
    full_name: str
    relationship: str
    share_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FuneralHomeAssignment(TypedDict, total=False):
    id: str
    policy_id: str
    funeral_home_name: str
    assigned_benefit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PremiumPayment(TypedDict, total=False):
    id: str
    policy_id: str
    amount_cents: int
    coverage_start: str
    coverage_end: str
    posted_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PolicyLoan(TypedDict, total=False):
    id: str
    policy_id: str
    expected_policy_version: int
    principal_cents: int
    disbursed_date: str
    settled_date: Optional[str]
    accrued_interest_cents: int
    repaid_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    date_of_death: str
    manner_of_death: str
    gross_benefit_cents: int
    loan_offset_cents: int
    net_payout_cents: int
    payout_basis: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only
class DeathCertificate(TypedDict, total=False):
    id: str
    claim_id: str
    certificate_number: str
    certified_cause: str
    verified: bool
    created_at: str


# common_fields: false -> id + created_at only
class LedgerEntry(TypedDict, total=False):
    id: str
    policy_id: str
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    occurred_at: str
    created_at: str
