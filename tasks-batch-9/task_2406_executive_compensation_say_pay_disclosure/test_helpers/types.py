"""Domain types for the executive-compensation / say-on-pay API.

Status enums, value enums and entity TypedDicts. Every field name here is the
PRD-exact name; nothing is abbreviated.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COMP_CONSULTANT = "CompConsultant"
    COMP_COMMITTEE_CHAIR = "CompCommitteeChair"
    SECURITIES_COUNSEL = "SecuritiesCounsel"
    INVESTOR_RELATIONS_LEAD = "InvestorRelationsLead"
    NAMED_EXECUTIVE_OFFICER = "NamedExecutiveOfficer"


# ---------------------------------------------------------------------------
# Status enums (one per entity that carries a lifecycle)
# ---------------------------------------------------------------------------
class CompanyListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELISTED = "DELISTED"


class PeerGroupStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENED = "SCREENED"
    APPROVED = "APPROVED"


class PeerGroupMemberStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    EXCLUDED = "EXCLUDED"


class PayProgramDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTEE_APPROVED = "COMMITTEE_APPROVED"
    DISCLOSED = "DISCLOSED"
    CLOSED = "CLOSED"


class PayProgramVoteStatus(str, Enum):
    NOT_VOTED = "NOT_VOTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REMEDIATED = "REMEDIATED"


class IncentiveMetricStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    ADJUSTED = "ADJUSTED"
    RESULT_SUBMITTED = "RESULT_SUBMITTED"
    CERTIFIED = "CERTIFIED"
    RESTATED = "RESTATED"


class PayoutAwardStatus(str, Enum):
    GRANTED = "GRANTED"
    VESTED = "VESTED"
    FORFEITED = "FORFEITED"
    CLAWED_BACK = "CLAWED_BACK"


class CdaDraftStatus(str, Enum):
    DRAFTING = "DRAFTING"
    IN_REVIEW = "IN_REVIEW"
    LEGAL_CLEARED = "LEGAL_CLEARED"
    FILED = "FILED"


class ProxyAdvisorScreenStatus(str, Enum):
    SCREENED = "SCREENED"
    STALE = "STALE"


class OutreachEngagementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"


class RestatementEventStatus(str, Enum):
    DECLARED = "DECLARED"
    ANALYZED = "ANALYZED"
    RECOVERY_ORDERED = "RECOVERY_ORDERED"
    CLOSED = "CLOSED"


class ClawbackDeterminationStatus(str, Enum):
    CALCULATED = "CALCULATED"
    NOTICED = "NOTICED"
    RECOVERED = "RECOVERED"


# ---------------------------------------------------------------------------
# Value enums
# ---------------------------------------------------------------------------
class GicsSector(str, Enum):
    TECH = "TECH"
    INDUSTRIALS = "INDUSTRIALS"
    HEALTHCARE = "HEALTHCARE"
    FINANCIALS = "FINANCIALS"
    CONSUMER = "CONSUMER"
    ENERGY = "ENERGY"


class BenchmarkBasis(str, Enum):
    RAW_MEDIAN = "RAW_MEDIAN"
    SIZE_ADJUSTED = "SIZE_ADJUSTED"


class InclusionReason(str, Enum):
    SIZE_MATCH = "SIZE_MATCH"
    INDUSTRY_MATCH = "INDUSTRY_MATCH"
    BUSINESS_MODEL_ANALOG = "BUSINESS_MODEL_ANALOG"
    TALENT_COMPETITOR = "TALENT_COMPETITOR"


class RoleTitle(str, Enum):
    CEO = "CEO"
    CFO = "CFO"
    COO = "COO"
    CHRO = "CHRO"
    GC = "GC"


class BenchmarkPosture(str, Enum):
    UNBENCHMARKED = "UNBENCHMARKED"
    BELOW_MARKET = "BELOW_MARKET"
    ALIGNED = "ALIGNED"
    ABOVE_MARKET = "ABOVE_MARKET"


class AlignmentStatus(str, Enum):
    UNRATED = "UNRATED"
    ALIGNED = "ALIGNED"
    WATCH = "WATCH"
    MISALIGNED = "MISALIGNED"


class MetricCode(str, Enum):
    ADJ_EPS = "ADJ_EPS"
    REVENUE_GROWTH = "REVENUE_GROWTH"
    FCF = "FCF"
    ROIC = "ROIC"
    RTSR = "RTSR"
    COST_RATIO = "COST_RATIO"


class MetricVehicle(str, Enum):
    ANNUAL_INCENTIVE = "ANNUAL_INCENTIVE"
    LONG_TERM_PSU = "LONG_TERM_PSU"


class AwardVehicle(str, Enum):
    ANNUAL_INCENTIVE = "ANNUAL_INCENTIVE"
    LONG_TERM_PSU = "LONG_TERM_PSU"
    RSU = "RSU"


class MetricDirection(str, Enum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"


class Interpolation(str, Enum):
    LINEAR = "LINEAR"
    STEP = "STEP"


class Disposition(str, Enum):
    VEST = "VEST"
    FORFEIT = "FORFEIT"


class MixComponent(str, Enum):
    SALARY = "SALARY"
    STI = "STI"
    LTI = "LTI"


class CdaSectionCode(str, Enum):
    CD_AND_A = "CD_AND_A"
    SUMMARY_COMP_TABLE = "SUMMARY_COMP_TABLE"
    PAY_RATIO = "PAY_RATIO"
    PVP_TABLE = "PVP_TABLE"


class Advisor(str, Enum):
    ISS = "ISS"
    GLASS_LEWIS = "GLASS_LEWIS"


class ConcernLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Recommendation(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"


class OutreachChannel(str, Enum):
    CALL = "CALL"
    MEETING = "MEETING"
    LETTER = "LETTER"


class FeedbackPosition(str, Enum):
    SUPPORTIVE = "SUPPORTIVE"
    CONCERNED = "CONCERNED"
    OPPOSED = "OPPOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Every entity in this PRD carries the four common fields
# (id, created_at, updated_at, version).
# ---------------------------------------------------------------------------
class Company(TypedDict):
    id: str
    legal_name: str
    ticker: str
    is_issuer: bool
    gics_sector: str
    revenue_usd: float
    market_cap_usd: float
    share_price_usd: float
    ceo_tdc_usd: float
    listing_status: str
    market_data_updated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PeerGroup(TypedDict):
    id: str
    issuer_company_id: str
    fiscal_year: int
    benchmark_basis: str
    status: str
    accepted_member_count: int
    median_revenue_usd: Optional[float]
    median_market_cap_usd: Optional[float]
    benchmark_target_tdc_raw_usd: Optional[float]
    benchmark_target_tdc_adjusted_usd: Optional[float]
    benchmark_target_tdc_usd: Optional[float]
    size_fit_score: Optional[float]
    screened_at: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PeerGroupMember(TypedDict):
    id: str
    peer_group_id: str
    peer_company_id: str
    inclusion_reason: str
    revenue_ratio: Optional[float]
    market_cap_ratio: Optional[float]
    in_size_band: bool
    status: str
    exclusion_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Executive(TypedDict):
    id: str
    company_id: str
    full_name: str
    role_title: str
    is_neo: bool
    base_salary_usd: float
    sti_target_pct: float
    created_at: str
    updated_at: str
    version: int


class PayProgram(TypedDict):
    id: str
    issuer_company_id: str
    peer_group_id: str
    ceo_executive_id: str
    fiscal_year: int
    salary_pct: float
    sti_pct: float
    lti_pct: float
    lti_performance_share_pct: float
    sti_max_multiple: float
    tsr_percentile_rank: Optional[float]
    meeting_date: str
    performance_based_pct: Optional[float]
    fixed_leg_usd: Optional[float]
    benchmark_ratio: Optional[float]
    lti_multiple: Optional[float]
    lti_target_usd: Optional[float]
    target_tdc_usd: Optional[float]
    benchmark_posture: str
    realized_pay_total_usd: float
    realizable_pay_total_usd: float
    pay_percentile_rank: Optional[float]
    degree_of_alignment: Optional[float]
    alignment_status: str
    design_status: str
    vote_status: str
    votes_for: Optional[int]
    votes_against: Optional[int]
    abstentions: Optional[int]
    support_pct: Optional[float]
    enhanced_engagement_required: bool
    outreach_coverage_pct: float
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncentiveMetric(TypedDict):
    id: str
    pay_program_id: str
    metric_code: str
    vehicle: str
    direction: str
    weight_pct: float
    threshold_value: float
    target_value: float
    maximum_value: float
    threshold_payout_pct: float
    target_payout_pct: float
    maximum_payout_pct: float
    interpolation: str
    locked_target_value: Optional[float]
    goal_adjustment_pct: Optional[float]
    as_reported_value: Optional[float]
    non_gaap_adjusted_value: Optional[float]
    result_adjustment_reason: Optional[str]
    achieved_value: Optional[float]
    payout_factor_pct: Optional[float]
    original_payout_factor_pct: Optional[float]
    restated_payout_factor_pct: Optional[float]
    status: str
    adjusted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayoutAward(TypedDict):
    id: str
    pay_program_id: str
    executive_id: str
    vehicle: str
    units_granted: Optional[float]
    grant_price_usd: Optional[float]
    target_amount_usd: Optional[float]
    certified_factor_pct: Optional[float]
    earned_amount_usd: Optional[float]
    settlement_date: Optional[str]
    vest_price_usd: Optional[float]
    realized_value_usd: float
    realizable_value_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CdaDraft(TypedDict):
    id: str
    pay_program_id: str
    section_code: str
    word_count: int
    required_tables_included: bool
    revision_round: int
    authored_by_user_id: str
    cleared_by_user_id: Optional[str]
    status: str
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProxyAdvisorScreen(TypedDict):
    id: str
    pay_program_id: str
    advisor: str
    alignment_component: Optional[float]
    mix_component: Optional[float]
    rigor_component: Optional[float]
    outreach_component: Optional[float]
    concern_score: Optional[float]
    concern_level: Optional[str]
    recommendation: Optional[str]
    status: str
    screened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutreachEngagement(TypedDict):
    id: str
    pay_program_id: str
    investor_name: str
    investor_key: str
    ownership_pct: float
    channel: str
    window_start: Optional[str]
    window_end: Optional[str]
    engagement_status: str
    feedback_position: Optional[str]
    feedback_summary: Optional[str]
    held_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestatementEvent(TypedDict):
    id: str
    company_id: str
    restatement_date: str
    lookback_start: str
    lookback_end: str
    accounting_reason: str
    status: str
    determination_count: int
    recoverable_total_usd: float
    recovered_total_usd: float
    created_at: str
    updated_at: str
    version: int


class ClawbackDetermination(TypedDict):
    id: str
    restatement_event_id: str
    payout_award_id: str
    original_factor_pct: Optional[float]
    restated_factor_pct: Optional[float]
    restated_amount_usd: Optional[float]
    recoverable_amount_usd: float
    status: str
    noticed_at: Optional[str]
    acknowledged_at: Optional[str]
    acknowledged_by_user_id: Optional[str]
    recovered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


RestatedMetricResult = TypedDict(
    "RestatedMetricResult",
    {"incentive_metric_id": str, "restated_achieved_value": float},
)

MetricList = List[IncentiveMetric]
