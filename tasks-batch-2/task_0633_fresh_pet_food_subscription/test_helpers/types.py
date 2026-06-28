"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD's Fresh Pet-Food Subscription resource definitions exactly.
WeightLog is the sole append-only resource: it carries only ``id`` and ``created_at`` (no
``updated_at``, no ``version``); every other resource carries the full common-field set.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# --------------------------------------------------------------------------- #
# Roles                                                                        #
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PET_PARENT = "PetParent"
    NUTRITION_VET = "NutritionVet"
    BILLING_ADMIN = "BillingAdmin"
    FULFILLMENT_OPS = "FulfillmentOps"
    ANONYMOUS = "Anonymous"


# --------------------------------------------------------------------------- #
# Status enums                                                                 #
# --------------------------------------------------------------------------- #
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class WeightLogStatus(str, Enum):
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"


class OrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SKIPPED = "SKIPPED"
    CHARGING = "CHARGING"
    PAID = "PAID"
    FAILED = "FAILED"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    SPOILED = "SPOILED"


class ReferralCreditStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class Beneficiary(str, Enum):
    REFERRER = "REFERRER"
    REFERRED = "REFERRED"


class CreditReason(str, Enum):
    SIGNUP = "SIGNUP"
    MAKE_GOOD = "MAKE_GOOD"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"


# --------------------------------------------------------------------------- #
# Entity TypedDicts — common_fields: true                                      #
# --------------------------------------------------------------------------- #
class Account(TypedDict):
    id: str
    email: str
    full_name: str
    country_code: str
    referral_code: str
    referred_by_account_id: Optional[str]
    wallet_credit_cents: int
    lifetime_referral_grants_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pet(TypedDict):
    id: str
    account_id: str
    name: str
    species: str
    sex: str
    birth_date: str
    current_weight_kg: float
    initial_weight_kg: float
    ideal_weight_kg: float
    activity_level: str
    neutered: bool
    body_condition_goal: str
    allergen_exclusions: List[str]
    daily_calorie_target: float
    life_stage: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict):
    id: str
    name: str
    species: str
    kcal_per_gram: float
    price_per_100g_cents: int
    ingredient_allergens: List[str]
    availability_regions: List[str]
    vet_formulated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    account_id: str
    pet_id: str
    recipe_id: str
    cadence_days: int
    pack_grams_per_day: float
    pack_total_grams: float
    cycle_price_cents: int
    transition_remaining_cycles: int
    pending_resize_grams_per_day: Optional[float]
    resize_effective_at: Optional[str]
    pause_until: Optional[str]
    next_order_date: str
    consecutive_failed_charges: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    subscription_id: str
    account_id: str
    cycle_index: int
    scheduled_ship_date: str
    food_grams: float
    is_transition_cycle: bool
    food_subtotal_cents: int
    credit_applied_cents: int
    shipping_cents: int
    total_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    coolant_packs: int
    transit_days: int
    dispatched_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReferralCredit(TypedDict):
    id: str
    referrer_account_id: str
    referred_account_id: str
    amount_cents: int
    beneficiary: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Entity TypedDicts — common_fields: false (append-only)                       #
# --------------------------------------------------------------------------- #
class WeightLog(TypedDict):
    id: str
    pet_id: str
    weight_kg: float
    effective_date: str
    status: str
    created_at: str
    # No updated_at, no version — WeightLog is immutable after creation.
