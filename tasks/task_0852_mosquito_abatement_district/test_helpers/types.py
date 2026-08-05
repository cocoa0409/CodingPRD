"""Domain types for the Mosquito Abatement District API.

Entity TypedDicts, status enums and the role enum, as described in the PRD.
Entities that the PRD declares append-only (larval inspections and weather
observations) expose only ``id`` and ``created_at`` — never ``updated_at`` or
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum (PRD §2.1) ─────────────────────────────


class UserRole(str, Enum):
    DISTRICT_ADMIN = "DistrictAdmin"
    FIELD_TECH = "FieldTech"
    LAB_ANALYST = "LabAnalyst"
    VECTOR_ECOLOGIST = "VectorEcologist"
    ABATEMENT_MANAGER = "AbatementManager"
    SENSITIVE_SITE_OPERATOR = "SensitiveSiteOperator"
    RESIDENT = "Resident"


# ─── Enumerations ─────────────────────────────────────


class RiskPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    EMERGENCY = "EMERGENCY"


class PostureSource(str, Enum):
    NO_ASSESSMENT = "NO_ASSESSMENT"
    INDEX = "INDEX"
    POSITIVE_OVERRIDE = "POSITIVE_OVERRIDE"


class SiteType(str, Enum):
    APIARY = "APIARY"
    ORGANIC_FARM = "ORGANIC_FARM"
    AQUACULTURE = "AQUACULTURE"
    SCHOOL = "SCHOOL"


class TrapType(str, Enum):
    CDC_LIGHT = "CDC_LIGHT"
    GRAVID = "GRAVID"
    BG_SENTINEL = "BG_SENTINEL"


class TrapHabitat(str, Enum):
    URBAN = "URBAN"
    WETLAND = "WETLAND"
    AGRICULTURAL = "AGRICULTURAL"
    STORMWATER = "STORMWATER"


class LarvalHabitat(str, Enum):
    CATCH_BASIN = "CATCH_BASIN"
    DITCH = "DITCH"
    MARSH = "MARSH"
    CONTAINER = "CONTAINER"


class Species(str, Enum):
    CULEX_PIPIENS = "CULEX_PIPIENS"
    CULEX_TARSALIS = "CULEX_TARSALIS"
    AEDES_AEGYPTI = "AEDES_AEGYPTI"
    AEDES_ALBOPICTUS = "AEDES_ALBOPICTUS"
    OTHER = "OTHER"


class TrapCollectionStatus(str, Enum):
    LOGGED = "LOGGED"
    SUBMITTED = "SUBMITTED"
    POOLED = "POOLED"
    VOIDED = "VOIDED"


class LabPoolStatus(str, Enum):
    CREATED = "CREATED"
    IN_TESTING = "IN_TESTING"
    RESULT_POSITIVE = "RESULT_POSITIVE"
    RESULT_NEGATIVE = "RESULT_NEGATIVE"
    INVALID = "INVALID"
    DISCARDED = "DISCARDED"


class Assay(str, Enum):
    RT_PCR = "RT_PCR"
    VECTEST = "VECTEST"


class RiskAssessmentStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"


class StaleReason(str, Enum):
    LAB_RESULT = "LAB_RESULT"
    NEW_COLLECTION = "NEW_COLLECTION"


class ActiveIngredient(str, Enum):
    BTI = "BTI"
    METHOPRENE = "METHOPRENE"
    PERMETHRIN = "PERMETHRIN"
    MALATHION = "MALATHION"
    NALED = "NALED"


class ApplicationMethod(str, Enum):
    LARVICIDE = "LARVICIDE"
    ADULTICIDE = "ADULTICIDE"
    AERIAL = "AERIAL"


class LicenseCategory(str, Enum):
    LARVICIDE_ONLY = "LARVICIDE_ONLY"
    ADULTICIDE = "ADULTICIDE"
    AERIAL = "AERIAL"


class ApplicatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TreatmentRouteStatus(str, Enum):
    PLANNED = "PLANNED"
    COMMITTED = "COMMITTED"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"
    RELEASED = "RELEASED"


class NotificationStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    UNDELIVERABLE = "UNDELIVERABLE"


class NotificationChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    PHONE = "PHONE"


class RequestCategory(str, Enum):
    STANDING_WATER = "STANDING_WATER"
    ADULT_ACTIVITY = "ADULT_ACTIVITY"
    DEAD_BIRD = "DEAD_BIRD"
    SPRAY_CONCERN = "SPRAY_CONCERN"


class HandlingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    ASSIGNED = "ASSIGNED"
    INSPECTED = "INSPECTED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    FIELD_CONFIRMED = "FIELD_CONFIRMED"
    UNFOUNDED = "UNFOUNDED"


class RequestPriority(str, Enum):
    ROUTINE = "ROUTINE"
    PRIORITY = "PRIORITY"
    URGENT = "URGENT"


# ─── Entity shapes ────────────────────────────────────
# Entities carrying id + created_at + updated_at + version.


class ServiceArea(TypedDict):
    id: str
    name: str
    code: str
    season_start_date: str
    population: int
    risk_posture: str
    posture_source: str
    latest_confirmed_vector_index: float
    seasonal_application_count: int
    request_total_count: int
    request_open_count: int
    request_resolved_count: int
    request_closed_count: int
    created_at: str
    updated_at: str
    version: int


class SensitiveSite(TypedDict):
    id: str
    service_area_id: str
    site_type: str
    operator_name: str
    contact_email: str
    x_m: int
    y_m: int
    buffer_meters_override: Optional[int]
    buffer_meters: int
    registered_on: str
    created_at: str
    updated_at: str
    version: int


class TrapSite(TypedDict):
    id: str
    service_area_id: str
    site_code: str
    trap_type: str
    habitat: str
    x_m: int
    y_m: int
    is_active: bool
    season_positive_count: int
    last_positive_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrapCollection(TypedDict):
    id: str
    trap_site_id: str
    recorded_by_applicator_id: str
    collection_date: str
    trap_nights: int
    female_count: int
    species: str
    status: str
    pooled_mosquito_count: int
    positive_pool_count: int
    wnv_detected: bool
    created_at: str
    updated_at: str
    version: int


class LabPool(TypedDict):
    id: str
    trap_collection_id: str
    pool_size: int
    assay: str
    status: str
    retest_count: int
    ct_value: Optional[float]
    result_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    service_area_id: str
    as_of_date: str
    status: str
    is_stale: bool
    stale_reason: Optional[str]
    abundance_index: float
    larval_index: float
    degree_days: float
    mir_provisional: float
    mir_confirmed: Optional[float]
    vector_index_provisional: float
    vector_index_confirmed: Optional[float]
    posture_at_confirm: Optional[str]
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PesticideProduct(TypedDict):
    id: str
    name: str
    epa_reg_no: str
    active_ingredient: str
    application_method: str
    label_rate_ml_per_acre: float
    reentry_interval_hours: int
    cost_cents_per_liter: int
    restricted_use: bool
    received_total_ml: float
    on_hand_ml: float
    committed_ml: float
    applied_ml: float
    created_at: str
    updated_at: str
    version: int


class Applicator(TypedDict):
    id: str
    full_name: str
    license_no: str
    license_category: str
    license_expires_on: str
    status: str
    assigned_route_count: int
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    service_area_id: str
    trigger_assessment_id: str
    treatment_type: str
    status: str
    required_approvals: int
    submitted_by_user_id: Optional[str]
    approver_user_ids: List[str]
    notification_required: bool
    revision_count: int
    scheduled_start_at: Optional[str]
    estimated_total_ml: float
    material_cost_cents: int
    labor_cost_cents: int
    subtotal_cents: int
    admin_fee_rate: float
    admin_fee_cents: int
    total_cost_cents: int
    completed_at: Optional[str]
    cancel_reason: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TreatmentRoute(TypedDict):
    id: str
    treatment_plan_id: str
    applicator_id: str
    pesticide_product_id: str
    route_code: str
    window_start: str
    window_end: str
    planned_acres: float
    center_x_m: int
    center_y_m: int
    swath_radius_m: int
    status: str
    duration_minutes: int
    estimated_volume_ml: float
    actual_acres: Optional[float]
    wind_speed_mph: Optional[float]
    actual_volume_ml: Optional[float]
    executed_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict):
    id: str
    treatment_plan_id: str
    sensitive_site_id: str
    channel: str
    status: str
    attempt_count: int
    sent_at: Optional[str]
    acknowledged_at: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    service_area_id: str
    assigned_applicator_id: Optional[str]
    reporter_contact: str
    category: str
    description: str
    x_m: int
    y_m: int
    reported_by_user_id: str
    handling_status: str
    verification_status: str
    priority: str
    triaged_at: Optional[str]
    due_at: Optional[str]
    resolved_at: Optional[str]
    reopen_count: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only evidence records: id + created_at only, no updated_at, no version.


class LarvalInspection(TypedDict):
    id: str
    service_area_id: str
    inspection_date: str
    dips: int
    larvae_count: int
    habitat: str
    treated_on_site: bool
    created_at: str


class WeatherObservation(TypedDict):
    id: str
    service_area_id: str
    obs_date: str
    tmax_c: float
    tmin_c: float
    rainfall_mm: float
    degree_day: float
    created_at: str
