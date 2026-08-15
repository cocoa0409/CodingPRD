"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class MarketStatus(str, Enum):
    SCREENING = "SCREENING"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    SATURATED = "SATURATED"
    CLOSED = "CLOSED"


class StoreStatus(str, Enum):
    OPERATING = "OPERATING"
    CLOSED = "CLOSED"


class SiteStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENED = "SCREENED"
    MODELED = "MODELED"
    SCORED = "SCORED"
    FORECAST_LOCKED = "FORECAST_LOCKED"
    IN_COMMITTEE = "IN_COMMITTEE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    LOI_ACTIVE = "LOI_ACTIVE"
    LEASE_EXECUTED = "LEASE_EXECUTED"
    BUILD_OUT = "BUILD_OUT"
    OPEN = "OPEN"
    MEASURING = "MEASURING"
    UNDERPERFORMING = "UNDERPERFORMING"
    WITHDRAWN = "WITHDRAWN"
    CLOSED_OUT = "CLOSED_OUT"


class ModelStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class VisitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class ForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTEE_LOCKED = "COMMITTEE_LOCKED"
    ACTUALIZED = "ACTUALIZED"
    SUPERSEDED = "SUPERSEDED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    DECIDED = "DECIDED"
    RATIFIED = "RATIFIED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class LoiStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class LeaseStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class SnapshotStatus(str, Enum):
    RECORDED = "RECORDED"
    FINALIZED = "FINALIZED"


class FormatType(str, Enum):
    EXPRESS = "EXPRESS"
    STANDARD = "STANDARD"
    FLAGSHIP = "FLAGSHIP"


class CannibalizationVariant(str, Enum):
    FLAT_BAND = "FLAT_BAND"
    DISTANCE_DECAY = "DISTANCE_DECAY"


class ModelVariant(str, Enum):
    GRAVITY = "GRAVITY"
    ANALOG = "ANALOG"


class ListingType(str, Enum):
    COMPETITOR = "COMPETITOR"
    COTENANT = "COTENANT"


class Ballot(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class DecidedOutcome(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class OccupancyBand(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class ScreeningTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class MilestoneType(str, Enum):
    PERMIT_SUBMITTED = "PERMIT_SUBMITTED"
    PERMIT_APPROVED = "PERMIT_APPROVED"
    BUILD_START = "BUILD_START"
    BUILD_COMPLETE = "BUILD_COMPLETE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REAL_ESTATE_ANALYST = "RealEstateAnalyst"
    REAL_ESTATE_MANAGER = "RealEstateManager"
    COMMITTEE_MEMBER = "CommitteeMember"
    COMMITTEE_CHAIR = "CommitteeChair"
    CONSTRUCTION_MANAGER = "ConstructionManager"


# --- Entity TypedDicts (common_fields entities carry id/created_at/updated_at/version) ---


class Market(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    population: int
    median_household_income_cents: int
    population_growth_bp: int
    psychographic_index: int
    base_target_stores: int
    annual_capex_budget_cents: int
    max_rent_psf_cents: int
    prototype_sales_cents: int
    market_status: str
    raw_score: Optional[float]
    screening_tier: Optional[str]
    target_store_count: Optional[int]
    penetration_index: Optional[float]
    final_score: Optional[float]
    open_store_count: int
    committed_capex_cents: int
    created_at: str
    updated_at: str
    version: int


class ExistingStore(TypedDict, total=False):
    id: str
    market_id: str
    store_code: str
    format_type: str
    annual_sales_cents: int
    store_status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    market_id: str
    address: str
    format_type: str
    square_footage: int
    asking_rent_psf_cents: int
    cam_psf_cents: int
    tax_psf_cents: int
    build_cost_cents: int
    site_status: str
    consecutive_miss_count: int
    created_at: str
    updated_at: str
    version: int


class StoreDriveTime(TypedDict):
    store_id: str
    drive_minutes: int


class TradeAreaModel(TypedDict, total=False):
    id: str
    site_id: str
    drive_time_minutes: int
    trade_area_population: int
    per_capita_spend_cents: int
    cannibalization_variant: str
    store_drive_times: List[StoreDriveTime]
    model_status: str
    cannibalized_sales_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CompetitorListing(TypedDict, total=False):
    id: str
    trade_area_model_id: str
    listing_type: str
    brand_name: str
    estimated_sqft: int
    distance_minutes: int
    created_at: str
    updated_at: str
    version: int


class SiteVisit(TypedDict, total=False):
    id: str
    site_id: str
    visited_on: str
    visibility_score: int
    access_score: int
    parking_score: int
    cotenancy_score: int
    total_score: float
    visit_status: str
    created_at: str
    updated_at: str
    version: int


class SalesForecast(TypedDict, total=False):
    id: str
    site_id: str
    trade_area_model_id: str
    model_variant: str
    forecast_status: str
    gross_annual_sales_cents: int
    cannibalized_sales_cents: Optional[int]
    net_annual_sales_cents: Optional[int]
    occupancy_ratio_bp: Optional[int]
    occupancy_band: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict, total=False):
    id: str
    display_name: str
    is_chair: bool
    member_status: str
    created_at: str
    updated_at: str
    version: int


class CommitteeReview(TypedDict, total=False):
    id: str
    site_id: str
    sales_forecast_id: str
    sponsor_member_id: str
    chair_override: bool
    expires_at: str
    review_status: str
    decided_outcome: Optional[str]
    eligible_member_count: int
    quorum_count: int
    approve_votes: int
    reject_votes: int
    abstain_votes: int
    created_at: str
    updated_at: str
    version: int


class Vote(TypedDict, total=False):
    # Append-only record: carries ONLY id + created_at (no updated_at, no version)
    id: str
    review_id: str
    member_id: str
    ballot: str
    created_at: str


class LOI(TypedDict, total=False):
    id: str
    site_id: str
    rent_psf_cents: int
    escalation_pct_bp: int
    term_years: int
    ti_allowance_cents: int
    free_rent_months: int
    exclusivity_start_date: str
    exclusivity_end_date: str
    countered_rent_psf_cents: Optional[int]
    agreed_rent_psf_cents: Optional[int]
    round_number: int
    effective_annual_rent_cents: Optional[int]
    loi_status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    loi_id: str
    final_rent_psf_cents: int
    escalation_pct_bp: int
    term_years: int
    ti_allowance_cents: int
    free_rent_months: int
    crew_id: str
    build_start_date: str
    build_end_date: str
    effective_annual_rent_cents: Optional[int]
    final_occupancy_ratio_bp: Optional[int]
    lease_status: str
    created_at: str
    updated_at: str
    version: int


class ConstructionCrew(TypedDict, total=False):
    id: str
    crew_code: str
    crew_status: str
    created_at: str
    updated_at: str
    version: int


class PermitMilestone(TypedDict, total=False):
    id: str
    site_id: str
    milestone_type: str
    planned_date: str
    actual_date: Optional[str]
    milestone_status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceSnapshot(TypedDict, total=False):
    id: str
    site_id: str
    period_index: int
    actual_sales_cents: int
    expected_sales_cents: Optional[int]
    variance_bp: Optional[int]
    snapshot_status: str
    created_at: str
    updated_at: str
    version: int
