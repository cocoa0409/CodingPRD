"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    CENSUS_PENDING = "CENSUS_PENDING"
    CENSUS_RECEIVED = "CENSUS_RECEIVED"
    CLAIMS_PENDING = "CLAIMS_PENDING"
    RATING_IN_PROGRESS = "RATING_IN_PROGRESS"
    QUOTED = "QUOTED"
    NEGOTIATING = "NEGOTIATING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class BrokerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CensusStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ClaimsStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    REVIEWED = "REVIEWED"
    REJECTED = "REJECTED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    MODELED = "MODELED"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class StopLossStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    DECLINED = "DECLINED"


class RoundStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentEventStatus(str, Enum):
    REPORTED = "REPORTED"
    PROCESSED = "PROCESSED"
    VOIDED_GUARANTEE = "VOIDED_GUARANTEE"


class DisclosureStatus(str, Enum):
    PENDING = "PENDING"
    DISCLOSED = "DISCLOSED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class FundingType(str, Enum):
    FULLY_INSURED = "FULLY_INSURED"
    LEVEL_FUNDED = "LEVEL_FUNDED"
    SELF_FUNDED = "SELF_FUNDED"


class QuoteFundingType(str, Enum):
    FULLY_INSURED = "FULLY_INSURED"
    LEVEL_FUNDED = "LEVEL_FUNDED"


class ContributionStrategy(str, Enum):
    FLAT_DOLLAR = "FLAT_DOLLAR"
    PERCENTAGE = "PERCENTAGE"
    TIERED = "TIERED"


class EventType(str, Enum):
    NEW_HIRE = "NEW_HIRE"
    TERMINATION = "TERMINATION"
    COBRA_ELECTION = "COBRA_ELECTION"
    PLAN_MIGRATION = "PLAN_MIGRATION"


class ProposedBy(str, Enum):
    UNDERWRITER = "UNDERWRITER"
    BROKER = "BROKER"


class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    SENIOR_UNDERWRITER = "SeniorUnderwriter"
    BROKER = "Broker"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# All entities carry common fields: id, created_at, updated_at, version.

class UnderwritingCase(TypedDict, total=False):
    id: str
    group_name: str
    group_size: int
    sic_code: str
    state_code: str
    effective_date: str
    current_premium_annual: int
    current_renewal_date: str
    funding_type: str
    status: str
    assigned_underwriter_id: str
    broker_id: str
    credibility_factor: float
    blended_rate_cents: int
    manual_rate_cents: int
    experience_rate_cents: int
    rate_cap_pct: float
    is_rate_cap_applied: bool
    created_at: str
    updated_at: str
    version: int


class Broker(TypedDict, total=False):
    id: str
    firm_name: str
    license_number: str
    state_code: str
    commission_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CensusSnapshot(TypedDict, total=False):
    id: str
    case_id: str
    submitted_at: str
    total_employees: int
    enrolled_employees: int
    dependent_count: int
    average_age: float
    gender_ratio: float
    tier_distribution: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimsExperience(TypedDict, total=False):
    id: str
    case_id: str
    experience_period_start: str
    experience_period_end: str
    months_of_experience: int
    total_paid_claims_cents: int
    total_enrollment_months: int
    large_claim_count: int
    pooling_threshold_cents: int
    pooled_claims_cents: int
    experience_claim_cost_cents: int
    completion_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitPlanDesign(TypedDict, total=False):
    id: str
    case_id: str
    plan_name: str
    deductible_individual: int
    deductible_family: int
    oop_max_individual: int
    oop_max_family: int
    coinsurance_pct: float
    copay_primary: int
    copay_specialist: int
    actuarial_value: float
    relativity_factor: float
    employer_contribution_pct: float
    contribution_strategy: str
    is_reference_plan: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    case_id: str
    plan_design_id: str
    quote_number: int
    funding_type: str
    pepm_rate_cents: int
    annual_premium_cents: int
    renewal_increase_pct: float
    claims_fund_cents: int
    admin_fee_cents: int
    stop_loss_premium_cents: int
    broker_commission_cents: int
    commission_disclosure_required: bool
    rate_guarantee_months: int
    enrollment_change_threshold: float
    status: str
    negotiation_round: int
    parent_quote_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StopLossQuote(TypedDict, total=False):
    id: str
    quote_id: str
    case_id: str
    specific_deductible_cents: int
    aggregate_attachment_pct: float
    expected_annual_claims_cents: int
    aggregate_attachment_cents: int
    specific_premium_cents: int
    aggregate_premium_cents: int
    total_stop_loss_premium_cents: int
    laser_claimant_ids: List[str]
    laser_deductible_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NegotiationRound(TypedDict, total=False):
    id: str
    quote_id: str
    case_id: str
    round_number: int
    proposed_by: str
    proposed_pepm_cents: int
    proposed_contribution_pct: float
    proposed_deductible_individual: int
    justification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnrollmentChangeEvent(TypedDict, total=False):
    id: str
    case_id: str
    quote_id: str
    event_type: str
    change_count: int
    effective_date: str
    revised_enrollment: int
    enrollment_change_pct: float
    guarantee_voided: bool
    rate_adjustment_factor: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionDisclosure(TypedDict, total=False):
    id: str
    case_id: str
    quote_id: str
    broker_id: str
    total_commission_cents: int
    commission_pct: float
    per_enrollee_cents: int
    disclosure_threshold_cents: int
    requires_disclosure: bool
    disclosed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
