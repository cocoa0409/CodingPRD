"""Domain types: entity TypedDicts, status enums, role enum.

All entities except Underwriter carry the full common-field quartet
(id, created_at, updated_at, version). Underwriter is immutable after
creation and carries only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    ADMIN = "Admin"
    AGENT = "Agent"
    UNDERWRITER = "Underwriter"
    INSPECTOR = "Inspector"


# --- Status / enum value sets ---
class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class EstimateVariant(str, Enum):
    COMPONENT = "COMPONENT"
    SQFT_BLEND = "SQFT_BLEND"
    NONE = "NONE"


class ConstructionType(str, Enum):
    FRAME = "FRAME"
    MASONRY = "MASONRY"
    FIRE_RESISTIVE = "FIRE_RESISTIVE"


class FloodZone(str, Enum):
    X = "X"
    A = "A"
    AE = "AE"
    VE = "VE"


class WindHailTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ScoreStage(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InspectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    BOUND = "BOUND"
    DECLINED = "DECLINED"


class DeclineReason(str, Enum):
    WILDFIRE_UNINSURABLE = "WILDFIRE_UNINSURABLE"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    NONE = "NONE"


class EndorsementKind(str, Enum):
    PERIL_ADD = "PERIL_ADD"
    EXCLUSION = "EXCLUSION"


class PerilCode(str, Enum):
    WATER_BACKUP = "WATER_BACKUP"
    SCREENED_ENCLOSURE = "SCREENED_ENCLOSURE"
    ORDINANCE_LAW = "ORDINANCE_LAW"
    EARTH_MOVEMENT = "EARTH_MOVEMENT"
    MOLD = "MOLD"


class EndorsementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    REMOVED = "REMOVED"


class QuoteStatus(str, Enum):
    BOUND_OFFER = "BOUND_OFFER"
    SUPERSEDED = "SUPERSEDED"


class PolicyStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    REINSTATED = "REINSTATED"
    CANCELLED = "CANCELLED"


class PaymentPurpose(str, Enum):
    BINDING = "BINDING"
    REINSTATEMENT = "REINSTATEMENT"


class PaymentStatus(str, Enum):
    SETTLED = "SETTLED"


# --- Entity TypedDicts (full common quartet unless noted) ---
class Property(TypedDict):
    id: str
    street_address: str
    state_code: str
    year_built: int
    square_footage: int
    construction_type: str
    roof_age_years: int
    stories: int
    replacement_cost: float
    total_insured_value: float
    estimate_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    property_id: str
    wildfire_fuel_density: int
    slope_grade_pct: int
    defensible_space_ft: int
    flood_zone: str
    distance_to_coast_mi: float
    wildfire_score: int
    wind_hail_tier: str
    score_stage: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    license_state: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    property_id: str
    inspector_id: str
    window_start: int
    window_end: int
    roof_ok: bool
    electrical_ok: bool
    plumbing_ok: bool
    hvac_ok: bool
    passed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    property_id: str
    agent_id: str
    requested_coverage_a: float
    wind_hail_deductible_pct: float
    quoted_premium: float
    decline_reason: str
    assigned_underwriter_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict):
    id: str
    application_id: str
    kind: str
    peril_code: str
    coverage_limit: float
    premium_delta: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    application_id: str
    base_premium: float
    endorsement_premium: float
    annual_premium: float
    wind_hail_deductible_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    application_id: str
    property_id: str
    effective_date: int
    expiration_date: int
    annual_premium: float
    premium_balance: float
    lapse_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    policy_id: str
    purpose: str
    amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Underwriter is immutable after creation: id + created_at only,
# NO updated_at, NO version.
class Underwriter(TypedDict):
    id: str
    full_name: str
    authority_limit: float
    created_at: str
