"""Domain types for the Convenience-Store Foodservice Program API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them.  Entities that the PRD describes as append-only evidence carry only
``id`` and ``created_at`` - they deliberately omit ``updated_at`` and
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────

class UserRole(str, Enum):
    CHAIN_ADMIN = "ChainAdmin"
    STORE_MANAGER = "StoreManager"
    KITCHEN_ASSOCIATE = "KitchenAssociate"
    SHIFT_LEAD = "ShiftLead"
    FOOD_SAFETY_LEAD = "FoodSafetyLead"
    STORE_TERMINAL = "StoreTerminal"
    CUSTOMER = "Customer"


# ─── Enumerated vocabularies ──────────────────────────────────────────

class Daypart(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"
    OVERNIGHT = "OVERNIGHT"


class UnitType(str, Enum):
    HOT_CASE = "HOT_CASE"
    COLD_CASE = "COLD_CASE"
    BAKERY_CASE = "BAKERY_CASE"


class HoldingUnitStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    IMPAIRED = "IMPAIRED"
    LOCKED_OUT = "LOCKED_OUT"


class Station(str, Enum):
    SANDWICH = "SANDWICH"
    BEVERAGE = "BEVERAGE"
    HOT_FOOD = "HOT_FOOD"
    BAKERY = "BAKERY"


class TargetStation(str, Enum):
    SANDWICH = "SANDWICH"
    BEVERAGE = "BEVERAGE"
    HOT_FOOD = "HOT_FOOD"
    BAKERY = "BAKERY"
    ALL = "ALL"


class FulfillmentMode(str, Enum):
    MADE_TO_ORDER = "MADE_TO_ORDER"
    PAR_BAKED_CASE = "PAR_BAKED_CASE"


class ModifierClass(str, Enum):
    BREAD = "BREAD"
    PROTEIN = "PROTEIN"
    CHEESE = "CHEESE"
    TOPPING = "TOPPING"
    PREP = "PREP"
    SIZE = "SIZE"


class PromotionKind(str, Enum):
    FUEL_FOOD_COMBO = "FUEL_FOOD_COMBO"
    DAYPART_BUNDLE = "DAYPART_BUNDLE"


class DiscountKind(str, Enum):
    PCT_PER_LINE = "PCT_PER_LINE"
    CENTS_OFF = "CENTS_OFF"


class PromotionRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoyaltyTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    ELITE = "ELITE"


class StaffingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class ProductionBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    BAKING = "BAKING"
    HOLDING = "HOLDING"
    SOLD_OUT = "SOLD_OUT"
    DISCARDED = "DISCARDED"


class WasteReason(str, Enum):
    HOLD_EXPIRED = "HOLD_EXPIRED"
    QUALITY_REJECT = "QUALITY_REJECT"
    UNIT_IMPAIRED = "UNIT_IMPAIRED"
    DAYPART_TRANSITION = "DAYPART_TRANSITION"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"


class OrderChannel(str, Enum):
    TOUCHSCREEN = "TOUCHSCREEN"
    MOBILE_PREORDER = "MOBILE_PREORDER"
    CATERING = "CATERING"


class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    IN_PRODUCTION = "IN_PRODUCTION"
    ASSEMBLED = "ASSEMBLED"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    RELEASED = "RELEASED"


class TenderType(str, Enum):
    CARD = "CARD"
    CASH = "CASH"
    APP_WALLET = "APP_WALLET"


class KitchenTicketStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    VOIDED = "VOIDED"


class ReadinessStatus(str, Enum):
    READY = "READY"
    AT_RISK = "AT_RISK"
    NOT_READY = "NOT_READY"


# ─── Entities that carry the full common field set ────────────────────
# (id, created_at, updated_at, version)

class Store(TypedDict):
    id: str
    store_code: str
    name: str
    hot_case_slot_capacity: int
    pickup_slot_capacity: int
    is_fuel_site: bool
    current_daypart: str
    daypart_epoch: int
    hot_case_slots_used: int
    waste_cost_cents_mtd: int
    rework_waste_cents_mtd: int
    created_at: str
    updated_at: str
    version: int


class HoldingUnit(TypedDict):
    id: str
    store_id: str
    unit_code: str
    unit_type: str
    min_temp_f: int
    max_temp_f: int
    slot_count: int
    status: str
    consecutive_out_of_range_count: int
    last_temp_log_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    sku: str
    name: str
    station: str
    fulfillment_mode: str
    base_price_cents: int
    unit_food_cost_cents: int
    valid_dayparts: List[str]
    prep_seconds: int
    bake_minutes: int
    hold_minutes: int
    included_premium_count: int
    is_catering_eligible: bool
    created_at: str
    updated_at: str
    version: int


class PromotionRule(TypedDict):
    id: str
    code: str
    kind: str
    discount_kind: str
    discount_bp: int
    discount_cents: int
    max_discount_cents: int
    min_food_subtotal_cents: int
    requires_fuel_gallons: float
    target_station: str
    valid_dayparts: List[str]
    stacking_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict):
    id: str
    member_code: str
    email: str
    points_balance: int
    lifetime_points_earned: int
    lifetime_points_redeemed: int
    points_reversed_total: int
    tier: str
    created_at: str
    updated_at: str
    version: int


class StaffingPlan(TypedDict):
    id: str
    store_id: str
    service_date: str
    daypart: str
    forecast_txn_count: int
    mto_share_bp: int
    peak_multiplier_bp: int
    planned_labor_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict):
    id: str
    store_id: str
    menu_item_id: str
    holding_unit_id: str
    slot_index: int
    planned_qty: int
    bake_start_at: str
    occupancy_end_at: str
    baked_qty: int
    remaining_qty: int
    reserved_qty: int
    sold_qty: int
    discarded_qty: int
    hold_started_at: Optional[str]
    hold_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict):
    id: str
    temperature_log_id: str
    action_taken: str
    status: str
    opened_by_user_id: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    store_id: str
    channel: str
    loyalty_account_id: Optional[str]
    pickup_window_start: Optional[str]
    pickup_window_end: Optional[str]
    production_status: str
    settlement_status: str
    subtotal_gross_cents: int
    promo_discount_cents: int
    service_fee_cents: int
    total_cents: int
    points_provisional: int
    points_final: Optional[int]
    rework_count: int
    daypart_at_placement: Optional[str]
    applied_promotion_id: Optional[str]
    expected_ready_at: Optional[str]
    placed_at: Optional[str]
    ready_at: Optional[str]
    tender_type: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    menu_item_id: str
    qty: int
    station: str
    unit_price_cents: int
    premium_surcharge_cents: int
    line_gross_cents: int
    line_discount_cents: int
    line_net_cents: int
    reserved_qty: int
    fulfillment_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KitchenTicket(TypedDict):
    id: str
    order_id: str
    store_id: str
    station: str
    status: str
    prep_seconds: int
    lead_seconds: int
    sequence_position: int
    promised_ready_at: str
    started_by_user_id: Optional[str]
    completed_by_user_id: Optional[str]
    rework_count: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only evidence: ONLY id + created_at ───────────────────────
# The PRD states that updated_at and version are absent from these
# representations, so these TypedDicts must not list them.

class ModifierOption(TypedDict):
    id: str
    menu_item_id: str
    code: str
    modifier_class: str
    price_delta_cents: int
    is_premium: bool
    max_qty: int
    created_at: str


class FuelTransaction(TypedDict):
    id: str
    loyalty_account_id: str
    gallons: float
    price_per_gallon_cents: int
    fuel_spend_cents: int
    occurred_at: str
    created_at: str


class WasteLog(TypedDict):
    id: str
    production_batch_id: str
    qty: int
    reason: str
    food_cost_cents: int
    retail_value_cents: int
    logged_by_user_id: str
    daypart_epoch: int
    created_at: str


class TemperatureLog(TypedDict):
    id: str
    holding_unit_id: str
    reading_f: int
    in_range: bool
    logged_by_user_id: str
    recorded_at: str
    created_at: str


# ─── Computed read (nothing persisted) ────────────────────────────────

class StoreReadiness(TypedDict):
    temp_log_compliance_pct: int
    units_impaired_count: int
    units_locked_out_count: int
    open_corrective_actions_count: int
    food_cost_waste_cents_mtd: int
    retail_waste_exposure_cents: int
    readiness_status: str


APPEND_ONLY_ENTITIES = (
    "ModifierOption",
    "FuelTransaction",
    "WasteLog",
    "TemperatureLog",
)
