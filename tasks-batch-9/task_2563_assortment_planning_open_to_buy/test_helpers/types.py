"""Domain types for the Assortment Planning & Open-to-Buy API.

Entity shapes, status enums and the role enum, exactly as the PRD declares them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    MERCH_OPS_ADMIN = "MerchOpsAdmin"
    MERCHANDISE_PLANNER = "MerchandisePlanner"
    PLANNING_DIRECTOR = "PlanningDirector"
    CATEGORY_BUYER = "CategoryBuyer"
    VENDOR_REP = "VendorRep"


class CategoryRole(str, Enum):
    TRAFFIC_DRIVER = "TRAFFIC_DRIVER"
    DESTINATION = "DESTINATION"
    CONVENIENCE = "CONVENIENCE"
    SEASONAL = "SEASONAL"
    OCCASIONAL = "OCCASIONAL"


class ClimateZone(str, Enum):
    COLD = "COLD"
    TEMPERATE = "TEMPERATE"
    HOT = "HOT"


class VolumeTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class VendorStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"


class VendorAuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class SeasonCode(str, Enum):
    SPRING = "SPRING"
    SUMMER = "SUMMER"
    FALL = "FALL"
    HOLIDAY = "HOLIDAY"


class CategoryPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REFORECAST_OPEN = "REFORECAST_OPEN"
    CLOSED = "CLOSED"


class OtbPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class VarianceStatus(str, Enum):
    ON_PLAN = "ON_PLAN"
    WATCH = "WATCH"
    BREACH = "BREACH"


class PlanMonthStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED_PLAN = "LOCKED_PLAN"
    IN_SEASON = "IN_SEASON"
    CLOSED = "CLOSED"


class ActiveBasis(str, Enum):
    PLANNED_BASIS = "PLANNED_BASIS"
    PROJECTED_BASIS = "PROJECTED_BASIS"


class OptionPlanStatus(str, Enum):
    OPEN = "OPEN"
    SLOTTED = "SLOTTED"
    CLOSED = "CLOSED"


class Tier(str, Enum):
    GOOD = "GOOD"
    BETTER = "BETTER"
    BEST = "BEST"


class LifecycleStage(str, Enum):
    NEW = "NEW"
    CARRYOVER = "CARRYOVER"
    CORE = "CORE"
    EXIT = "EXIT"


class AssortmentItemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DEFERRED = "DEFERRED"
    ADOPTED = "ADOPTED"
    IN_SEASON = "IN_SEASON"
    CHASED = "CHASED"
    CANCELLED_IN_SEASON = "CANCELLED_IN_SEASON"
    CLOSED = "CLOSED"


class SellThroughBasis(str, Enum):
    NEW_ITEM_BASIS = "NEW_ITEM_BASIS"
    CARRYOVER_BASIS = "CARRYOVER_BASIS"


class CommitStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class FulfillmentStatus(str, Enum):
    AWAITING_SHIP = "AWAITING_SHIP"
    SHIPPED = "SHIPPED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    VOID = "VOID"


class CommitmentOrigin(str, Enum):
    BUYER = "BUYER"
    CHASE_DECISION = "CHASE_DECISION"


class ReforecastCycleStatus(str, Enum):
    OPEN = "OPEN"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class TriggerReason(str, Enum):
    VARIANCE_BREACH = "VARIANCE_BREACH"
    DIRECTOR_REQUEST = "DIRECTOR_REQUEST"


class DecisionAction(str, Enum):
    CHASE = "CHASE"
    CANCEL = "CANCEL"
    HOLD = "HOLD"


class DecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OverlayType(str, Enum):
    CLIMATE = "CLIMATE"
    DEMOGRAPHIC = "DEMOGRAPHIC"
    VOLUME = "VOLUME"


class OverlayStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


# ─── Entity shapes ────────────────────────────────────
# Governed rows carry id, created_at, updated_at and version.
# Append-only records (size-curve cell, weekly actuals post) carry ONLY
# id and created_at.


class Department(TypedDict):
    id: str
    name: str
    code: str
    fiscal_year: int
    sales_target_cents: int
    margin_target_bps: int
    turn_target_x100: int
    created_at: str
    updated_at: str
    version: int


class Category(TypedDict):
    id: str
    department_id: str
    name: str
    code: str
    role: str
    sales_share_bps: int
    created_at: str
    updated_at: str
    version: int


class StoreCluster(TypedDict):
    id: str
    name: str
    climate_zone: str
    demographic_index_bps: int
    volume_tier: str
    store_count: int
    sales_index_bps: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    code: str
    status: str
    lead_time_days: int
    weekly_unit_capacity: int
    min_order_units: int
    cancel_cutoff_days: int
    created_at: str
    updated_at: str
    version: int


class VendorAuthorization(TypedDict):
    id: str
    vendor_id: str
    category_id: str
    max_open_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CategoryPlan(TypedDict):
    id: str
    category_id: str
    season_code: str
    fiscal_year: int
    planned_sales_cents: int
    planned_margin_bps: int
    planned_turn_x100: int
    status: str
    reforecast_round: int
    receipt_budget_cents: Optional[int]
    otb_posture: str
    variance_status: str
    sales_variance_bps: int
    open_ratio_bps: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanMonth(TypedDict):
    id: str
    category_plan_id: str
    month_index: int
    fiscal_month_label: str
    first_receipt_date: str
    bom_inventory_cents: int
    planned_sales_cents: int
    planned_markdown_cents: int
    planned_eom_cents: int
    status: str
    active_basis: str
    provisional_sell_through_bps: int
    reserve_rate_bps: int
    markdown_reserve_cents: int
    otb_planned_cents: int
    otb_committed_cents: int
    otb_received_cents: int
    otb_open_cents: int
    created_at: str
    updated_at: str
    version: int


class OptionPlan(TypedDict):
    id: str
    category_plan_id: str
    store_cluster_id: str
    tier: str
    breadth_target: int
    depth_units_per_option: int
    assumed_unit_cost_cents: int
    status: str
    option_slots_total: Optional[int]
    option_slots_assigned: int
    option_slots_open: Optional[int]
    target_units_per_option: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SizeCurveCell(TypedDict):
    # Append-only: no updated_at, no version.
    id: str
    option_plan_id: str
    size_label: str
    size_sort_order: int
    pct_bps: int
    raw_units_x10000: int
    allocated_units: int
    created_at: str


class AssortmentItem(TypedDict):
    id: str
    option_plan_id: str
    vendor_id: str
    sku_code: str
    color_code: str
    lifecycle_stage: str
    unit_cost_cents: int
    retail_price_cents: int
    prior_season_sell_through_bps: int
    status: str
    sell_through_basis: Optional[str]
    sell_through_bps: Optional[int]
    effective_overlay_multiplier_bps: int
    planned_units: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ReceiptCommitment(TypedDict):
    id: str
    plan_month_id: str
    assortment_item_id: str
    vendor_id: str
    units: int
    unit_cost_cents: int
    ship_window_start: str
    ship_window_end: str
    origin: str
    commit_status: str
    fulfillment_status: str
    received_units: int
    cancelled_units: int
    cost_cents: int
    open_cost_cents: int
    received_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class ActualsPost(TypedDict):
    # Append-only: no updated_at, no version.
    id: str
    plan_month_id: str
    week_index: int
    actual_sales_cents: int
    actual_receipts_cents: int
    actual_units_received: int
    created_at: str


class ReforecastCycle(TypedDict):
    id: str
    category_plan_id: str
    round_index: int
    trigger_reason: str
    opened_at_utc: str
    snapshot_sales_variance_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChaseCancelDecision(TypedDict):
    id: str
    reforecast_cycle_id: str
    assortment_item_id: str
    action: str
    requested_units: int
    rationale: str
    proposed_by_user_id: str
    approved_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LocalizationOverlay(TypedDict):
    id: str
    category_plan_id: str
    store_cluster_id: str
    overlay_type: str
    effective_start: str
    effective_end: str
    unit_multiplier_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int
