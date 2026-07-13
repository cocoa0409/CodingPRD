"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---- Role enum ----
class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    NUTRITIONIST = "Nutritionist"
    ROUTE_MANAGER = "RouteManager"
    PROGRAM_ADMIN = "ProgramAdmin"
    CONTRIBUTION_CLERK = "ContributionClerk"
    VOLUNTEER_DRIVER = "VolunteerDriver"


# ---- Status / band enums ----
class ClientStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSED = "ASSESSED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    DISCHARGED = "DISCHARGED"


class IncomeTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class NutritionRiskCategory(str, Enum):
    GOOD = "GOOD"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class FunctionalLevel(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    PARTIAL = "PARTIAL"
    DEPENDENT = "DEPENDENT"


class TherapeuticDietType(str, Enum):
    NONE = "NONE"
    RENAL = "RENAL"
    DIABETIC = "DIABETIC"
    LOW_SODIUM = "LOW_SODIUM"
    PUREED = "PUREED"


class MealType(str, Enum):
    FROZEN = "FROZEN"
    HOT = "HOT"
    THERAPEUTIC = "THERAPEUTIC"


class MealPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class DriverStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    NO_ANSWER = "NO_ANSWER"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class WellnessCheckOutcome(str, Enum):
    OK = "OK"
    NO_ANSWER = "NO_ANSWER"


class WelfareAlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class WelfareSeverity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class ContributionStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class VacationHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---- Weekday values used by routes / plans / deliveries ----
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


# ---- Entity TypedDicts ----
# Client carries id + created_at + updated_at + version (common fields).
class Client(TypedDict):
    id: str
    full_name: str
    birth_date: str
    household_size: int
    monthly_income_cents: int
    address_zone: str
    phone: str
    enrollment_status: str
    oaa_eligible: bool
    income_tier: str
    suggested_contribution_cents: int
    donation_balance_cents: int
    lifetime_oaa_units: int
    consecutive_no_answer: int
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    client_id: str
    nutrition_determine_points: int
    nutrition_risk_category: str
    adl_score: int
    functional_level: str
    therapeutic_diet_required: bool
    therapeutic_diet_type: str
    recommended_meals_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MealPlan(TypedDict):
    id: str
    client_id: str
    assessment_id: str
    route_id: str
    meal_type: str
    therapeutic_diet_type: str
    meals_per_day: int
    delivery_days: List[str]
    weekly_meal_count: int
    suggested_contribution_per_meal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    name: str
    zone: str
    service_days: List[str]
    driver_id: Optional[str]
    max_meals_per_run: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerDriver(TypedDict):
    id: str
    full_name: str
    phone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    meal_plan_id: str
    client_id: str
    route_id: str
    scheduled_date: str
    meal_type: str
    meal_count: int
    oaa_units_accrued: int
    status: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# WellnessCheck is common_fields:false — carries ONLY id + created_at
# (no updated_at, no version): it is an immutable event record.
class WellnessCheck(TypedDict):
    id: str
    delivery_id: str
    client_id: str
    outcome: str
    notes: Optional[str]
    created_at: str


class WelfareAlert(TypedDict):
    id: str
    client_id: str
    triggering_wellness_check_id: str
    severity: str
    status: str
    acknowledged_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict):
    id: str
    client_id: str
    amount_cents: int
    period_month: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VacationHold(TypedDict):
    id: str
    client_id: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
