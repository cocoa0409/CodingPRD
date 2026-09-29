"""Domain types for the bank merger application and community impact review API.

Entity TypedDicts, status enums and the role enum. Every persisted record in this
domain exposes id, created_at, updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


class UserRole(str, Enum):
    FILER = "Filer"
    PUBLIC_COMMENTER = "PublicCommenter"
    CASE_ANALYST = "CaseAnalyst"
    APPROVING_OFFICIAL = "ApprovingOfficial"
    COMPLIANCE_MONITOR = "ComplianceMonitor"


class CharterType(str, Enum):
    NATIONAL = "NATIONAL"
    STATE_MEMBER = "STATE_MEMBER"
    STATE_NONMEMBER = "STATE_NONMEMBER"
    SAVINGS = "SAVINGS"


class PrimaryRegulator(str, Enum):
    OCC = "OCC"
    FRB = "FRB"
    FDIC = "FDIC"


class CraRating(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    SATISFACTORY = "SATISFACTORY"
    NEEDS_TO_IMPROVE = "NEEDS_TO_IMPROVE"
    SUBSTANTIAL_NONCOMPLIANCE = "SUBSTANTIAL_NONCOMPLIANCE"


class InstitutionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MERGED_OUT = "MERGED_OUT"


class MarketType(str, Enum):
    MSA = "MSA"
    RURAL_COUNTY = "RURAL_COUNTY"


class ServiceType(str, Enum):
    FULL_SERVICE = "FULL_SERVICE"
    LIMITED_SERVICE = "LIMITED_SERVICE"


class BranchStatus(str, Enum):
    OPEN = "OPEN"
    DESIGNATED_FOR_DIVESTITURE = "DESIGNATED_FOR_DIVESTITURE"
    DESIGNATED_FOR_CLOSURE = "DESIGNATED_FOR_CLOSURE"
    DIVESTED = "DIVESTED"
    CLOSED = "CLOSED"


class DesignationType(str, Enum):
    DIVESTITURE = "DIVESTITURE"
    CLOSURE = "CLOSURE"


class MergerStructure(str, Enum):
    STATUTORY_MERGER = "STATUTORY_MERGER"
    PURCHASE_AND_ASSUMPTION = "PURCHASE_AND_ASSUMPTION"
    HOLDCO_ACQUISITION = "HOLDCO_ACQUISITION"


class ConsiderationType(str, Enum):
    ALL_CASH = "ALL_CASH"
    ALL_STOCK = "ALL_STOCK"
    MIXED = "MIXED"


class ManagementRating(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    CONDITIONAL = "CONDITIONAL"
    UNSATISFACTORY = "UNSATISFACTORY"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_AMENDMENT = "RETURNED_FOR_AMENDMENT"
    RECOMMENDED = "RECOMMENDED"
    DECIDED = "DECIDED"
    CONSUMMATED = "CONSUMMATED"
    DENIED = "DENIED"


class PublicReviewStatus(str, Enum):
    NOT_OPEN = "NOT_OPEN"
    OPEN_FOR_COMMENT = "OPEN_FOR_COMMENT"
    PROTEST_PENDING = "PROTEST_PENDING"
    HEARING_PENDING = "HEARING_PENDING"
    HEARING_GRANTED = "HEARING_GRANTED"
    COMMENT_CLOSED = "COMMENT_CLOSED"
    CLEARED = "CLEARED"


class CompetitivePosture(str, Enum):
    NOT_ANALYZED = "NOT_ANALYZED"
    CLEARED = "CLEARED"
    CLEARED_WITH_DIVESTITURE = "CLEARED_WITH_DIVESTITURE"
    MITIGATION_REQUIRED = "MITIGATION_REQUIRED"
    BLOCKED = "BLOCKED"


class Recommendation(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
    DENY = "DENY"


class PostClosingMonitoringStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MONITORING = "MONITORING"
    ESCALATED = "ESCALATED"


class ScheduleBasis(str, Enum):
    REGULATORY_ADJUSTED = "REGULATORY_ADJUSTED"
    INTERNAL_STRESS = "INTERNAL_STRESS"


class CapitalAdequacyFlag(str, Enum):
    WELL_CAPITALIZED = "WELL_CAPITALIZED"
    ADEQUATELY_CAPITALIZED = "ADEQUATELY_CAPITALIZED"
    UNDERCAPITALIZED = "UNDERCAPITALIZED"


class ScheduleStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class ScreenResult(str, Enum):
    PASS = "PASS"
    MITIGATION_REQUIRED = "MITIGATION_REQUIRED"
    PRESUMPTIVE_VIOLATION = "PRESUMPTIVE_VIOLATION"


class CommentPeriodStatus(str, Enum):
    OPEN = "OPEN"
    EXTENDED = "EXTENDED"
    CLOSED = "CLOSED"


class CommenterType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    COMMUNITY_ORGANIZATION = "COMMUNITY_ORGANIZATION"
    TRADE_GROUP = "TRADE_GROUP"
    GOVERNMENT = "GOVERNMENT"


class Stance(str, Enum):
    SUPPORT = "SUPPORT"
    OPPOSE = "OPPOSE"
    PROTEST = "PROTEST"


class CommentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESPONDED = "RESPONDED"
    UNTIMELY = "UNTIMELY"


class Disposition(str, Enum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESPONDED = "RESPONDED"


class HearingRequestStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class HearingOutcome(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class MeasurementBasis(str, Enum):
    CUMULATIVE_TO_DATE = "CUMULATIVE_TO_DATE"
    ANNUAL_PRO_RATA = "ANNUAL_PRO_RATA"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    DEFICIENT = "DEFICIENT"


class PlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"


class CommitmentCategory(str, Enum):
    MORTGAGE_LENDING = "MORTGAGE_LENDING"
    SMALL_BUSINESS_LENDING = "SMALL_BUSINESS_LENDING"
    PHILANTHROPY = "PHILANTHROPY"
    BRANCH_RETENTION = "BRANCH_RETENTION"
    CDFI_INVESTMENT = "CDFI_INVESTMENT"


class DecisionOutcome(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    DENIED = "DENIED"


class DecisionStatus(str, Enum):
    ISSUED = "ISSUED"
    CONSUMMATED = "CONSUMMATED"
    LAPSED = "LAPSED"
    CLOSED = "CLOSED"


class ConditionType(str, Enum):
    DIVESTITURE = "DIVESTITURE"
    COMMUNITY_BENEFITS = "COMMUNITY_BENEFITS"
    CAPITAL_MAINTENANCE = "CAPITAL_MAINTENANCE"
    BRANCH_RETENTION = "BRANCH_RETENTION"
    SYSTEMS_CONVERSION = "SYSTEMS_CONVERSION"


class ConditionTiming(str, Enum):
    PRE_CONSUMMATION = "PRE_CONSUMMATION"
    POST_CLOSING = "POST_CLOSING"


class ConditionStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    BREACHED = "BREACHED"


class ConversionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    DISCLOSED = "DISCLOSED"
    CONVERTED = "CONVERTED"


class DisclosureChannel(str, Enum):
    MAIL = "MAIL"
    EMAIL = "EMAIL"
    IN_BRANCH_NOTICE = "IN_BRANCH_NOTICE"
    ONLINE_BANKING = "ONLINE_BANKING"


class ReportStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"


# --- Entity shapes -------------------------------------------------------
# Every entity in this service carries id, created_at, updated_at and version.

class Institution(TypedDict):
    id: str
    legal_name: str
    charter_type: str
    primary_regulator: str
    cet1_capital_usd: int
    tier1_capital_usd: int
    total_capital_usd: int
    risk_weighted_assets_usd: int
    average_total_assets_usd: int
    total_loans_usd: int
    latest_cra_rating: str
    cra_exam_closed_at: Optional[str]
    status: str
    total_deposits_usd: int
    branch_count: int
    created_at: str
    updated_at: str
    version: int


class DepositMarket(TypedDict):
    id: str
    market_code: str
    market_name: str
    market_type: str
    total_deposits_usd: int
    participant_count: int
    hhi_current: int
    created_at: str
    updated_at: str
    version: int


class Branch(TypedDict):
    id: str
    institution_id: str
    market_id: str
    branch_name: str
    deposits_usd: int
    service_type: str
    status: str
    designation_application_id: Optional[str]
    notice_sent_at: Optional[str]
    planned_closure_date: Optional[str]
    notice_lead_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MergerApplication(TypedDict):
    id: str
    acquirer_id: str
    target_id: str
    structure: str
    consideration_type: str
    total_consideration_usd: int
    officer_experience_score: int
    risk_management_score: int
    compliance_history_score: int
    integration_readiness_score: int
    management_composite_score: float
    management_rating: str
    filing_status: str
    public_review_status: str
    competitive_posture: str
    substantive_protest_count: int
    unresolved_protest_count: int
    earliest_decision_at: Optional[str]
    recommended_by_user_id: Optional[str]
    recommendation: Optional[str]
    amendment_round: int
    post_closing_monitoring_status: str
    created_at: str
    updated_at: str
    version: int


class ProFormaCapitalSchedule(TypedDict):
    id: str
    application_id: str
    basis: str
    goodwill_created_usd: int
    core_deposit_intangible_usd: int
    aoci_markdown_usd: int
    deferred_tax_asset_usd: int
    transaction_costs_usd: int
    cash_consideration_usd: int
    pro_forma_cet1_ratio_pct: float
    pro_forma_tier1_leverage_pct: float
    capital_adequacy_flag: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CompetitiveAnalysis(TypedDict):
    id: str
    application_id: str
    market_id: str
    combined_market_deposits_usd: int
    hhi_pre_merger: int
    hhi_post_unmitigated: int
    hhi_delta_unmitigated: int
    screen_result: str
    required_divestiture_deposits_usd: int
    designated_divestiture_deposits_usd: int
    hhi_post_mitigated: int
    mitigation_satisfied: bool
    created_at: str
    updated_at: str
    version: int


class PublicCommentPeriod(TypedDict):
    id: str
    application_id: str
    opens_at: str
    duration_days: int
    closes_at: str
    extension_count: int
    extended_days_total: int
    status: str
    comment_count: int
    substantive_protest_count: int
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    id: str
    period_id: str
    commenter_user_id: str
    commenter_name: str
    commenter_type: str
    stance: str
    substantive: bool
    body: str
    received_at: str
    status: str
    response_body: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HearingRequest(TypedDict):
    id: str
    application_id: str
    comment_id: str
    requester_user_id: str
    requested_at: str
    basis: str
    status: str
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    decision_rationale: Optional[str]
    extension_days_granted: int
    created_at: str
    updated_at: str
    version: int


class CommunityBenefitsPlan(TypedDict):
    id: str
    application_id: str
    term_years: int
    measurement_basis: str
    total_committed_usd: int
    annual_target_total_usd: int
    quarterly_target_total_usd: int
    credited_to_date_usd: int
    remaining_commitment_usd: int
    compliance_status: str
    consecutive_deficient_periods: int
    filed_report_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitmentLineItem(TypedDict):
    id: str
    plan_id: str
    category: str
    committed_usd: int
    annual_target_usd: int
    final_year_target_usd: int
    credited_usd: int
    created_at: str
    updated_at: str
    version: int


class ApprovalDecision(TypedDict):
    id: str
    application_id: str
    decision: str
    decided_by_user_id: str
    decided_at: str
    expedited_processing: bool
    waiting_period_days: int
    consummation_window_open_at: Optional[str]
    consummation_deadline_at: Optional[str]
    status: str
    consummated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApprovalCondition(TypedDict):
    id: str
    decision_id: str
    condition_type: str
    timing: str
    description: str
    threshold_usd: Optional[int]
    status: str
    satisfied_at: Optional[str]
    satisfied_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SystemsConversionPlan(TypedDict):
    id: str
    application_id: str
    conversion_start_date: str
    conversion_end_date: str
    affected_customer_count: int
    disclosure_channels: Optional[List[str]]
    customer_disclosure_sent_at: Optional[str]
    disclosure_lead_days: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitmentPerformanceReport(TypedDict):
    id: str
    plan_id: str
    period_label: str
    period_index: int
    achieved_by_category: Dict[str, int]
    credited_usd: int
    excess_uncredited_usd: int
    measurement_basis: str
    fulfillment_pct: float
    alternate_fulfillment_pct: float
    filed_at: str
    reviewed_at: Optional[str]
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
