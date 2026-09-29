"""Domain types: entity TypedDicts, status enums and the role enum."""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    NETWORK_STRATEGIST = "NetworkStrategist"
    CONSOLIDATION_APPROVER = "ConsolidationApprover"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    HR_PARTNER = "HRPartner"
    REAL_ESTATE_MANAGER = "RealEstateManager"
    BRANCH_MANAGER = "BranchManager"
    NETWORK_OPS_ADMIN = "NetworkOpsAdmin"


class SaturationTier(str, Enum):
    OVER_BRANCHED = "OVER_BRANCHED"
    SATURATED = "SATURATED"
    UNDER_BRANCHED = "UNDER_BRANCHED"


class BranchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSURE_SCHEDULED = "CLOSURE_SCHEDULED"
    CLOSED = "CLOSED"
    DE_NOVO_RAMPING = "DE_NOVO_RAMPING"


class BranchType(str, Enum):
    FULL_SERVICE = "FULL_SERVICE"
    LIMITED_SERVICE = "LIMITED_SERVICE"
    DRIVE_UP = "DRIVE_UP"


class TenureClass(str, Enum):
    LEASED = "LEASED"
    OWNED = "OWNED"


class ScoringVariant(str, Enum):
    POINT_IN_TIME = "POINT_IN_TIME"
    TRAILING_BLEND = "TRAILING_BLEND"


class PerformanceBand(str, Enum):
    CORE = "CORE"
    STABLE = "STABLE"
    WATCH = "WATCH"
    CONSOLIDATION_CANDIDATE = "CONSOLIDATION_CANDIDATE"
    UNSCORED = "UNSCORED"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    NOTICE_FILED = "NOTICE_FILED"
    CLOSURE_EXECUTED = "CLOSURE_EXECUTED"
    POST_CLOSE_MONITORING = "POST_CLOSE_MONITORING"
    UNWOUND = "UNWOUND"
    CLOSED_OUT = "CLOSED_OUT"


class RationaleCode(str, Enum):
    LOW_PERFORMANCE = "LOW_PERFORMANCE"
    LEASE_EXPIRY = "LEASE_EXPIRY"
    MARKET_OVERLAP = "MARKET_OVERLAP"
    DIGITAL_MIGRATION = "DIGITAL_MIGRATION"


class GovernanceFlag(str, Enum):
    NONE = "NONE"
    SAVINGS_WATCH = "SAVINGS_WATCH"


class MonitoringPosture(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ON_TRACK = "ON_TRACK"
    REMEDIATION = "REMEDIATION"
    RESOLVED = "RESOLVED"


class ImpactTier(str, Enum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    UNASSESSED = "UNASSESSED"


class RetentionModelVariant(str, Enum):
    DISTANCE_DECAY = "DISTANCE_DECAY"
    SEGMENT_MIX = "SEGMENT_MIX"


class ForecastStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    REOPENED = "REOPENED"
    SUPERSEDED = "SUPERSEDED"


class NoticeType(str, Enum):
    REGULATOR = "REGULATOR"
    CUSTOMER = "CUSTOMER"
    LOBBY_POSTING = "LOBBY_POSTING"


class NoticeStatus(str, Enum):
    FILED = "FILED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class WithdrawnReasonCode(str, Enum):
    REGULATOR_OBJECTION = "REGULATOR_OBJECTION"
    PLAN_REVISION = "PLAN_REVISION"
    COMMUNITY_PROTEST = "COMMUNITY_PROTEST"


class ProposedDisposition(str, Enum):
    REDEPLOYMENT = "REDEPLOYMENT"
    SEVERANCE = "SEVERANCE"


class DispositionState(str, Enum):
    PROPOSED = "PROPOSED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    SEVERED = "SEVERED"
    COMPLETED = "COMPLETED"


class NotificationState(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"


class AtmDisposition(str, Enum):
    RETAIN_OFFSITE = "RETAIN_OFFSITE"
    RELOCATE = "RELOCATE"
    DECOMMISSION = "DECOMMISSION"


class PropertyStatus(str, Enum):
    PENDING = "PENDING"
    MARKETED = "MARKETED"
    HOLDOVER = "HOLDOVER"
    ASSIGNMENT_PENDING = "ASSIGNMENT_PENDING"
    SALE_PENDING = "SALE_PENDING"
    DISPOSED = "DISPOSED"


class ChannelMix(str, Enum):
    LETTER_ONLY = "LETTER_ONLY"
    LETTER_EMAIL = "LETTER_EMAIL"
    FULL_OMNI = "FULL_OMNI"


class CampaignStatus(str, Enum):
    PLANNED = "PLANNED"
    LAUNCHED = "LAUNCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PlanStatus(str, Enum):
    SITE_IDENTIFIED = "SITE_IDENTIFIED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    HELD = "HELD"
    OPENED = "OPENED"
    RAMP_TRACKING = "RAMP_TRACKING"
    RAMP_REMEDIATION = "RAMP_REMEDIATION"
    RAMP_MET = "RAMP_MET"


class RampStatus(str, Enum):
    UNTRACKED = "UNTRACKED"
    ON_TRACK = "ON_TRACK"
    BEHIND = "BEHIND"
    AT_RISK = "AT_RISK"
    MET = "MET"


class SubjectType(str, Enum):
    CONSOLIDATION_CASE = "CONSOLIDATION_CASE"
    DE_NOVO_PLAN = "DE_NOVO_PLAN"


class MarketArea(TypedDict):
    id: str
    name: str
    region_code: str
    population: int
    median_household_income_cents: int
    deposit_market_total_cents: int
    competitor_branch_count: int
    household_growth_pct_bps: int
    digital_penetration_bps: int
    competitor_density_index: int
    own_branch_count: int
    branch_density_per_100k: int
    saturation_tier: str
    absorbed_deposits_cents: int
    cumulative_runoff_deposits_cents: int
    flagged_case_count: int
    remediation_case_count: int
    de_novo_hold: bool
    created_at: str
    updated_at: str
    version: int


class Branch(TypedDict):
    id: str
    market_area_id: str
    branch_code: str
    branch_type: str
    tenure_class: str
    deposit_balance_cents: int
    monthly_transaction_count: int
    digital_adoption_bps: int
    annual_noninterest_expense_cents: int
    annual_revenue_cents: int
    fte_count: int
    atm_count: int
    opened_on: str
    scoring_variant: str
    onboarding_capacity_households_per_day: int
    status: str
    performance_score_bps: Optional[int]
    performance_band: str
    snapshot_count: int
    transferred_in_deposits_cents: int
    absorbing_branch_id: Optional[str]
    pre_close_deposits_cents: Optional[int]
    pre_close_fte_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Immutable append-only reading: carries only id and created_at.
class PerformanceSnapshot(TypedDict):
    id: str
    branch_id: str
    period_label: str
    period_end_date: str
    deposits_cents: int
    transaction_count: int
    digital_active_bps: int
    revenue_cents: int
    noninterest_expense_cents: int
    composite_score_bps: int
    band: str
    created_at: str


class ConsolidationCase(TypedDict):
    id: str
    closing_branch_id: str
    receiving_branch_id: Optional[str]
    rationale_code: str
    planned_closure_date: str
    retention_model_variant: str
    status: str
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    returned_count: int
    governance_flag: str
    impact_tier: str
    notice_required_days: int
    monitoring_posture: str
    last_observed_month_index: int
    cumulative_variance_bps: int
    forecast_retention_bps: int
    forecast_retained_deposits_cents: int
    forecast_runoff_cents: int
    gross_annual_savings_cents: int
    transition_incentive_rate_bps: int
    transition_incentive_cents: int
    net_annual_savings_cents: int
    severance_pool_cents: int
    pending_disposition_count: int
    redeployed_fte_count: int
    severed_fte_count: int
    pre_close_deposits_cents: Optional[int]
    executed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetentionForecast(TypedDict):
    id: str
    consolidation_case_id: str
    model_variant: str
    distance_miles: float
    retail_share_bps: int
    small_business_share_bps: int
    wealth_share_bps: int
    baseline_deposits_cents: int
    digital_adoption_bps: int
    retention_bps: int
    retained_deposits_cents: int
    runoff_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommunityImpactAssessment(TypedDict):
    id: str
    consolidation_case_id: str
    lmi_tract: bool
    distance_to_nearest_remaining_miles: float
    alternative_access_count: int
    senior_household_pct_bps: int
    public_transit_access: bool
    market_saturation_tier_at_assessment: str
    impact_score: int
    impact_tier: str
    requires_public_comment: bool
    notice_required_days: int
    status: str
    finalized_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClosureNotice(TypedDict):
    id: str
    consolidation_case_id: str
    notice_type: str
    effective_closure_date: str
    filed_on: str
    required_lead_days: int
    lead_days: int
    buffer_end_date: str
    status: str
    withdrawn_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffDisposition(TypedDict):
    id: str
    consolidation_case_id: str
    source_branch_id: str
    target_branch_id: Optional[str]
    employee_ref: str
    role_title: str
    tenure_months: int
    annual_salary_cents: int
    proposed_disposition: str
    service_years: int
    severance_weeks: int
    weekly_pay_cents: int
    severance_amount_cents: int
    disposition_state: str
    notification_state: str
    notified_on: Optional[str]
    severed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PropertyDisposition(TypedDict):
    id: str
    branch_id: str
    consolidation_case_id: str
    tenure_class: str
    atm_disposition: str
    atm_monthly_cost_cents: int
    atm_monthly_surcharge_revenue_cents: int
    atm_breakeven_met: bool
    atm_decision_final: str
    monthly_rent_cents: Optional[int]
    lease_end_date: Optional[str]
    buyout_offer_cents: Optional[int]
    book_value_cents: Optional[int]
    list_price_cents: Optional[int]
    counterparty_ref: Optional[str]
    agreed_amount_cents: Optional[int]
    selling_costs_cents: Optional[int]
    net_disposition_cents: Optional[int]
    annual_carry_cents: int
    status: str
    marketing_started_on: Optional[str]
    settled_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomerTransitionCampaign(TypedDict):
    id: str
    consolidation_case_id: str
    receiving_branch_id: str
    wave_start_date: str
    wave_end_date: str
    inbound_household_count: int
    channel_mix: str
    wave_days: int
    daily_onboarding_load: int
    status: str
    launched_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeNovoSitePlan(TypedDict):
    id: str
    market_area_id: str
    site_label: str
    proposed_branch_code: str
    target_year1_deposits_cents: int
    capex_budget_cents: int
    site_score: int
    status: str
    ramp_status: str
    ramp_month_index: int
    ramp_attainment_bps: int
    opened_branch_id: Optional[str]
    opened_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable append-only reading: carries only id and created_at.
class DepositObservation(TypedDict):
    id: str
    subject_type: str
    consolidation_case_id: Optional[str]
    de_novo_plan_id: Optional[str]
    month_index: int
    observed_deposits_cents: int
    forecast_deposits_cents: int
    variance_bps: int
    breach: bool
    observed_on: str
    created_at: str
