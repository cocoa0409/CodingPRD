"""Domain types: entity TypedDicts, status enums, role enum.

Derived strictly from the PRD's entity definitions. Entities that carry the
standard system-managed set (id, created_at, updated_at, version) are modelled
with all four; the two append-only records (RecipeComponent, TempLog) carry
only id and created_at, per PRD section 2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PlanTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class StationClass(str, Enum):
    PREP_TABLE = "PREP_TABLE"
    CONVECTION_OVEN = "CONVECTION_OVEN"
    BLAST_CHILLER = "BLAST_CHILLER"


class StationStatus(str, Enum):
    OPEN = "OPEN"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class TempClass(str, Enum):
    DRY = "DRY"
    COLD = "COLD"
    FROZEN = "FROZEN"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    EXCURSION = "EXCURSION"
    QUARANTINED = "QUARANTINED"


class StorageAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ProductionBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    SCRAPPED = "SCRAPPED"


class IngredientOrderStatus(str, Enum):
    PLACED = "PLACED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class EventPackoutStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    SHIPPED = "SHIPPED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"


class UserRole(str, Enum):
    Anonymous = "Anonymous"
    MemberOperator = "MemberOperator"
    FacilityManager = "FacilityManager"
    ComplianceOfficer = "ComplianceOfficer"


# ─── Entity TypedDicts (standard fields: id/created_at/updated_at/version) ──

class Member(TypedDict):
    id: str
    business_name: str
    email: str
    plan_tier: str
    status: str
    wallet_balance_cents: int
    lifetime_loaded_cents: int
    lifetime_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    name: str
    station_class: str
    turnover_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    member_id: str
    station_id: str
    start_utc: str
    end_utc: str
    is_peak: bool
    turnover_applied: bool
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageUnit(TypedDict):
    id: str
    name: str
    temp_class: str
    total_slots: int
    used_slots: int
    temp_min_c: float
    temp_max_c: float
    compliance_status: str
    excursion_minutes: int
    created_at: str
    updated_at: str
    version: int


class StorageAssignment(TypedDict):
    id: str
    member_id: str
    storage_unit_id: str
    temp_class: str
    requested_slots: int
    allocation_plan: list
    monthly_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict):
    id: str
    name: str
    unit_cost_cents: int
    on_hand_qty: float
    allergen_tags: list
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict):
    id: str
    member_id: str
    name: str
    version: int
    batch_yield_units: int
    allergen_tags: list
    estimated_food_cost_cents: int
    status: str
    created_at: str
    updated_at: str


class ProductionBatch(TypedDict):
    id: str
    member_id: str
    recipe_id: str
    recipe_version_pinned: int
    planned_yield_units: int
    actual_yield_units: Optional[int]
    estimated_food_cost_cents: int
    actual_food_cost_cents: Optional[int]
    production_fee_cents: Optional[int]
    actual_components: list
    status: str
    created_at: str
    updated_at: str
    version: int


class IngredientOrder(TypedDict):
    id: str
    member_id: str
    ingredient_id: str
    order_qty: float
    unit_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventPackout(TypedDict):
    id: str
    member_id: str
    event_name: str
    batch_ids: list
    allergen_free_required: list
    combined_allergen_tags: list
    packed_unit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    member_id: str
    period_start_utc: str
    period_end_utc: str
    booking_subtotal_cents: int
    storage_subtotal_cents: int
    production_subtotal_cents: int
    subtotal_cents: int
    loyalty_discount_cents: int
    platform_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only records: id + created_at only (no updated_at, no version) ──

class RecipeComponent(TypedDict):
    id: str
    recipe_id: str
    ingredient_id: str
    planned_qty: float
    created_at: str


class TempLog(TypedDict):
    id: str
    storage_unit_id: str
    reading_c: float
    reading_utc: str
    in_range: bool
    certified: bool
    created_at: str
