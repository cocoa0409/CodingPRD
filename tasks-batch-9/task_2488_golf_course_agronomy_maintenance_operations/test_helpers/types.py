"""Vocabularies and record shapes the golf-course agronomy contract declares.

Every member is spelled exactly as the PRD spells it, because the API compares
these strings verbatim.  The two record shapes that carry only `id` and
`created_at` — pesticide products and playability readings (PRD §2.4) —
deliberately omit `updated_at` and `version`.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The five roles of PRD §2.1, whose "spellings are exact"."""

    SUPERINTENDENT = "Superintendent"
    AGRONOMIST = "Agronomist"
    APPLICATOR = "Applicator"
    TOURNAMENT_OFFICIAL = "TournamentOfficial"
    EQUIPMENT_TECHNICIAN = "EquipmentTechnician"


ALL_ROLES = [role.value for role in UserRole]


# --------------------------------------------------------------------------
# Course postures (PRD §2.10)
# --------------------------------------------------------------------------
class WaterPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class PlayPosture(str, Enum):
    OPEN = "OPEN"
    FROST_DELAY = "FROST_DELAY"
    CART_PATH_ONLY = "CART_PATH_ONLY"
    CLOSED = "CLOSED"


# --------------------------------------------------------------------------
# Turf areas (PRD §3.2)
# --------------------------------------------------------------------------
class AreaType(str, Enum):
    GREEN = "GREEN"
    TEE = "TEE"
    FAIRWAY = "FAIRWAY"
    ROUGH = "ROUGH"
    APPROACH = "APPROACH"
    PRACTICE_GREEN = "PRACTICE_GREEN"


class SoilType(str, Enum):
    SAND_USGA = "SAND_USGA"
    NATIVE_LOAM = "NATIVE_LOAM"
    PUSH_UP_CLAY = "PUSH_UP_CLAY"


class AgronomicStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_RENOVATION = "UNDER_RENOVATION"
    OUT_OF_PLAY = "OUT_OF_PLAY"


# --------------------------------------------------------------------------
# Plans and plan tasks (PRD §3.3)
# --------------------------------------------------------------------------
class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class PlanTaskType(str, Enum):
    FERTILITY = "FERTILITY"
    AERATION = "AERATION"
    TOPDRESSING = "TOPDRESSING"
    PEST_CONTROL = "PEST_CONTROL"


class PlanTaskStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Licensing, labels and application records (PRD §3.4)
# --------------------------------------------------------------------------
class LicenseCategory(str, Enum):
    CAT_3_TURF = "CAT_3_TURF"
    CAT_7_AQUATIC = "CAT_7_AQUATIC"
    CAT_3_AND_7 = "CAT_3_AND_7"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class RecordStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class PostingStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    POSTED = "POSTED"
    RELEASED = "RELEASED"


class VoidReason(str, Enum):
    DATA_ENTRY_ERROR = "DATA_ENTRY_ERROR"
    SAFETY_VIOLATION = "SAFETY_VIOLATION"


# --------------------------------------------------------------------------
# Irrigation (PRD §3.5)
# --------------------------------------------------------------------------
class SourceType(str, Enum):
    WELL = "WELL"
    POND = "POND"
    RECLAIMED = "RECLAIMED"


class PumpStationStatus(str, Enum):
    ONLINE = "ONLINE"
    RESTRICTED = "RESTRICTED"
    OFFLINE = "OFFLINE"


class IrrigationRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Crew windows (PRD §3.6)
# --------------------------------------------------------------------------
class WindowTaskType(str, Enum):
    FERTILITY = "FERTILITY"
    AERATION = "AERATION"
    TOPDRESSING = "TOPDRESSING"
    PEST_CONTROL = "PEST_CONTROL"
    MOWING = "MOWING"
    STORM_CLEANUP = "STORM_CLEANUP"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEFERRED = "DEFERRED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Play events and readiness (PRD §3.7)
# --------------------------------------------------------------------------
class PlayEventType(str, Enum):
    STANDARD_TEE_TIMES = "STANDARD_TEE_TIMES"
    SHOTGUN_START = "SHOTGUN_START"
    TOURNAMENT_ROUND = "TOURNAMENT_ROUND"


class PlayEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    CANCELLED = "CANCELLED"


class ReadinessStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


# --------------------------------------------------------------------------
# The fleet (PRD §3.8)
# --------------------------------------------------------------------------
class UnitType(str, Enum):
    TRIPLEX_GREENS_MOWER = "TRIPLEX_GREENS_MOWER"
    FAIRWAY_MOWER = "FAIRWAY_MOWER"
    SPRAYER = "SPRAYER"
    AERATOR = "AERATOR"
    TOPDRESSER = "TOPDRESSER"


class EquipmentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    DOWN_FOR_SERVICE = "DOWN_FOR_SERVICE"
    RETIRED = "RETIRED"


# --------------------------------------------------------------------------
# Weather (PRD §3.9)
# --------------------------------------------------------------------------
class WeatherEventType(str, Enum):
    FROST = "FROST"
    LIGHTNING = "LIGHTNING"
    HEAVY_RAIN = "HEAVY_RAIN"
    STORM_DAMAGE = "STORM_DAMAGE"


class WeatherEventStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"


# --------------------------------------------------------------------------
# The water assessment tiers (PRD §3.1)
# --------------------------------------------------------------------------
class AssessmentTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


# ==========================================================================
# Record shapes
# ==========================================================================
class VersionedRecord(TypedDict):
    """The audit fields carried by every resource except products and readings."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableRecord(TypedDict):
    """"Two resource types are exceptions and carry only `id` and `created_at`"."""

    id: str
    created_at: str


class Course(VersionedRecord):
    name: str
    region_code: str
    annual_water_allocation_gal: float
    water_restricted_threshold_pct: float
    water_suspended_threshold_pct: float
    water_used_gal: float
    water_posture: str
    play_posture: str
    frost_delay_minutes: int


class TurfArea(VersionedRecord):
    course_id: str
    area_type: str
    hole_number: Optional[int]
    area_sq_ft: float
    mowing_height_mm: float
    distance_to_water_ft: float
    soil_type: str
    target_moisture_pct: float
    current_moisture_pct: Optional[float]
    agronomic_status: str
    nitrogen_applied_lb_per_1000_ytd: float
    nitrogen_projected_lb_per_1000: float
    rei_expires_at: Optional[str]


class AgronomicPlan(VersionedRecord):
    course_id: str
    plan_year: int
    nitrogen_budget_lb: float
    committed_nitrogen_lb: float
    status: str
    return_count: int
    submitted_by_user_id: Optional[str]


class PlanTask(VersionedRecord):
    plan_id: str
    turf_area_id: str
    task_type: str
    nitrogen_lb_per_1000: Optional[float]
    commitment_lb: float
    planned_window_start: str
    planned_window_end: str
    status: str


class Applicator(VersionedRecord):
    full_name: str
    license_number: str
    license_category: str
    license_expires_on: str
    license_status: str
    suspended_at: Optional[str]


class PesticideProduct(ImmutableRecord):
    trade_name: str
    epa_reg_no: str
    requires_license_category: str
    rei_hours: int
    min_buffer_ft: float
    max_wind_speed_mph: float
    posting_required: bool
    nitrogen_pct: float


class Application(VersionedRecord):
    turf_area_id: str
    product_id: str
    applicator_id: str
    plan_task_id: Optional[str]
    applied_at: str
    rate_lb_per_acre: float
    wind_speed_mph: float
    distance_to_water_ft: float
    total_lb: float
    nitrogen_lb: float
    rei_expires_at: Optional[str]
    record_status: str
    posting_status: str
    verified_by_applicator_id: Optional[str]
    void_reason: Optional[str]


class PumpStation(VersionedRecord):
    course_id: str
    source_type: str
    max_flow_gpm: float
    max_concurrent_zones: int
    daily_withdrawal_cap_gal: float
    withdrawn_today_gal: float
    status: str


class IrrigationRun(VersionedRecord):
    pump_station_id: str
    turf_area_id: str
    window_start: str
    window_end: str
    target_moisture_deficit_pct: float
    allotted_gal: float
    flow_gpm: float
    volume_gal: float
    status: str


class MaintenanceWindow(VersionedRecord):
    course_id: str
    turf_area_id: str
    plan_task_id: Optional[str]
    task_type: str
    window_start: str
    window_end: str
    crew_size: int
    required_unit_type: Optional[str]
    crew_hours: float
    status: str
    deferral_count: int


class PlayEvent(VersionedRecord):
    course_id: str
    event_type: str
    start_at: str
    end_at: str
    holes_in_play: int
    field_size: int
    delayed_minutes: int
    effective_start_at: str
    readiness_index: Optional[float]
    readiness_status: str
    status: str


class EquipmentUnit(VersionedRecord):
    course_id: str
    replaced_by_unit_id: Optional[str]
    unit_type: str
    model_year: int
    purchase_cost: float
    expected_life_hours: float
    service_interval_hours: float
    avg_daily_hours: float
    initial_engine_hours: float
    engine_hours: float
    hours_since_service: float
    engine_hours_at_last_service: float
    replacement_score: float
    replacement_score_projected: float
    replacement_flag: bool
    status: str


class PlayabilityReading(ImmutableRecord):
    turf_area_id: str
    measured_at: str
    green_speed_ft: float
    firmness_gravities: float
    moisture_pct: float
    within_tournament_spec: bool


class WeatherEvent(VersionedRecord):
    course_id: str
    event_type: str
    delay_minutes: int
    expected_clear_at: str
    affected_turf_area_ids: List[str]
    declared_at: str
    cleared_at: Optional[str]
    deferred_window_count: int
    status: str


class WaterAssessment(TypedDict):
    """The computed read of PRD §3.1 — "it returns no entity"."""

    billable_gal: float
    base_charge: float
    tier: str
    surcharge_rate: float
    surcharge: float
    total_charge: float
