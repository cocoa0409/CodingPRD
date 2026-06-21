"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the LTC Insurance Administration PRD.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    CARE_ASSESSOR = "CareAssessor"
    REGULATOR = "Regulator"
    POLICYHOLDER = "Policyholder"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CoverageStatus(str, Enum):
    APPLIED = "APPLIED"
    IN_FORCE = "IN_FORCE"
    CLAIM_OPEN = "CLAIM_OPEN"
    EXHAUSTED = "EXHAUSTED"
    RESCINDED = "RESCINDED"


class PremiumStatus(str, Enum):
    PENDING = "PENDING"
    PAID_CURRENT = "PAID_CURRENT"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    NONFORFEITURE_PAID_UP = "NONFORFEITURE_PAID_UP"
    WAIVED = "WAIVED"


class ProductMode(str, Enum):
    REIMBURSEMENT = "REIMBURSEMENT"
    INDEMNITY = "INDEMNITY"


class InflationRider(str, Enum):
    NONE = "NONE"
    COMPOUND_3PCT = "COMPOUND_3PCT"
    COMPOUND_5PCT = "COMPOUND_5PCT"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    WAIVED = "WAIVED"
    DEFAULTED = "DEFAULTED"


class RateFilingStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class TriggerDecision(str, Enum):
    CERTIFIED = "CERTIFIED"
    NOT_CERTIFIED = "NOT_CERTIFIED"


class ProviderType(str, Enum):
    NURSING_HOME = "NURSING_HOME"
    ASSISTED_LIVING = "ASSISTED_LIVING"
    HOME_HEALTH_AGENCY = "HOME_HEALTH_AGENCY"
    ADULT_DAY_CARE = "ADULT_DAY_CARE"
    INFORMAL_CAREGIVER = "INFORMAL_CAREGIVER"


class ProviderEligibility(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    SUSPENDED = "SUSPENDED"


class CareSetting(str, Enum):
    NURSING_HOME = "NURSING_HOME"
    ASSISTED_LIVING = "ASSISTED_LIVING"
    HOME_HEALTH = "HOME_HEALTH"
    ADULT_DAY = "ADULT_DAY"
    INFORMAL = "INFORMAL"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDING_REASSESSMENT = "PENDING_REASSESSMENT"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    VOID = "VOID"


class LedgerSourceKind(str, Enum):
    CLAIM_PAYMENT = "CLAIM_PAYMENT"
    NONFORFEITURE_REDUCTION = "NONFORFEITURE_REDUCTION"
    INFLATION_GROWTH = "INFLATION_GROWTH"


class DisregardStatus(str, Enum):
    ACCRUING = "ACCRUING"
    FROZEN = "FROZEN"


ADL_ACTIVITIES = ["BATHING", "DRESSING", "TOILETING", "TRANSFERRING", "CONTINENCE", "EATING"]


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true -> id, created_at, updated_at, version
class Policyholder(TypedDict):
    id: str
    full_name: str
    state_code: str
    date_of_birth: str
    medicaid_state_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    policyholder_id: str
    product_mode: str
    daily_benefit_max_cents: int
    monthly_benefit_max_cents: int
    initial_pool_cents: int
    inflation_rider: str
    elimination_period_days: int
    is_partnership_policy: bool
    inflation_years_elapsed: int
    inflated_daily_max_cents: int
    inflated_monthly_max_cents: int
    coverage_status: str
    premium_status: str
    benefits_triggered: bool
    elimination_days_satisfied: int
    created_at: str
    updated_at: str
    version: int


class BenefitPool(TypedDict):
    id: str
    policy_id: str
    inflated_pool_cents: int
    lifetime_paid_cents: int
    nonforfeiture_reduction_cents: int
    remaining_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class PremiumInvoice(TypedDict):
    id: str
    policy_id: str
    period_index: int
    amount_cents: int
    due_date: str
    grace_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RateIncreaseFiling(TypedDict):
    id: str
    policy_id: str
    requested_increase_pct: int
    approved_increase_pct: int
    effective_period_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    name: str
    provider_type: str
    state_code: str
    license_active: bool
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    policy_id: str
    provider_id: str
    care_setting: str
    authored_by_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    care_plan_id: str
    service_month: str
    month_paid_cents: int
    requires_reassessment: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict):
    id: str
    claim_id: str
    service_date: str
    billed_charge_cents: int
    is_qualifying_day: bool
    elimination_applied: bool
    benefit_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class PartnershipDisregard(TypedDict):
    id: str
    policy_id: str
    protected_asset_cents: int
    disregard_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only: id + created_at ONLY (no updated_at, no version)
class BenefitTriggerCertification(TypedDict):
    id: str
    policy_id: str
    adl_deficiencies: List[str]
    cognitive_impairment: bool
    decision: str
    assessed_by_id: str
    supersedes_id: Optional[str]
    created_at: str


class BenefitLedgerEntry(TypedDict):
    id: str
    policy_id: str
    claim_id: Optional[str]
    source_kind: str
    amount_cents: int
    created_at: str
