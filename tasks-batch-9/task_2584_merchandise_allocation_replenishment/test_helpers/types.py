"""Domain types for the merchandise allocation and replenishment API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  AllocationProgram, Store, FixturePlan, Item, StorePosition,
Receipt, AllocationRun, AllocationLine, PromoEvent, TransferRecommendation and
AssortmentAction carry ``id``, ``created_at``, ``updated_at`` and ``version``.
SizeProfile and PerformanceSnapshot are append-only: they carry only ``id`` and
``created_at`` and therefore expose neither ``updated_at`` nor ``version``.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLANNING_ADMIN = "PlanningAdmin"
    ALLOCATOR = "Allocator"
    ALLOCATION_MANAGER = "AllocationManager"
    STORE_OPERATOR = "StoreOperator"


class ProgramStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMODEL = "REMODEL"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class ReceiptStatus(str, Enum):
    STAGED = "STAGED"
    ALLOCATING = "ALLOCATING"
    ALLOCATED = "ALLOCATED"
    CLOSED = "CLOSED"


class RunStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class LineFulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"


class StockStatus(str, Enum):
    STOCKOUT = "STOCKOUT"
    LOW = "LOW"
    IN_STOCK = "IN_STOCK"
    OVERSTOCK = "OVERSTOCK"


class AssortmentStatus(str, Enum):
    EXITED = "EXITED"
    COMPLETE = "COMPLETE"
    SIZE_OUT_RISK = "SIZE_OUT_RISK"
    BROKEN = "BROKEN"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class ItemLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    SIZE_OUT_WATCH = "SIZE_OUT_WATCH"
    BROKEN = "BROKEN"
    CONSOLIDATION_PENDING = "CONSOLIDATION_PENDING"
    MARKDOWN = "MARKDOWN"


class PromoEventStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class AssortmentActionStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class ItemClass(str, Enum):
    APPAREL_TOP = "APPAREL_TOP"
    APPAREL_BOTTOM = "APPAREL_BOTTOM"
    FOOTWEAR = "FOOTWEAR"
    ACCESSORY = "ACCESSORY"


class ItemType(str, Enum):
    BASIC = "BASIC"
    SEASONAL = "SEASONAL"
    FASHION = "FASHION"


class ReplenishmentModel(str, Enum):
    MIN_MAX = "MIN_MAX"
    DEMAND_DRIVEN = "DEMAND_DRIVEN"
    PUSH = "PUSH"


class AllocationMethod(str, Enum):
    MIN_MAX_TOPUP = "MIN_MAX_TOPUP"
    DEMAND_DRIVEN = "DEMAND_DRIVEN"
    PUSH_SIZE_PROFILE = "PUSH_SIZE_PROFILE"


class NeedBasis(str, Enum):
    FORWARD_LOOKING = "FORWARD_LOOKING"
    HISTORICAL_SELL_THROUGH = "HISTORICAL_SELL_THROUGH"


class ScorecardBasis(str, Enum):
    SIMPLE_AVERAGE = "SIMPLE_AVERAGE"
    UNIT_WEIGHTED = "UNIT_WEIGHTED"


class PromoScope(str, Enum):
    PROGRAM = "PROGRAM"
    CLUSTER = "CLUSTER"
    STORE = "STORE"


class StoreGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class TransferSourceReason(str, Enum):
    REBALANCE = "REBALANCE"
    CONSOLIDATION = "CONSOLIDATION"


class AssortmentTriggerReason(str, Enum):
    SIZE_OUT = "SIZE_OUT"
    BROKEN_ASSORTMENT = "BROKEN_ASSORTMENT"


class AssortmentActionType(str, Enum):
    CONSOLIDATION = "CONSOLIDATION"
    MARKDOWN = "MARKDOWN"


class SizeQuantity(TypedDict):
    size_code: str
    units: int


class SizeCurveEntry(TypedDict):
    size_code: str
    share_bp: int


class AllocationProgram(TypedDict):
    id: str
    name: str
    season_code: str
    banner_code: str
    status: str
    transfer_min_ratio_bp: int
    scorecard_basis: str
    total_units_received: int
    total_units_committed: int
    open_reserve_units: int
    locked_at: Optional[str]
    lock_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    program_id: str
    store_code: str
    grade: str
    grade_index_bp: int
    cluster_code: str
    status: str
    freight_flat_usd: float
    historical_sell_through_bp: int
    created_at: str
    updated_at: str
    version: int


class FixturePlan(TypedDict):
    id: str
    store_id: str
    item_class: str
    effective_from: str
    effective_to: Optional[str]
    fixture_count: int
    facings_per_fixture: int
    units_per_facing: int
    capacity_units: int
    presentation_min_units: int
    created_at: str
    updated_at: str
    version: int


class SizeProfile(TypedDict):
    """Append-only: carries only ``id`` and ``created_at``."""
    id: str
    program_id: str
    profile_code: str
    item_class: str
    size_curve: List[SizeCurveEntry]
    core_size_min_share_bp: int
    size_count: int
    core_size_count: int
    created_at: str


class Item(TypedDict):
    id: str
    program_id: str
    sku_code: str
    style_code: str
    item_class: str
    item_type: str
    size_profile_id: str
    unit_cost_usd: float
    retail_price_usd: float
    replenishment_model_override: Optional[str]
    replenishment_model: str
    lifecycle_state: str
    broken_store_count: int
    size_out_store_count: int
    created_at: str
    updated_at: str
    version: int


class StorePosition(TypedDict):
    id: str
    store_id: str
    item_id: str
    on_hand_units: int
    size_on_hand: List[SizeQuantity]
    on_order_units: int
    in_transit_units: int
    reserved_out_units: int
    available_units: int
    min_units: int
    max_units: int
    weekly_forecast_units: int
    trailing_4wk_sales_units: int
    stock_status: str
    assortment_status: str
    broken_size_count: int
    consolidated_out: bool
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict):
    id: str
    program_id: str
    item_id: str
    reference: str
    units_received: int
    size_received: List[SizeQuantity]
    receipt_date: str
    status: str
    units_committed: int
    units_unallocated: int
    created_at: str
    updated_at: str
    version: int


class AllocationRun(TypedDict):
    id: str
    receipt_id: str
    method: str
    need_basis: str
    status: str
    supersedes_run_id: Optional[str]
    proposed_by_user_id: Optional[str]
    committed_by_user_id: Optional[str]
    units_proposed: int
    units_committed: int
    unallocated_remainder_units: int
    eligible_store_count: int
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict):
    id: str
    run_id: str
    store_id: str
    need_units: int
    units_proposed: int
    units_allocated: int
    size_breakdown: List[SizeQuantity]
    capacity_capped_units: int
    presentation_gap_units: int
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class PromoEvent(TypedDict):
    id: str
    program_id: str
    event_code: str
    scope: str
    cluster_code: Optional[str]
    store_id: Optional[str]
    item_class: Optional[str]
    start_date: str
    end_date: str
    lift_factor_bp: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRecommendation(TypedDict):
    id: str
    program_id: str
    from_store_id: str
    to_store_id: str
    item_id: str
    units: int
    source_reason: str
    size_split: List[SizeQuantity]
    freight_cost_usd: float
    handling_fee_usd: float
    landed_cost_usd: float
    benefit_usd: float
    benefit_ratio_bp: int
    status: str
    expires_at: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    reject_reason: Optional[str]
    supersedes_recommendation_id: Optional[str]
    assortment_action_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssortmentAction(TypedDict):
    id: str
    item_id: str
    store_id: str
    trigger_reason: str
    action_type: str
    consolidation_target_store_id: Optional[str]
    broken_size_count: int
    markdown_pct_bp: Optional[int]
    units_at_detection: int
    status: str
    detected_at: str
    created_at: str
    updated_at: str
    version: int


class PerformanceSnapshot(TypedDict):
    """Append-only: carries only ``id`` and ``created_at``."""
    id: str
    program_id: str
    cluster_code: str
    basis: str
    as_of_date: str
    store_count: int
    included_position_count: int
    in_stock_pct_bp: int
    sell_through_pct_bp: int
    allocation_accuracy_bp: int
    created_at: str
