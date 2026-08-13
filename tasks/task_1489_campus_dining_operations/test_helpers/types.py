"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class DiningHallStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServiceModel(str, Enum):
    BOARD = "BOARD"
    RETAIL = "RETAIL"
    HYBRID = "HYBRID"


class VendorContractStatus(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class MenuCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class RecipeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Station(str, Enum):
    GRILL = "GRILL"
    DELI = "DELI"
    PIZZA = "PIZZA"
    SALAD = "SALAD"
    GLOBAL = "GLOBAL"
    BAKERY = "BAKERY"


class Allergen(str, Enum):
    MILK = "MILK"
    EGG = "EGG"
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    SOY = "SOY"
    WHEAT = "WHEAT"
    FISH = "FISH"
    SHELLFISH = "SHELLFISH"
    SESAME = "SESAME"


class DietaryFlag(str, Enum):
    VEGAN = "VEGAN"
    VEGETARIAN = "VEGETARIAN"
    HALAL = "HALAL"
    KOSHER = "KOSHER"
    GLUTEN_FREE = "GLUTEN_FREE"


class MealPeriod(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"
    LATE_NIGHT = "LATE_NIGHT"


class MealPeriodStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FORECAST_LOCKED = "FORECAST_LOCKED"
    IN_SERVICE = "IN_SERVICE"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EntryType(str, Enum):
    BOARD_SWIPE = "BOARD_SWIPE"
    RETAIL_SALE = "RETAIL_SALE"


class ForecastVariant(str, Enum):
    BASE = "BASE"
    TREND = "TREND"


class ForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class AccommodationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    NUTRITION_REVIEW = "NUTRITION_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class DietaryRequirement(str, Enum):
    VEGAN = "VEGAN"
    VEGETARIAN = "VEGETARIAN"
    HALAL = "HALAL"
    KOSHER = "KOSHER"
    GLUTEN_FREE = "GLUTEN_FREE"
    OTHER = "OTHER"


class LaborRole(str, Enum):
    COOK = "COOK"
    SERVER = "SERVER"
    CASHIER = "CASHIER"
    DISHWASHER = "DISHWASHER"


class LaborShiftStatus(str, Enum):
    PLANNED = "PLANNED"
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class WasteCategory(str, Enum):
    PRE_CONSUMER = "PRE_CONSUMER"
    POST_CONSUMER = "POST_CONSUMER"
    SPOILAGE = "SPOILAGE"


class WasteDisposition(str, Enum):
    LANDFILL = "LANDFILL"
    COMPOST = "COMPOST"
    DONATION = "DONATION"


class WasteLogStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    POSTED = "POSTED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLOSED = "CLOSED"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"


class TimeSlot(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"


class ApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    NONE = "NONE"
    SCHEDULED = "SCHEDULED"
    FULFILLED = "FULFILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class CommissionStatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"


class UserRole(str, Enum):
    DINING_ADMIN = "DiningAdmin"
    HALL_MANAGER = "HallManager"
    KITCHEN_LEAD = "KitchenLead"
    DIETITIAN = "Dietitian"
    HEALTH_INSPECTOR = "HealthInspector"
    CONTRACT_MANAGER = "ContractManager"
    DEPARTMENT_USER = "DepartmentUser"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class DiningHall(TypedDict):
    id: str
    name: str
    service_model: str
    dining_capacity: int
    catering_kitchen_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorContract(TypedDict):
    id: str
    dining_hall_id: str
    vendor_name: str
    board_rate_per_cover_cents: int
    retail_commission_bps: int
    catering_commission_bps: int
    minimum_monthly_guarantee_cents: int
    effective_start_date: str
    effective_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuCycle(TypedDict):
    id: str
    dining_hall_id: str
    name: str
    cycle_length_weeks: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict):
    id: str
    dining_hall_id: str
    name: str
    station: str
    allergen_tags: List[str]
    dietary_flags: List[str]
    popularity_share: float
    unit_cost_cents: int
    allergen_reviewed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MealPeriodService(TypedDict):
    id: str
    dining_hall_id: str
    menu_cycle_id: str
    service_date: str
    meal_period: str
    status: str
    forecasted_covers: int
    actual_board_swipes: int
    actual_retail_sales_cents: int
    actual_covers: int
    forecast_variance_pct: Optional[float]
    posted_waste_kg: float
    landfill_waste_kg: float
    diversion_rate: Optional[float]
    sustainability_alert: bool
    created_at: str
    updated_at: str
    version: int


# Append-only ingestion record: carries ONLY id + created_at from the common
# set; updated_at and version are absent.
class SwipeEvent(TypedDict):
    id: str
    meal_period_id: str
    entry_type: str
    amount_cents: int
    recorded_at: str
    created_at: str


class ProductionForecast(TypedDict):
    id: str
    meal_period_id: str
    recipe_id: str
    variant: str
    forecasted_portions: int
    base_covers: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccommodationRequest(TypedDict):
    id: str
    dining_hall_id: str
    student_ref: str
    allergen_exclusions: List[str]
    dietary_requirement: str
    review_notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LaborShift(TypedDict):
    id: str
    dining_hall_id: str
    staff_ref: Optional[str]
    role: str
    shift_date: str
    start_minute: int
    end_minute: int
    hourly_rate_cents: int
    status: str
    worked_minutes: Optional[int]
    regular_minutes: int
    overtime_minutes: int
    regular_pay_cents: int
    overtime_pay_cents: int
    created_at: str
    updated_at: str
    version: int


class WasteLog(TypedDict):
    id: str
    meal_period_id: str
    category: str
    disposition: str
    weight_kg: float
    recorded_by_user_id: str
    verified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionReport(TypedDict):
    id: str
    dining_hall_id: str
    inspector_user_id: str
    inspection_date: str
    violations: List[Dict[str, Any]]
    score: Optional[int]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict):
    id: str
    inspection_report_id: str
    violation_code: str
    severity: str
    due_date: str
    status: str
    resolved_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict):
    id: str
    name: str
    department_code: str
    semester_budget_cents: int
    reserved_cents: int
    committed_cents: int
    spent_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class CateringOrder(TypedDict):
    id: str
    dining_hall_id: str
    department_id: str
    revised_from_id: Optional[str]
    event_date: str
    time_slot: str
    guaranteed_covers: int
    menu_lines: List[Dict[str, Any]]
    dietary_plates: int
    quoted_total_cents: int
    final_total_cents: Optional[int]
    cancellation_fee_cents: int
    approval_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict):
    id: str
    vendor_contract_id: str
    period_month: str
    status: str
    board_revenue_cents: int
    retail_commission_cents: int
    catering_commission_cents: int
    guarantee_top_up_cents: int
    total_due_to_university_cents: int
    provisional_total_due_cents: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
