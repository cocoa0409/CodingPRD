"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this system exposes the full common-field set
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MENU_PLANNER = "MenuPlanner"
    NUTRITION_DIRECTOR = "NutritionDirector"
    CAFETERIA_MANAGER = "CafeteriaManager"
    POS_CLERK = "POSClerk"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class MealType(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"


class GradeGroup(str, Enum):
    GRADES_K_5 = "GRADES_K_5"
    GRADES_6_8 = "GRADES_6_8"
    GRADES_9_12 = "GRADES_9_12"


class FoodCategory(str, Enum):
    ENTREE = "ENTREE"
    GRAIN = "GRAIN"
    FRUIT = "FRUIT"
    VEGETABLE = "VEGETABLE"
    MILK = "MILK"
    SNACK = "SNACK"
    BEVERAGE = "BEVERAGE"


class ComponentType(str, Enum):
    MEAT_MEAT_ALT = "MEAT_MEAT_ALT"
    GRAINS = "GRAINS"
    FRUIT = "FRUIT"
    VEGETABLE = "VEGETABLE"
    MILK = "MILK"


class InventoryUnit(str, Enum):
    EACH = "EACH"
    OZ = "OZ"
    CASE = "CASE"


class Program(str, Enum):
    NSLP = "NSLP"
    SBP = "SBP"


class EligibilityCategory(str, Enum):
    FREE = "FREE"
    REDUCED = "REDUCED"
    PAID = "PAID"


class MenuCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"


class LotType(str, Enum):
    COMMODITY_USDA_FOODS = "COMMODITY_USDA_FOODS"
    PURCHASED = "PURCHASED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class ProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    PREPARED = "PREPARED"
    CANCELLED = "CANCELLED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LOW_BALANCE = "LOW_BALANCE"
    NEGATIVE = "NEGATIVE"


class MealClaimStatus(str, Enum):
    REIMBURSABLE = "REIMBURSABLE"
    NON_REIMBURSABLE = "NON_REIMBURSABLE"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    PAID = "PAID"
    CHARGED = "CHARGED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry the full common-field set)
# --------------------------------------------------------------------------
class SchoolSite(TypedDict, total=False):
    id: str
    name: str
    site_code: str
    nslp_participating: bool
    sbp_participating: bool
    severe_need_breakfast: bool
    performance_based_certified: bool
    negative_balance_allowed: bool
    sales_tax_bps: int
    paid_lunch_price_cents: int
    paid_breakfast_price_cents: int
    reduced_lunch_copay_cents: int
    reduced_breakfast_copay_cents: int
    negative_balance_count: int
    created_at: str
    updated_at: str
    version: int


class FoodItem(TypedDict, total=False):
    id: str
    name: str
    category: str
    is_commodity: bool
    calories: int
    sat_fat_g: float
    total_fat_g: float
    sodium_mg: int
    total_sugar_g: float
    weight_g: float
    meat_alt_oz_eq: float
    grain_oz_eq: float
    fruit_cup: float
    veg_cup: float
    is_whole_grain_rich: bool
    unit: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementRate(TypedDict, total=False):
    id: str
    program: str
    category: str
    severe_need: bool
    rate_cents: int
    performance_addon_cents: int
    effective_date: str
    created_at: str
    updated_at: str
    version: int


class MenuCycle(TypedDict, total=False):
    id: str
    site_id: str
    meal_type: str
    grade_group: str
    effective_date: str
    end_date: str
    components: List[dict]
    status: str
    compliance_status: str
    submitted_by_user_id: Optional[str]
    rejection_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    site_id: str
    food_item_id: str
    lot_type: str
    quantity_received: float
    quantity_on_hand: float
    unit_cost_cents: int
    received_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRecord(TypedDict, total=False):
    id: str
    site_id: str
    menu_cycle_id: str
    service_date: str
    meal_type: str
    planned_qty: float
    forecast_par_qty: float
    prepared_qty: float
    served_qty: int
    leftover_qty: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    site_id: str
    first_name: str
    last_name: str
    grade: str
    eligibility_category: str
    balance_cents: int
    low_balance_threshold_cents: int
    account_status: str
    created_at: str
    updated_at: str
    version: int


class MealTransaction(TypedDict, total=False):
    id: str
    site_id: str
    student_id: str
    production_record_id: str
    service_date: str
    meal_type: str
    selected_components: List[str]
    claim_category: str
    meal_claim_status: str
    a_la_carte_lines: List[dict]
    alacarte_total_cents: int
    meal_charge_cents: int
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict, total=False):
    id: str
    site_id: str
    claim_month: str
    status: str
    free_count: int
    reduced_count: int
    paid_count: int
    estimated_reimbursement_cents: int
    final_reimbursement_cents: Optional[int]
    created_by_user_id: str
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
