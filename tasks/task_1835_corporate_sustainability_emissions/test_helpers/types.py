"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    MANAGER = "SustainabilityManager"
    ANALYST = "SustainabilityAnalyst"
    STEWARD = "SiteDataSteward"
    LEAD = "DisclosureLead"
    ASSURER = "AssuranceProvider"
    SUPPLIER = "SupplierContact"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    DATA_COLLECTION = "DATA_COLLECTION"
    UNDER_REVIEW = "UNDER_REVIEW"
    LOCKED = "LOCKED"
    UNDER_ASSURANCE = "UNDER_ASSURANCE"
    ASSURED = "ASSURED"
    DISCLOSED = "DISCLOSED"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class FactorStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ScopeCategory(str, Enum):
    SCOPE1_STATIONARY = "SCOPE1_STATIONARY"
    SCOPE2_GRID = "SCOPE2_GRID"
    SCOPE2_RESIDUAL_MIX = "SCOPE2_RESIDUAL_MIX"
    SCOPE3_TRAVEL = "SCOPE3_TRAVEL"
    SCOPE3_EEIO_SPEND = "SCOPE3_EEIO_SPEND"


class ActivityType(str, Enum):
    ELECTRICITY = "ELECTRICITY"
    STATIONARY_FUEL = "STATIONARY_FUEL"
    BUSINESS_TRAVEL = "BUSINESS_TRAVEL"


class RecordStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class EvidenceStatus(str, Enum):
    UPLOADED = "UPLOADED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class InventoryStatus(str, Enum):
    STALE = "STALE"
    CURRENT = "CURRENT"
    FROZEN = "FROZEN"


class EngagementStatus(str, Enum):
    INVITED = "INVITED"
    RESPONDED = "RESPONDED"
    NEEDS_REVISION = "NEEDS_REVISION"
    ACCEPTED = "ACCEPTED"
    CLOSED_NO_DATA = "CLOSED_NO_DATA"


class EngagementCategory(str, Enum):
    PURCHASED_GOODS = "PURCHASED_GOODS"
    CAPITAL_GOODS = "CAPITAL_GOODS"
    UPSTREAM_TRANSPORT = "UPSTREAM_TRANSPORT"


class TargetStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    ACHIEVED = "ACHIEVED"
    MISSED = "MISSED"
    RETIRED = "RETIRED"


class BaselineSource(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    RECALCULATED = "RECALCULATED"


class TrajectoryStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    OFF_TRACK = "OFF_TRACK"
    NOT_EVALUATED = "NOT_EVALUATED"


class ScopeCoverage(str, Enum):
    SCOPE1_2 = "SCOPE1_2"
    SCOPE1_2_3 = "SCOPE1_2_3"


class Technology(str, Enum):
    SOLAR = "SOLAR"
    WIND = "WIND"
    HYDRO = "HYDRO"


class InstrumentStatus(str, Enum):
    PROCURED = "PROCURED"
    RETIRED = "RETIRED"
    EXPIRED = "EXPIRED"


class Framework(str, Enum):
    CDP = "CDP"
    GRI = "GRI"
    ECOVADIS = "ECOVADIS"


class QuestionnaireStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"


# Required answer sections per framework (PRD §3.9).
REQUIRED_SECTIONS = {
    "CDP": ["GOVERNANCE", "RISKS", "EMISSIONS", "TARGETS"],
    "GRI": ["DISCLOSURE_305", "ENERGY"],
    "ECOVADIS": ["ENVIRONMENT"],
}


class Site(TypedDict):
    id: str
    name: str
    country_code: str
    grid_region_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionFactor(TypedDict):
    id: str
    scope_category: str
    region_code: str
    unit: str
    value_tco2e_per_unit: float
    library_version: int
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportingCycle(TypedDict):
    id: str
    name: str
    reporting_year: int
    status: str
    readiness_pct: float
    pinned_library_version: Optional[int]
    assurance_statement: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActivityRecord(TypedDict):
    id: str
    cycle_id: str
    site_id: str
    factor_id: str
    activity_type: str
    quantity: float
    unit: str
    period_start: str
    period_end: str
    status: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    reject_reason: Optional[str]
    factor_value_snapshot: Optional[float]
    tco2e: Optional[float]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict):
    id: str
    activity_record_id: str
    supersedes_evidence_id: Optional[str]
    file_name: str
    sha256_hex: str
    status: str
    uploaded_by_user_id: str
    verified_by_user_id: Optional[str]
    retention_until: str
    created_at: str
    updated_at: str
    version: int


class InventoryResult(TypedDict):
    id: str
    cycle_id: str
    status: str
    scope1_tco2e: float
    scope2_location_tco2e: float
    scope2_market_tco2e: float
    scope3_tco2e: float
    scope3_provisional_tco2e: float
    total_tco2e: float
    computed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplierEngagement(TypedDict):
    id: str
    cycle_id: str
    supplier_name: str
    category: str
    spend_usd: float
    contact_user_id: str
    due_date: str
    status: str
    round: int
    supplier_tco2e: Optional[float]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmissionTarget(TypedDict):
    id: str
    name: str
    base_year: int
    target_year: int
    reduction_pct: float
    scope_coverage: str
    base_year_total_tco2e: float
    baseline_source: str
    baseline_shift_pct: Optional[float]
    baseline_shift_significant: Optional[bool]
    status: str
    trajectory_status: str
    created_at: str
    updated_at: str
    version: int


class RenewableInstrument(TypedDict):
    id: str
    registry: str
    serial_number: str
    technology: str
    vintage_year: int
    quantity_mwh: float
    status: str
    retired_for_cycle_id: Optional[str]
    retired_for_site_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuestionnaireResponse(TypedDict):
    id: str
    cycle_id: str
    framework: str
    prepared_by_user_id: str
    sections: dict
    completeness_pct: float
    emissions_section_stale: bool
    status: str
    review_decision_by: Optional[str]
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int
