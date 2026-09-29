"""Domain types for the NPD stage-gate API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PORTFOLIO_ADMIN = "PortfolioAdmin"
    INNOVATION_LEAD = "InnovationLead"
    GATE_CHAIR = "GateChair"
    FUNCTIONAL_REVIEWER = "FunctionalReviewer"
    REGULATORY_APPROVER = "RegulatoryApprover"
    RND_LEAD = "RnDLead"
    SALES_ACCOUNT_MANAGER = "SalesAccountManager"


class Category(str, Enum):
    BEVERAGE = "BEVERAGE"
    SNACK = "SNACK"
    DAIRY = "DAIRY"
    HOUSEHOLD = "HOUSEHOLD"


class ProjectType(str, Enum):
    NEW_BRAND = "NEW_BRAND"
    LINE_EXTENSION = "LINE_EXTENSION"
    RENOVATION = "RENOVATION"


class Function(str, Enum):
    R_AND_D = "R_AND_D"
    MARKETING = "MARKETING"
    FINANCE = "FINANCE"
    OPERATIONS = "OPERATIONS"
    QUALITY = "QUALITY"
    REGULATORY = "REGULATORY"
    SALES = "SALES"


class VoteValue(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
    REJECT = "REJECT"


class Channel(str, Enum):
    GROCERY = "GROCERY"
    MASS = "MASS"
    CLUB = "CLUB"
    CONVENIENCE = "CONVENIENCE"
    ECOMMERCE = "ECOMMERCE"


class TestType(str, Enum):
    MONADIC = "MONADIC"
    SEQUENTIAL_MONADIC = "SEQUENTIAL_MONADIC"
    IN_HOME_USE = "IN_HOME_USE"


class VariantMode(str, Enum):
    BOTTOM_UP = "BOTTOM_UP"
    TOP_DOWN = "TOP_DOWN"


class CaseType(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"


class AllergenRegime(str, Enum):
    NONE = "NONE"
    DAIRY = "DAIRY"
    NUT = "NUT"
    GLUTEN = "GLUTEN"


class AttainmentBasis(str, Enum):
    CUMULATIVE = "CUMULATIVE"
    TRAILING = "TRAILING"


class PostLaunchDecision(str, Enum):
    CONTINUE = "CONTINUE"
    FIX = "FIX"
    DISCONTINUE = "DISCONTINUE"


class ScreeningDecision(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    REJECTED = "REJECTED"


class StabilityVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DeliverableType(str, Enum):
    CONSUMER_CONCEPT_TEST = "CONSUMER_CONCEPT_TEST"
    PRELIM_BUSINESS_CASE = "PRELIM_BUSINESS_CASE"
    FINAL_BUSINESS_CASE = "FINAL_BUSINESS_CASE"
    PILOT_SCALE_UP_REPORT = "PILOT_SCALE_UP_REPORT"
    SHELF_LIFE_REPORT = "SHELF_LIFE_REPORT"
    REGULATORY_CLEARANCE = "REGULATORY_CLEARANCE"
    MANUFACTURING_READINESS = "MANUFACTURING_READINESS"
    DISTRIBUTION_READINESS = "DISTRIBUTION_READINESS"
    MARKETING_LAUNCH_PLAN = "MARKETING_LAUNCH_PLAN"
    SALES_SELL_IN_PLAN = "SALES_SELL_IN_PLAN"


class DevStatus(str, Enum):
    IDEA = "IDEA"
    SCREENED = "SCREENED"
    PILOT_QUALIFIED = "PILOT_QUALIFIED"
    LAUNCH_READY = "LAUNCH_READY"
    LAUNCHED = "LAUNCHED"
    IN_MARKET_FIX = "IN_MARKET_FIX"
    KILLED = "KILLED"
    DISCONTINUED = "DISCONTINUED"


class CommercialStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SELL_IN_SCHEDULED = "SELL_IN_SCHEDULED"
    PRESENTED = "PRESENTED"
    AUTHORIZED = "AUTHORIZED"
    SELL_IN_REJECTED = "SELL_IN_REJECTED"
    LAUNCH_LOCKED = "LAUNCH_LOCKED"
    LOCK_SLIPPED = "LOCK_SLIPPED"
    SHIPPED = "SHIPPED"


class BusinessCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class DeliverableStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class GateReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    PASSED = "PASSED"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    RECYCLED = "RECYCLED"
    KILLED = "KILLED"
    CANCELLED = "CANCELLED"


class FormulationStatus(str, Enum):
    DRAFT = "DRAFT"
    PILOT_PASSED = "PILOT_PASSED"
    PILOT_FAILED = "PILOT_FAILED"
    SHELF_LIFE_CLEARED = "SHELF_LIFE_CLEARED"
    SUPERSEDED = "SUPERSEDED"


class PilotRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ShelfLifeStudyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class LabelApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class PresentationStatus(str, Enum):
    PLANNED = "PLANNED"
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


# --------------------------------------------------------------------------
# Entity shapes. Every entity carries id, created_at, updated_at and version,
# with the single exception of GateVote, which carries only id and created_at.
# --------------------------------------------------------------------------

class InnovationProject(TypedDict):
    id: str
    name: str
    brand: str
    category: str
    project_type: str
    strategic_fit_score: float
    consumer_need_score: float
    category_attractiveness_score: float
    target_gross_margin_pct: float
    development_budget_cap_usd: float
    owner_user_id: str
    dev_status: str
    commercial_status: str
    next_gate_number: int
    screening_decision: str
    screening_score: Optional[float]
    screening_notes: Optional[str]
    development_budget_committed_usd: float
    launch_readiness_pct: float
    authorized_acv_pct: float
    recycle_count: int
    open_gate_conditions: bool
    launch_date: Optional[str]
    shelf_reset_window_id: Optional[str]
    post_launch_decision: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StageGate(TypedDict):
    id: str
    gate_number: int
    category: str
    stage_from: str
    stage_to: str
    required_deliverable_types: List[str]
    quorum_size: int
    veto_functions: List[str]
    npv_hurdle_usd: float
    payback_months_max: int
    gross_margin_floor_pct: float
    readiness_floor_index: float
    created_at: str
    updated_at: str
    version: int


class Retailer(TypedDict):
    id: str
    name: str
    channel: str
    acv_contribution_pct: float
    presentation_lead_days: int
    created_at: str
    updated_at: str
    version: int


class ShelfResetWindow(TypedDict):
    id: str
    retailer_id: str
    category: str
    window_start: str
    window_end: str
    max_presentations: int
    booked_slot_count: int
    created_at: str
    updated_at: str
    version: int


class PilotLine(TypedDict):
    id: str
    plant_name: str
    line_code: str
    changeover_buffer_minutes: int
    allergen_regime: str
    hourly_cost_usd: float
    created_at: str
    updated_at: str
    version: int


class ConceptTest(TypedDict):
    id: str
    project_id: str
    test_type: str
    sample_size: int
    purchase_intent_top2_pct: float
    uniqueness_pct: float
    fielded_at: str
    concept_score: float
    is_authoritative: bool
    created_at: str
    updated_at: str
    version: int


class BusinessCase(TypedDict):
    id: str
    project_id: str
    case_type: str
    status: str
    variant_mode: str
    category_size_units_year: int
    target_share_pct: float
    cogs_per_unit_usd: float
    slotting_fees_usd: float
    capex_usd: float
    discount_rate_pct: float
    annual_units: int
    avg_list_price_usd: float
    gross_revenue_usd: float
    trade_spend_rate_pct: float
    trade_spend_usd: float
    net_revenue_usd: float
    cogs_total_usd: float
    gross_margin_usd: float
    gross_margin_pct: float
    npv_usd: float
    payback_months: int
    created_at: str
    updated_at: str
    version: int


class ForecastLine(TypedDict):
    id: str
    business_case_id: str
    channel: str
    store_count: int
    base_velocity_units_per_store_week: float
    promo_weeks: int
    promo_lift_pct: float
    list_price_usd: float
    line_units: int
    line_revenue_usd: float
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    project_id: str
    gate_id: str
    deliverable_type: str
    owner_function: str
    status: str
    due_at: Optional[str]
    prerequisite_deliverable_id: Optional[str]
    evidence_url: Optional[str]
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    submission_count: int
    created_at: str
    updated_at: str
    version: int


class GateReview(TypedDict):
    id: str
    project_id: str
    gate_id: str
    scheduled_at: str
    status: str
    decision: Optional[str]
    chair_user_id: Optional[str]
    conditions: Optional[str]
    conditions_due_at: Optional[str]
    closed_at: Optional[str]
    vote_count: int
    deliverable_completeness_pct: float
    readiness_index: float
    created_at: str
    updated_at: str
    version: int


class GateVote(TypedDict):
    """Immutable once cast: carries only id and created_at as audit fields."""
    id: str
    gate_review_id: str
    function: str
    vote: str
    rationale: Optional[str]
    voter_user_id: str
    created_at: str


class Formulation(TypedDict):
    id: str
    project_id: str
    revision: int
    spec_summary: str
    allergen_regime: str
    target_shelf_life_days: int
    unit_cost_usd: float
    status: str
    best_pilot_yield_pct: float
    created_at: str
    updated_at: str
    version: int


class PilotRun(TypedDict):
    id: str
    formulation_id: str
    pilot_line_id: str
    window_start: str
    window_end: str
    planned_units: int
    committed_cost_usd: float
    effective_buffer_minutes: int
    status: str
    actual_units: Optional[int]
    yield_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ShelfLifeStudy(TypedDict):
    id: str
    formulation_id: str
    duration_days: int
    committed_cost_usd: float
    start_at: str
    status: str
    timepoints: List[dict]
    min_quality_score: Optional[float]
    verdict: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabelApproval(TypedDict):
    id: str
    project_id: str
    formulation_id: str
    label_version: str
    claims: List[str]
    status: str
    unsupported_claims: List[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SellInPresentation(TypedDict):
    id: str
    project_id: str
    retailer_id: str
    shelf_reset_window_id: str
    scheduled_at: str
    proposed_sku_count: int
    accepted_sku_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PostLaunchPeriod(TypedDict):
    id: str
    project_id: str
    period_index: int
    actual_units: int
    actual_net_revenue_usd: float
    actual_gross_margin_usd: float
    attainment_basis: str
    plan_units_per_period: float
    attainment_cumulative_pct: float
    attainment_trailing_pct: float
    attainment_pct: float
    decision: str
    created_at: str
    updated_at: str
    version: int
