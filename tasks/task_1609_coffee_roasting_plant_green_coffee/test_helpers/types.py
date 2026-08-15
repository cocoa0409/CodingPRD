"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Entities carrying the standard four
system-managed fields have id + created_at + updated_at + version;
PriceFixEvent is the sole append-only exception and carries only id +
created_at (PRD: common resource properties).
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    TRADER = "Trader"
    RISK_MANAGER = "RiskManager"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    WAREHOUSE_CLERK = "WarehouseClerk"
    HEAD_ROASTER = "HeadRoaster"
    ROAST_OPERATOR = "RoastOperator"
    QA_GRADER = "QAGrader"
    FULFILLMENT_PLANNER = "FulfillmentPlanner"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Enums (field-level)
# ---------------------------------------------------------------------------

class CounterpartyKind(str, Enum):
    SUPPLIER = "SUPPLIER"
    IMPORTER = "IMPORTER"
    CUSTOMER = "CUSTOMER"


class CounterpartyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PricingMode(str, Enum):
    DIFFERENTIAL_PTBF = "DIFFERENTIAL_PTBF"
    FIXED_OUTRIGHT = "FIXED_OUTRIGHT"


class CoffeeGrade(str, Enum):
    SHB = "SHB"
    HG = "HG"
    NY2_3 = "NY2_3"
    ROBUSTA_GRADE1 = "ROBUSTA_GRADE1"


class PricingStatus(str, Enum):
    UNFIXED = "UNFIXED"
    PARTIALLY_FIXED = "PARTIALLY_FIXED"
    FULLY_FIXED = "FULLY_FIXED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    FULLY_RECEIVED = "FULLY_RECEIVED"
    SHORT_CLOSED = "SHORT_CLOSED"
    CANCELLED = "CANCELLED"


class TransitStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class ShipmentQcStatus(str, Enum):
    PENDING_CUP = "PENDING_CUP"
    CUP_PASSED = "CUP_PASSED"
    CUP_FAILED = "CUP_FAILED"
    NOT_REQUIRED = "NOT_REQUIRED"


class DisputeStatus(str, Enum):
    NONE = "NONE"
    DISPUTED = "DISPUTED"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"


class GreenLotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class FinancingStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ReserveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class Channel(str, Enum):
    PRIVATE_LABEL = "PRIVATE_LABEL"
    SUBSCRIPTION = "SUBSCRIPTION"
    WHOLESALE = "WHOLESALE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ProductionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_DRUM = "IN_DRUM"
    ROASTED = "ROASTED"
    PACKED = "PACKED"
    VOIDED = "VOIDED"


class BatchQcStatus(str, Enum):
    PENDING_QC = "PENDING_QC"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    NOT_REQUIRED = "NOT_REQUIRED"


class YieldVarianceFlag(str, Enum):
    WITHIN_BAND = "WITHIN_BAND"
    ABOVE_BAND = "ABOVE_BAND"
    BELOW_BAND = "BELOW_BAND"
    UNKNOWN = "UNKNOWN"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class FinishedLotStatus(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    DEPLETED = "DEPLETED"
    RECALLED = "RECALLED"


class SubjectKind(str, Enum):
    GREEN_LOT = "GREEN_LOT"
    ROAST_BATCH = "ROAST_BATCH"


class SessionVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING_REVIEW = "PENDING_REVIEW"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHIPPED = "SHIPPED"
    RELEASED = "RELEASED"


class HedgeSide(str, Enum):
    BUY_FUTURES = "BUY_FUTURES"
    SELL_FUTURES = "SELL_FUTURES"


class HedgeStatus(str, Enum):
    WORKING = "WORKING"
    APPROVED = "APPROVED"
    LIFTED = "LIFTED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Counterparty(TypedDict, total=False):
    id: str
    counterparty_ref: str
    legal_name: str
    counterparty_kind: str
    credit_limit_usd: float
    counterparty_status: str
    open_exposure_usd: float
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    counterparty_id: str
    contract_ref: str
    pricing_mode: str
    coffee_grade: str
    total_lbs: int
    fixed_price_usd_per_lb: Optional[float]
    differential_usd_per_lb: Optional[float]
    delivery_window_start: str
    delivery_window_end: str
    pricing_status: str
    fulfillment_status: str
    fixed_lbs_accum: int
    weighted_avg_fixed_futures_usd: Optional[float]
    received_lbs_accum: int
    priced_notional_usd: float
    unpriced_lbs: int
    created_at: str
    updated_at: str
    version: int


class PriceFixEvent(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at; updated_at and version absent.
    id: str
    contract_id: str
    fix_lbs: int
    futures_price_usd_per_lb: float
    fixed_at: str
    fixed_by_trader_id: str
    created_at: str


class Shipment(TypedDict, total=False):
    id: str
    contract_id: str
    shipment_ref: str
    planned_lbs: int
    scheduled_arrival: str
    transit_status: str
    qc_status: str
    dispute_status: str
    received_lbs: Optional[int]
    created_at: str
    updated_at: str
    version: int


class GreenLot(TypedDict, total=False):
    id: str
    shipment_id: str
    lot_code: str
    received_lbs: int
    moisture_pct: float
    warehouse_location: str
    landed_cost_usd_per_lb: float
    available_lbs: int
    cup_score: Optional[float]
    lot_status: str
    created_at: str
    updated_at: str
    version: int


class WarehousePosition(TypedDict, total=False):
    id: str
    position_as_of: str
    physical_lbs: int
    committed_lbs: int
    reserved_for_financing_lbs: int
    open_to_sell_lbs: int
    weighted_avg_landed_cost_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class InventoryFinancingLine(TypedDict, total=False):
    id: str
    lender_name: str
    facility_limit_usd: float
    advance_rate_pct: float
    utilized_usd: float
    collateral_value_usd: float
    financing_status: str
    created_at: str
    updated_at: str
    version: int


class FinancingReserve(TypedDict, total=False):
    id: str
    financing_line_id: str
    green_lot_id: str
    reserved_lbs: int
    reserve_advance_usd: float
    reserve_status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    display_name: str
    channel: str
    target_roast_profile_id: str
    freshness_days: int
    product_status: str
    created_at: str
    updated_at: str
    version: int


class RoastProfile(TypedDict, total=False):
    id: str
    profile_code: str
    charge_temp_c: int
    target_drop_temp_c: int
    expected_yield_loss_pct: float
    shrinkage_alert_band_pct: float
    created_at: str
    updated_at: str
    version: int


class BlendRecipe(TypedDict, total=False):
    id: str
    product_id: str
    recipe_version: int
    recipe_status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecipeComponent(TypedDict, total=False):
    id: str
    recipe_id: str
    required_grade: str
    component_pct: float
    substitution_grade: Optional[str]
    substitution_max_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class RoastBatch(TypedDict, total=False):
    id: str
    product_id: str
    recipe_id: str
    scheduled_green_lbs: int
    production_status: str
    qc_status: str
    actual_roasted_lbs: Optional[int]
    actual_yield_loss_pct: Optional[float]
    yield_variance_flag: str
    recipe_version_pinned: int
    roast_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoastInputAllocation(TypedDict, total=False):
    id: str
    roast_batch_id: str
    green_lot_id: str
    component_id: str
    allocated_lbs: int
    is_substitution: bool
    allocation_status: str
    created_at: str
    updated_at: str
    version: int


class FinishedGoodsLot(TypedDict, total=False):
    id: str
    roast_batch_id: str
    product_id: str
    packed_lbs: int
    packed_at: str
    sellable_until: str
    available_lbs: int
    lot_status: str
    created_at: str
    updated_at: str
    version: int


class CuppingSession(TypedDict, total=False):
    id: str
    subject_kind: str
    subject_id: str
    panelist_count: int
    score_aroma: float
    score_flavor: float
    score_aftertaste: float
    score_acidity: float
    score_body: float
    score_balance: float
    score_uniformity: float
    score_clean_cup: float
    score_sweetness: float
    score_overall: float
    defects_subtracted: int
    final_score: Optional[float]
    session_verdict: str
    reviewed_by_qa_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FulfillmentOrder(TypedDict, total=False):
    id: str
    customer_counterparty_id: str
    channel: str
    requested_ship_date: str
    order_status: str
    total_reserved_lbs: int
    created_at: str
    updated_at: str
    version: int


class FulfillmentLine(TypedDict, total=False):
    id: str
    order_id: str
    finished_goods_lot_id: str
    allocated_lbs: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


class FuturesHedge(TypedDict, total=False):
    id: str
    contract_id: str
    hedge_side: str
    hedge_lbs: int
    entry_price_usd_per_lb: float
    exit_price_usd_per_lb: Optional[float]
    realized_pnl_usd: Optional[float]
    hedge_status: str
    approved_by_risk_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
