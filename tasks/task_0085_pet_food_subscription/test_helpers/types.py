"""Domain types for the Pet Food Subscription API.

Entity TypedDicts, status enums, and role enum. Mutable entities carry
id + created_at + updated_at + version; append-only / immutable-catalog
entities carry only id + created_at (no updated_at, no version) per
PRD §2.4.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    ADMIN_OPS = "AdminOps"
    PAYMENT_ADAPTER = "PaymentAdapter"
    LOGISTICS_ADAPTER = "LogisticsAdapter"
    VET_ADAPTER = "VetAdapter"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"


class ActivityLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class LifeStage(str, Enum):
    PUPPY_KITTEN = "PUPPY_KITTEN"
    ADULT = "ADULT"
    SENIOR = "SENIOR"


class PetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VET_HOLD = "VET_HOLD"
    ARCHIVED = "ARCHIVED"


class Frequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    REACTIVATING = "REACTIVATING"


class CancelReason(str, Enum):
    PRICE = "PRICE"
    QUALITY = "QUALITY"
    PET_NO_LONGER = "PET_NO_LONGER"
    OTHER = "OTHER"


class TargetLifeStage(str, Enum):
    PUPPY_KITTEN = "PUPPY_KITTEN"
    ADULT = "ADULT"
    SENIOR = "SENIOR"
    ALL = "ALL"


class RecipeRecommendationStatus(str, Enum):
    PENDING = "PENDING"
    FROZEN = "FROZEN"
    SUPERSEDED = "SUPERSEDED"


class WarehouseStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class FulfillmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    SKIPPED = "SKIPPED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SuggestionType(str, Enum):
    ROTATE_PROTEIN = "ROTATE_PROTEIN"
    INCREASE_PORTION = "INCREASE_PORTION"
    DECREASE_PORTION = "DECREASE_PORTION"
    SWAP_RECIPE_FAMILY = "SWAP_RECIPE_FAMILY"
    VET_ESCALATE = "VET_ESCALATE"


class AdjustmentStatus(str, Enum):
    SUGGESTED = "SUGGESTED"
    APPLIED = "APPLIED"
    DISMISSED = "DISMISSED"
    VET_PENDING = "VET_PENDING"
    VET_APPROVED = "VET_APPROVED"
    VET_REJECTED = "VET_REJECTED"


class AuditEventType(str, Enum):
    PLAN_MODIFIED = "PLAN_MODIFIED"
    SKIPPED = "SKIPPED"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"
    CANCELLED = "CANCELLED"
    REACTIVATED = "REACTIVATED"
    ADJUSTMENT_APPLIED = "ADJUSTMENT_APPLIED"
    ADJUSTMENT_DISMISSED = "ADJUSTMENT_DISMISSED"
    VET_ESCALATED = "VET_ESCALATED"


class PaymentEventType(str, Enum):
    PAYMENT_CAPTURED = "PAYMENT_CAPTURED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYMENT_REFUNDED = "PAYMENT_REFUNDED"


class LogisticsEventType(str, Enum):
    SHIPMENT_DISPATCHED = "SHIPMENT_DISPATCHED"
    DELIVERY_CONFIRMED = "DELIVERY_CONFIRMED"


class VetEventType(str, Enum):
    VET_APPROVED = "VET_APPROVED"
    VET_REJECTED = "VET_REJECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Mutable (PRD §2.4): id, created_at, updated_at, version
# Append-only / immutable-catalog: id, created_at only
# ---------------------------------------------------------------------------
class Address(TypedDict, total=False):
    line1: str
    line2: Optional[str]
    city: str
    region: str
    postal_code: str
    country: str
    verified: bool


class Customer(TypedDict, total=False):
    id: str
    email: str
    display_name: str
    default_shipping_address: Address
    total_charged_cents: int
    total_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class Pet(TypedDict, total=False):
    id: str
    customer_id: str
    name: str
    species: str
    breed: str
    birthdate: str
    weight_kg: float
    activity_level: str
    allergies: List[str]
    intolerances: List[str]
    dietary_preferences: List[str]
    dietary_aversions: List[str]
    health_conditions: List[str]
    life_stage: str
    photo_gallery: List[dict]
    status: str
    adjustment_history: List[dict]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    customer_id: str
    pet_ids: List[str]
    frequency: str
    cycle_days: int
    shipping_address: Address
    is_trial: bool
    status: str
    paused_until: Optional[str]
    cancel_reason: Optional[str]
    retention_offer_applied: bool
    scheduled_order_count: int
    skipped_count: int
    total_cycles_elapsed: int
    modification_deadline_hours: int
    next_cycle_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Recipe is an immutable catalog row (PRD §2.4): id + created_at only.
class Recipe(TypedDict, total=False):
    id: str
    code: str
    target_species: str
    target_life_stage: str
    protein_sources: List[str]
    grain_sources: List[str]
    supplement_sources: List[str]
    kcal_per_gram: float
    unit_price_cents_per_100g: int
    vet_prescribed: bool
    prescribed_for: List[str]
    monotony_class: str
    trial_eligible: bool
    created_at: str


class RecipeRecommendation(TypedDict, total=False):
    id: str
    subscription_id: str
    pet_id: str
    cycle_index: int
    recipe_id: str
    match_score: float
    explanation: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict, total=False):
    id: str
    code: str
    serves_regions: List[str]
    priority_rank: int
    daily_outbound_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    warehouse_id: str
    recipe_id: str
    batch_code: str
    expiration_date: str
    quantity_grams: int
    created_at: str
    updated_at: str
    version: int


class OrderItem(TypedDict, total=False):
    pet_id: str
    recipe_id: str
    portion_grams_per_day: int
    total_grams: int
    unit_price_cents: int
    line_total_cents: int


class AssignedLot(TypedDict, total=False):
    item_index: int
    lot_id: str
    batch_code: str
    expiration_date: str
    grams_drawn: int


class Order(TypedDict, total=False):
    id: str
    subscription_id: str
    customer_id: str
    cycle_index: int
    scheduled_ship_at: str
    items: List[OrderItem]
    warehouse_id: Optional[str]
    assigned_lots: List[AssignedLot]
    subtotal_cents: int
    shipping_fee_cents: int
    total_cents: int
    payment_status: str
    fulfillment_status: str
    tracking_number: Optional[str]
    shipping_address_snapshot: Address
    is_trial_pack: bool
    created_at: str
    updated_at: str
    version: int


class ShipmentFeedback(TypedDict, total=False):
    id: str
    order_id: str
    pet_id: str
    palatability: int
    stool_quality: int
    coat_condition: int
    weight_change_grams: int
    notes: Optional[str]
    adverse_flag: bool
    created_at: str
    updated_at: str
    version: int


class RecipeAdjustment(TypedDict, total=False):
    id: str
    pet_id: str
    subscription_id: str
    based_on_feedback_ids: List[str]
    suggestion_type: str
    target_recipe_id: Optional[str]
    portion_delta_pct: Optional[int]
    status: str
    applied_at: Optional[str]
    rationale: List[str]
    created_at: str
    updated_at: str
    version: int


# AuditLog is an append-only event log (PRD §2.4): id + created_at only.
class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    entity_type: str
    entity_id: str
    event_type: str
    before: dict
    after: dict
    ts: str
    created_at: str


__all__ = [
    "UserRole",
    "Species",
    "ActivityLevel",
    "LifeStage",
    "PetStatus",
    "Frequency",
    "SubscriptionStatus",
    "CancelReason",
    "TargetLifeStage",
    "RecipeRecommendationStatus",
    "WarehouseStatus",
    "PaymentStatus",
    "FulfillmentStatus",
    "SuggestionType",
    "AdjustmentStatus",
    "AuditEventType",
    "PaymentEventType",
    "LogisticsEventType",
    "VetEventType",
    "Address",
    "Customer",
    "Pet",
    "Subscription",
    "Recipe",
    "RecipeRecommendation",
    "Warehouse",
    "InventoryLot",
    "OrderItem",
    "AssignedLot",
    "Order",
    "ShipmentFeedback",
    "RecipeAdjustment",
    "AuditLog",
]
