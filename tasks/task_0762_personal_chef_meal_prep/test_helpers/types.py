"""Domain types: entity TypedDicts, status enums, role enum.

All eight entities carry the common system-managed fields id, created_at,
updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT = "Client"
    CHEF = "Chef"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ChefStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DietaryPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class WeeklyMenuStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SKIPPED = "SKIPPED"
    COOKED = "COOKED"
    CANCELLED = "CANCELLED"


class MenuMealStatus(str, Enum):
    PLANNED = "PLANNED"
    COOKED = "COOKED"
    CANCELLED = "CANCELLED"


class CookSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ContainerStatus(str, Enum):
    FILLED = "FILLED"


class BillingInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"


class BillingMode(str, Enum):
    PER_WEEK = "PER_WEEK"
    PER_MEAL = "PER_MEAL"


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    household_size: int
    billing_mode: str
    weekly_base_fee_cents: int
    per_meal_fee_cents: int
    weekly_grocery_budget_cents: int
    available_equipment: List[str]
    kitchen_open_hour: int
    kitchen_close_hour: int
    wallet_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Chef(TypedDict):
    id: str
    full_name: str
    email: str
    hourly_rate_cents: int
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DietaryPlan(TypedDict):
    id: str
    client_id: str
    restriction_tags: List[str]
    allergen_tags: List[str]
    daily_calorie_target: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeeklyMenu(TypedDict):
    id: str
    client_id: str
    dietary_plan_id: str
    chef_id: str
    week_start_date: str
    grocery_cost_cents: int
    pinned_plan_version: Optional[int]
    billing_mode_snapshot: Optional[str]
    markup_pct_snapshot: Optional[int]
    billed_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuMeal(TypedDict):
    id: str
    weekly_menu_id: str
    meal_name: str
    meal_slot: str
    servings: int
    is_perishable: bool
    required_equipment: List[str]
    ingredients: List[dict]
    meal_grocery_cost_cents: int
    client_rating: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CookSession(TypedDict):
    id: str
    weekly_menu_id: str
    chef_id: str
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    provisional_payout_cents: int
    final_payout_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict):
    id: str
    menu_meal_id: str
    label_prep_date: str
    label_use_by_date: str
    portion_count: int
    label_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingInvoice(TypedDict):
    id: str
    client_id: str
    weekly_menu_id: str
    billing_mode: str
    gross_amount_cents: int
    credit_applied_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
