"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the Pension / Defined-Benefit Plan Administration PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---------------------------------------------------------------
class UserRole(str, Enum):
    PLAN_SPONSOR = "PlanSponsor"
    PLAN_ACTUARY = "PlanActuary"
    BENEFITS_ADMINISTRATOR = "BenefitsAdministrator"


# --- Status enums ------------------------------------------------------------
class PensionPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATING = "TERMINATING"


class FundingPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class BenefitFormulaType(str, Enum):
    FINAL_AVERAGE_PAY = "FINAL_AVERAGE_PAY"
    CASH_BALANCE = "CASH_BALANCE"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    RETIRED = "RETIRED"
    DECEASED = "DECEASED"


class VestingStatus(str, Enum):
    UNVESTED = "UNVESTED"
    PARTIALLY_VESTED = "PARTIALLY_VESTED"
    FULLY_VESTED = "FULLY_VESTED"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class PaymentForm(str, Enum):
    SINGLE_LIFE = "SINGLE_LIFE"
    JOINT_AND_SURVIVOR = "JOINT_AND_SURVIVOR"
    LUMP_SUM = "LUMP_SUM"


class ElectionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SPOUSAL_CONSENT_PENDING = "SPOUSAL_CONSENT_PENDING"
    APPROVED = "APPROVED"
    COMMENCED = "COMMENCED"
    REJECTED = "REJECTED"


class AlternatePayeeKind(str, Enum):
    SPOUSE = "SPOUSE"
    FORMER_SPOUSE = "FORMER_SPOUSE"
    CHILD = "CHILD"


class SplitMethod(str, Enum):
    PERCENTAGE = "PERCENTAGE"
    SHARED_INTEREST = "SHARED_INTEREST"


class QdroStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"


class PaymentStatus(str, Enum):
    PENDING_SETUP = "PENDING_SETUP"
    IN_PAY = "IN_PAY"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AdjustmentKind(str, Enum):
    MILITARY_BUYBACK = "MILITARY_BUYBACK"
    BREAK_IN_SERVICE = "BREAK_IN_SERVICE"
    PRIOR_SERVICE_GRANT = "PRIOR_SERVICE_GRANT"


# --- Entity TypedDicts -------------------------------------------------------
# common_fields: true -> id + created_at + updated_at + version
class PensionPlan(TypedDict):
    id: str
    plan_name: str
    ein_psn: str
    benefit_formula_type: str
    normal_retirement_age: int
    cola_pct: float
    fap_accrual_rate: float
    cb_pay_credit_rate: float
    cb_interest_crediting_rate: float
    funding_posture: str
    latest_certified_filing_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    plan_id: str
    ssn_last4: str
    date_of_birth: str
    hire_date: str
    credited_service_years: float
    final_average_pay_cents: int
    cash_balance_account_cents: int
    vesting_status: str
    vested_pct: float
    employment_status: str
    termination_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnnualCompensation(TypedDict):
    id: str
    participant_id: str
    plan_year: int
    gross_comp_cents: int
    capped_comp_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at ONLY (append-only event)
class ServiceCreditAdjustment(TypedDict):
    id: str
    participant_id: str
    adjustment_kind: str
    delta_service_years: float
    applied: bool
    created_at: str


class PlanYearFiling(TypedDict):
    id: str
    plan_id: str
    plan_year: int
    plan_assets_cents: int
    funding_target_cents: int
    aftap_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PbgcPremiumFiling(TypedDict):
    id: str
    plan_id: str
    premium_year: int
    participant_count: int
    unfunded_vested_benefits_cents: int
    flat_rate_premium_cents: int
    variable_rate_premium_cents: int
    total_premium_cents: int
    created_at: str
    updated_at: str
    version: int


class BenefitElection(TypedDict):
    id: str
    participant_id: str
    plan_id: str
    payment_form: str
    js_survivor_pct: Optional[float]
    spouse_date_of_birth: Optional[str]
    annuity_start_date: str
    gross_accrued_monthly_cents: int
    js_reduced_monthly_cents: int
    lump_sum_value_cents: int
    relative_value_pct: float
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QdroAward(TypedDict):
    id: str
    participant_id: str
    plan_id: str
    alternate_payee_kind: str
    split_method: str
    award_pct: Optional[float]
    award_fixed_monthly_cents: Optional[int]
    alternate_payee_monthly_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitPayment(TypedDict):
    id: str
    election_id: str
    participant_id: str
    plan_id: str
    base_monthly_cents: int
    current_monthly_cents: int
    cola_applied_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at ONLY (immutable witnessed record)
class SpousalConsent(TypedDict):
    id: str
    election_id: str
    consenting_spouse_dob: str
    notary_reference: str
    waives_qjsa: bool
    created_at: str
