"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Meal Kit Subscription PRD. All eight resources carry the full
common audit set (id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class SelectionStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SKIPPED = "SKIPPED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    CHARGED = "CHARGED"
    SHIPPED = "SHIPPED"
    REFUNDED = "REFUNDED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    VOID = "VOID"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class DietPreference(str, Enum):
    STANDARD = "STANDARD"
    VEGETARIAN = "VEGETARIAN"
    PESCATARIAN = "PESCATARIAN"
    LOW_CARB = "LOW_CARB"
    FAMILY_FRIENDLY = "FAMILY_FRIENDLY"


class ZoneCode(str, Enum):
    ZONE_A = "ZONE_A"
    ZONE_B = "ZONE_B"
    ZONE_C = "ZONE_C"
    ZONE_D = "ZONE_D"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    PLATFORM_OPS = "PlatformOps"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts (all common_fields: true) ──────────────────────────

class Plan(TypedDict):
    id: str
    code: str
    servings_per_meal: int
    meals_per_week: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class ShippingZone(TypedDict):
    id: str
    zone_code: str
    cold_pack_surcharge_cents: int
    cutoff_weekday: int
    serviceable: bool
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict):
    id: str
    title: str
    is_premium: bool
    contains_allergens: List[str]
    diet_tags: List[str]
    is_available: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    shipping_zone_id: str
    referred_by_member_id: Optional[str]
    referral_code: str
    credit_balance_cents: int
    lifetime_box_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    plan_id: str
    diet_preference: str
    blocked_allergens: List[str]
    monthly_addon_fee_cents: int
    billing_cycle_day: int
    scheduled_resume_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WeeklyBox(TypedDict):
    id: str
    subscription_id: str
    delivery_date: str
    cutoff_at: str
    provisional_charge_cents: int
    final_charge_cents: Optional[int]
    selection_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class BoxRecipe(TypedDict):
    id: str
    box_id: str
    recipe_id: str
    is_premium_snapshot: bool
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referrer_member_id: str
    referee_member_id: str
    reward_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
