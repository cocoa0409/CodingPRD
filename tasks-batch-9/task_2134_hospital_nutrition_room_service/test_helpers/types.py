"""Domain types for the Hospital Nutrition Room Service API.

Entity shapes, status enumerations and the role enumeration, all drawn from the
PRD. Satisfaction surveys are append-only events and therefore carry only
``id`` and ``created_at`` -- no ``updated_at`` and no ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --- Role enumeration (PRD 2.1) ---------------------------------------------

class UserRole(str, Enum):
    PHYSICIAN = "Physician"
    DIETITIAN = "Dietitian"
    DIET_CLERK = "DietClerk"
    TRAY_AIDE = "TrayAide"
    NUTRITION_MANAGER = "NutritionManager"


# --- Ordinal ladders (PRD 3.4) ----------------------------------------------

class TextureLevel(str, Enum):
    REGULAR = "REGULAR"
    MINCED_MOIST = "MINCED_MOIST"
    PUREED = "PUREED"
    LIQUIDISED = "LIQUIDISED"


class LiquidLevel(str, Enum):
    THIN = "THIN"
    MILDLY_THICK = "MILDLY_THICK"
    MODERATELY_THICK = "MODERATELY_THICK"
    EXTREMELY_THICK = "EXTREMELY_THICK"


# --- Status enumerations -----------------------------------------------------

class WardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PatientStatus(str, Enum):
    ADMITTED = "ADMITTED"
    DISCHARGED = "DISCHARGED"


class NpoStatus(str, Enum):
    NONE = "NONE"
    NPO_STRICT = "NPO_STRICT"
    NPO_CLEAR_LIQUIDS = "NPO_CLEAR_LIQUIDS"


class DietRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DietOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_COSIGN = "PENDING_COSIGN"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DISCONTINUED = "DISCONTINUED"


class MealPeriodStatus(str, Enum):
    PLANNED = "PLANNED"
    FORECAST_LOCKED = "FORECAST_LOCKED"
    IN_SERVICE = "IN_SERVICE"
    CLOSED = "CLOSED"


class PeriodCode(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"
    LATE_SNACK = "LATE_SNACK"


class ForecastVariant(str, Enum):
    ROLLING_AVERAGE = "ROLLING_AVERAGE"
    CENSUS_BASED = "CENSUS_BASED"


class MenuItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ServiceTempClass(str, Enum):
    HOT = "HOT"
    COLD = "COLD"
    AMBIENT = "AMBIENT"


class FulfillmentStatus(str, Enum):
    PENDING_VALIDATION = "PENDING_VALIDATION"
    VALIDATED = "VALIDATED"
    IN_PRODUCTION = "IN_PRODUCTION"
    PLATED = "PLATED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    MISSED = "MISSED"


class QaStatus(str, Enum):
    NOT_CHECKED = "NOT_CHECKED"
    ACCURACY_PASSED = "ACCURACY_PASSED"
    ACCURACY_FAILED = "ACCURACY_FAILED"
    TEMP_PASSED = "TEMP_PASSED"
    TEMP_FAILED = "TEMP_FAILED"


class MissedReason(str, Enum):
    NPO_HOLD = "NPO_HOLD"
    PERIOD_CLOSED = "PERIOD_CLOSED"


class DeliveryWindowCompliance(str, Enum):
    EARLY = "EARLY"
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class LineStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUBSTITUTED = "SUBSTITUTED"


class ProcedureHoldStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class NpoKind(str, Enum):
    NPO_STRICT = "NPO_STRICT"
    NPO_CLEAR_LIQUIDS = "NPO_CLEAR_LIQUIDS"


class ConsultStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    ASSESSED = "ASSESSED"
    SIGNED = "SIGNED"
    CANCELLED = "CANCELLED"


class ConsultAcuity(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class AssessmentVariant(str, Enum):
    SCREENING = "SCREENING"
    COMPREHENSIVE = "COMPREHENSIVE"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class SupplementOrderStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


# --- Entity shapes -----------------------------------------------------------

class Ward(TypedDict):
    id: str
    name: str
    code: str
    tray_line_capacity_per_window: int
    delivery_lead_minutes: int
    temperature_probe_required: bool
    status: str
    active_patient_census: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    ward_id: str
    mrn: str
    full_name: str
    age_years: int
    allergen_codes: List[str]
    texture_level: str
    liquid_level: str
    status: str
    npo_status: str
    active_procedure_hold_id: Optional[str]
    active_diet_order_id: Optional[str]
    missed_meal_count: int
    protein_deficit_g: float
    daily_supplement_cost_cents: int
    survey_count: int
    satisfaction_score_avg: Optional[float]
    created_at: str
    updated_at: str
    version: int


class TherapeuticDietRule(TypedDict):
    id: str
    diet_code: str
    display_name: str
    max_sodium_mg_per_meal: Optional[int]
    max_potassium_mg_per_meal: Optional[int]
    max_carb_g_per_meal: Optional[float]
    min_texture_level: Optional[str]
    min_liquid_level: Optional[str]
    forbidden_tag_codes: List[str]
    requires_dietitian_cosign: bool
    precedence_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DietOrder(TypedDict):
    id: str
    patient_id: str
    primary_diet_rule_id: str
    secondary_diet_rule_id: Optional[str]
    supersedes_diet_order_id: Optional[str]
    superseded_by_diet_order_id: Optional[str]
    ordering_physician_user_id: str
    cosigned_by_user_id: Optional[str]
    texture_level: str
    liquid_level: str
    status: str
    revision_round: int
    revision_note: Optional[str]
    effective_from: Optional[str]
    effective_sodium_cap_mg: Optional[int]
    effective_potassium_cap_mg: Optional[int]
    effective_carb_cap_g: Optional[float]
    effective_texture_level: Optional[str]
    effective_liquid_level: Optional[str]
    forbidden_tag_codes_effective: List[str]
    linked_meal_order_count: int
    created_at: str
    updated_at: str
    version: int


class MealPeriod(TypedDict):
    id: str
    ward_id: str
    period_code: str
    service_date: str
    order_cutoff_at: str
    window_start_at: str
    window_end_at: str
    production_capacity_trays: int
    cost_ceiling_cents: Optional[int]
    status: str
    forecast_variant: Optional[str]
    forecast_tray_count: Optional[int]
    forecast_cost_cents: Optional[int]
    forecast_variance_pct: Optional[float]
    locked_at: Optional[str]
    committed_tray_count: int
    committed_food_cost_cents: int
    delivered_tray_count: int
    period_overhead_cents: int
    period_bulk_discount_cents: int
    period_total_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    item_code: str
    display_name: str
    sodium_mg: int
    potassium_mg: int
    carb_g: float
    protein_g: float
    unit_cost_cents: int
    texture_level: str
    liquid_level: Optional[str]
    service_temp_class: str
    allergen_codes: List[str]
    tag_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MealOrder(TypedDict):
    id: str
    patient_id: str
    meal_period_id: str
    diet_order_id: str
    pinned_diet_order_version: int
    placed_by_user_id: str
    fulfillment_status: str
    qa_status: str
    revalidation_required: bool
    effective_texture_level: Optional[str]
    effective_liquid_level: Optional[str]
    total_sodium_mg: int
    total_potassium_mg: int
    total_carb_g: float
    total_protein_g: float
    food_cost_cents: int
    requires_hot_probe: bool
    requires_cold_probe: bool
    hot_probe_celsius: Optional[float]
    cold_probe_celsius: Optional[float]
    accuracy_retry_count: int
    temperature_retry_count: int
    accuracy_checked_by_user_id: Optional[str]
    temperature_checked_by_user_id: Optional[str]
    delivered_at: Optional[str]
    delivery_window_compliance: Optional[str]
    service_compliance_score: Optional[int]
    missed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MealOrderLine(TypedDict):
    id: str
    meal_order_id: str
    menu_item_id: str
    substituted_from_menu_item_id: Optional[str]
    quantity: int
    line_status: str
    substitution_reason: Optional[str]
    line_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class ProcedureHold(TypedDict):
    id: str
    patient_id: str
    procedure_code: str
    npo_kind: str
    hold_start_at: str
    hold_end_at: str
    buffer_before_minutes: int
    buffer_after_minutes: int
    buffered_start_at: str
    buffered_end_at: str
    status: str
    requested_by_user_id: str
    released_at: Optional[str]
    missed_meal_order_count: int
    created_at: str
    updated_at: str
    version: int


class NutritionConsult(TypedDict):
    id: str
    patient_id: str
    acuity: str
    reason_code: str
    requested_by_user_id: str
    assigned_dietitian_user_id: Optional[str]
    auto_generated: bool
    status: str
    assessment_variant: Optional[str]
    weight_loss_pct: Optional[float]
    intake_pct: Optional[float]
    bmi: Optional[float]
    albumin_g_dl: Optional[float]
    malnutrition_risk_score: Optional[float]
    risk_tier: Optional[str]
    recommended_supplement_item_id: Optional[str]
    signed_by_user_id: Optional[str]
    due_at: str
    is_overdue: bool
    linked_supplement_order_count: int
    created_at: str
    updated_at: str
    version: int


class SupplementOrder(TypedDict):
    id: str
    consult_id: str
    patient_id: str
    menu_item_id: str
    doses_per_day: int
    status: str
    daily_cost_cents: int
    ordered_by_user_id: str
    activated_at: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SatisfactionSurvey(TypedDict):
    """Immutable append-only event: id and created_at only, no updated_at/version."""
    id: str
    meal_order_id: str
    patient_id: str
    taste_score: int
    temperature_score: int
    accuracy_score: int
    comment: Optional[str]
    composite_score: float
    created_at: str
