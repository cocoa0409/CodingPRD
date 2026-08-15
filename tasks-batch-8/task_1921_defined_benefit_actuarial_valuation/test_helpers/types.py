"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class PlanPosture(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    LUMP_SUM_RESTRICTED = "LUMP_SUM_RESTRICTED"
    ACCRUAL_FROZEN = "ACCRUAL_FROZEN"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ASSOCIATE = "ASSOCIATE"


class CensusBatchStatus(str, Enum):
    UPLOADED = "UPLOADED"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"
    VALIDATED = "VALIDATED"
    LOCKED = "LOCKED"


class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED_VESTED = "TERMINATED_VESTED"
    RETIREE = "RETIREE"


class AssumptionSetStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    RETIRED = "RETIRED"


class CorridorApplied(str, Enum):
    NONE = "NONE"
    FLOOR = "FLOOR"
    CEILING = "CEILING"


class ValuationRunStatus(str, Enum):
    INITIATED = "INITIATED"
    COMPUTED = "COMPUTED"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class CreditBalanceElectionStatus(str, Enum):
    EFFECTIVE = "EFFECTIVE"
    REVOKED = "REVOKED"


class ContributionDemandStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_SATISFIED = "PARTIALLY_SATISFIED"
    SATISFIED = "SATISFIED"
    DELINQUENT = "DELINQUENT"


class PBGCFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    AMENDED = "AMENDED"
    VOID = "VOID"


class DisclosureReportStatus(str, Enum):
    DRAFT = "DRAFT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class PremiumMethod(str, Enum):
    STANDARD = "STANDARD"
    ALTERNATIVE = "ALTERNATIVE"


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    PLAN_ADMIN = "PlanAdmin"
    ACTUARY = "Actuary"
    SENIOR_ACTUARY = "SeniorActuary"
    AUDITOR = "Auditor"


# --- Entity TypedDicts (common_fields: true -> id + created_at + updated_at + version) ---

class Plan(TypedDict, total=False):
    id: str
    sponsor_name: str
    plan_year: int
    accrual_rate: float
    normal_retirement_age: int
    prior_aftap_pct: float
    initial_carryover_balance: float
    initial_prefunding_balance: float
    status: str
    current_posture: str
    certified_aftap_pct: Optional[float]
    presumed_aftap_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Actuary(TypedDict, total=False):
    id: str
    full_name: str
    credential_id: str
    enrollment_status: str
    created_at: str
    updated_at: str
    version: int


class CensusBatch(TypedDict, total=False):
    id: str
    plan_id: str
    plan_year: int
    source_label: str
    status: str
    participant_count: int
    error_count: int
    screening_errors: List[Any]
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    census_batch_id: str
    external_ref: str
    date_of_birth: str
    status: str
    years_of_service: Optional[int]
    annual_compensation: Optional[float]
    deferred_benefit_annual: Optional[float]
    current_annual_benefit: Optional[float]
    created_at: str
    updated_at: str
    version: int


class AssumptionSet(TypedDict, total=False):
    id: str
    plan_id: str
    plan_year: int
    label: str
    mortality_table: str
    funding_discount_rate: float
    disclosure_discount_rate: float
    retirement_age: int
    prepared_by_actuary_id: str
    approved_by_actuary_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AssetStatement(TypedDict, total=False):
    id: str
    plan_id: str
    plan_year: int
    market_value_begin: float
    contributions_received: float
    benefits_paid: float
    investment_return: float
    market_value_end: float
    created_at: str
    updated_at: str
    version: int


class AssetValuation(TypedDict, total=False):
    id: str
    plan_id: str
    plan_year: int
    market_value: float
    smoothed_value: float
    unrecognized_gain: float
    corridor_floor: float
    corridor_ceiling: float
    corridor_applied: str
    created_at: str
    updated_at: str
    version: int


class ValuationRun(TypedDict, total=False):
    id: str
    plan_id: str
    plan_year: int
    census_batch_id: str
    assumption_set_id: str
    asset_valuation_id: str
    status: str
    funding_target: float
    normal_cost: float
    aftap_pct: Optional[float]
    created_by_actuary_id: str
    certified_by_actuary_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParticipantAccrual(TypedDict, total=False):
    id: str
    valuation_run_id: str
    participant_id: str
    age_at_valuation: int
    annuity_factor: float
    accrued_liability: float
    normal_cost_share: float
    frozen: bool
    created_at: str
    updated_at: str
    version: int


class CreditBalanceLedger(TypedDict, total=False):
    id: str
    plan_id: str
    carryover_balance: float
    prefunding_balance: float
    total_applied_to_date: float
    created_at: str
    updated_at: str
    version: int


class CreditBalanceElection(TypedDict, total=False):
    id: str
    plan_id: str
    contribution_demand_id: str
    amount: float
    status: str
    revoke_deadline: str
    created_at: str
    updated_at: str
    version: int


class ContributionDemand(TypedDict, total=False):
    id: str
    plan_id: str
    plan_year: int
    valuation_run_id: str
    tentative_minimum: float
    credit_applied: float
    minimum_due: float
    maximum_deductible: float
    paid_to_date: float
    outstanding_amount: float
    excise_accrued: float
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only payment event; carries ONLY id + created_at
class ContributionPayment(TypedDict, total=False):
    id: str
    contribution_demand_id: str
    amount: float
    paid_on: str
    created_at: str


class PBGCFiling(TypedDict, total=False):
    id: str
    plan_id: str
    valuation_run_id: str
    plan_year: int
    premium_method: str
    participant_count: int
    premium_target: float
    market_assets: float
    uvb: float
    flat_rate_premium: float
    variable_rate_premium: float
    total_premium: float
    cap_applied: bool
    status: str
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureReport(TypedDict, total=False):
    id: str
    plan_id: str
    valuation_run_id: str
    pbo: float
    fair_value_assets: float
    funded_status: float
    status: str
    acknowledged_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
