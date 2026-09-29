"""Domain types for the Spare Parts Aftermarket API: entity shapes, status enums, role enum."""

from enum import Enum
from typing import Optional, TypedDict


# ─── Role enum (PRD section 2.1) ────────────────────────────────────────────

class UserRole(str, Enum):
    AFTERMARKET_PLANNER = "AftermarketPlanner"
    INVENTORY_CONTROLLER = "InventoryController"
    DEALER_USER = "DealerUser"
    PRICING_ANALYST = "PricingAnalyst"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status / enum vocabularies ─────────────────────────────────────────────

class PartLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    PHASE_OUT = "PHASE_OUT"
    LTB_OPEN = "LTB_OPEN"
    LTB_CLOSED = "LTB_CLOSED"
    OBSOLETE = "OBSOLETE"
    SUPERSEDED = "SUPERSEDED"


class CriticalityClass(str, Enum):
    VITAL = "VITAL"
    ESSENTIAL = "ESSENTIAL"
    DESIRABLE = "DESIRABLE"


class StockingPolicy(str, Enum):
    STOCK_TO_MAX = "STOCK_TO_MAX"
    MIN_MAX = "MIN_MAX"
    MAKE_TO_ORDER = "MAKE_TO_ORDER"
    NO_STOCK = "NO_STOCK"


class ReplenishmentStatus(str, Enum):
    NORMAL = "NORMAL"
    BELOW_REORDER_POINT = "BELOW_REORDER_POINT"
    ON_ORDER = "ON_ORDER"


class InstalledUnitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ApplicabilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class DealerTier(str, Enum):
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    SILVER = "SILVER"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Region(str, Enum):
    NA = "NA"
    EU = "EU"
    APAC = "APAC"
    LATAM = "LATAM"


class WorkType(str, Enum):
    SCHEDULED_MAINTENANCE = "SCHEDULED_MAINTENANCE"
    BREAKDOWN = "BREAKDOWN"
    CAMPAIGN = "CAMPAIGN"


class DowntimePriority(str, Enum):
    MACHINE_DOWN = "MACHINE_DOWN"
    DEGRADED = "DEGRADED"
    PLANNED = "PLANNED"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    PARTS_PENDING = "PARTS_PENDING"
    CLOSED = "CLOSED"


class LineStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    BACKORDERED = "BACKORDERED"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"


class FulfillmentMode(str, Enum):
    STOCK = "STOCK"
    AIR_FREIGHT = "AIR_FREIGHT"
    BACKORDER = "BACKORDER"


class ForecastMethod(str, Enum):
    WORK_ORDER_HISTORY = "WORK_ORDER_HISTORY"
    INSTALLED_BASE_RATE = "INSTALLED_BASE_RATE"
    BLENDED = "BLENDED"


class ForecastStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class LtbMethod(str, Enum):
    DEMAND_DECAY = "DEMAND_DECAY"
    FLAT_RATE = "FLAT_RATE"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ALLOCATING = "ALLOCATING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class OrderType(str, Enum):
    STOCK = "STOCK"
    EMERGENCY_AIR = "EMERGENCY_AIR"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LogisticsStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"


class ReturnReason(str, Enum):
    WRONG_PART = "WRONG_PART"
    UNUSED_SURPLUS = "UNUSED_SURPLUS"
    DEFECTIVE = "DEFECTIVE"
    CORE_RETURN = "CORE_RETURN"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    CREDITED = "CREDITED"
    SCRAPPED = "SCRAPPED"


class Disposition(str, Enum):
    RESTOCK = "RESTOCK"
    SCRAP = "SCRAP"


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class LedgerEntryType(str, Enum):
    RECEIPT = "RECEIPT"
    ISSUE = "ISSUE"
    RETURN_RECEIPT = "RETURN_RECEIPT"
    SCRAP = "SCRAP"


class SourceRefType(str, Enum):
    REPLENISHMENT_ORDER = "REPLENISHMENT_ORDER"
    WORK_ORDER_PART_LINE = "WORK_ORDER_PART_LINE"
    RETURN_AUTHORIZATION = "RETURN_AUTHORIZATION"


# ─── Entity shapes ──────────────────────────────────────────────────────────
# Every resource carries id + created_at.  Almost every resource also carries
# updated_at and version; the stock ledger entry is the single exception
# (PRD section 2.5).

class Part(TypedDict):
    id: str
    part_number: str
    description: str
    lifecycle_state: str
    superseded_by_part_id: Optional[str]
    unit_cost_cents: int
    lead_time_days: int
    weight_kg: float
    hazmat: bool
    max_stock_units: int
    criticality_score: float
    criticality_class: str
    stocking_policy: str
    safety_stock_units: int
    reorder_point_units: int
    on_hand_units: int
    allocated_units: int
    quarantine_units: int
    in_transit_units: int
    available_units: int
    replenishment_status: str
    current_list_unit_price_cents: int
    current_effective_uplift_pct: float
    created_at: str
    updated_at: str
    version: int


class EquipmentModel(TypedDict):
    id: str
    model_code: str
    name: str
    production_end_date: str
    support_end_date: str
    created_at: str
    updated_at: str
    version: int


class InstalledUnit(TypedDict):
    id: str
    model_id: str
    dealer_id: str
    serial_number: str
    build_revision: int
    commission_date: str
    region: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PartApplicability(TypedDict):
    id: str
    part_id: str
    model_id: str
    effective_from_build_revision: int
    effective_to_build_revision: Optional[int]
    qty_per_unit: int
    applicability_status: str
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict):
    id: str
    dealer_code: str
    tier: str
    region: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    lifetime_restocking_fee_cents: int
    lifetime_rebate_cents: int
    credit_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceWorkOrder(TypedDict):
    id: str
    installed_unit_id: str
    dealer_id: str
    work_type: str
    downtime_priority: str
    status: str
    opened_at: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrderPartLine(TypedDict):
    id: str
    work_order_id: str
    part_id: str
    qty_requested: int
    qty_consumed: int
    line_status: str
    fulfillment_mode: str
    decision_net_benefit_cents: int
    freight_cost_cents: int
    effective_uplift_pct: float
    list_unit_price_cents: int
    list_line_total_cents: int
    quoted_line_total_cents: int
    variant_delta_cents: int
    margin_pct: float
    charged_amount_cents: int
    consumed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DemandForecast(TypedDict):
    id: str
    part_id: str
    horizon_months: int
    lookback_days: int
    method: str
    wo_history_units: int
    annualized_wo_units: float
    installed_base_units: int
    ib_rate_units: float
    forecast_units: int
    forecast_status: str
    computed_at: str
    created_at: str
    updated_at: str
    version: int


class LastTimeBuyCampaign(TypedDict):
    id: str
    part_id: str
    method: str
    coverage_years: int
    ltb_window_start: str
    ltb_window_end: str
    annual_demand_units: int
    proposed_qty: int
    approved_qty: int
    remaining_qty: int
    status: str
    revision_index: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationRequest(TypedDict):
    id: str
    campaign_id: str
    dealer_id: str
    requested_units: int
    granted_units: int
    priority_score: int
    dealer_installed_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplenishmentOrder(TypedDict):
    id: str
    part_id: str
    order_type: str
    qty: int
    unit_cost_cents: int
    freight_cost_cents: int
    total_landed_cost_cents: int
    approval_status: str
    logistics_status: str
    auto_generated: bool
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict):
    id: str
    work_order_part_line_id: str
    part_id: str
    dealer_id: str
    qty_returned: int
    return_reason: str
    age_days: int
    gross_credit_cents: int
    fee_pct: float
    restocking_fee_cents: int
    net_before_rebate_cents: int
    rebate_pct: float
    loyalty_rebate_cents: int
    final_credit_cents: int
    credit_posted_cents: int
    disposition: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AftermarketPriceRule(TypedDict):
    id: str
    criticality_class: str
    base_uplift_pct: float
    max_uplift_pct: float
    min_margin_pct: float
    rule_status: str
    created_at: str
    updated_at: str
    version: int


class StockLedgerEntry(TypedDict):
    """Append-only: carries only id and created_at, no updated_at and no version."""
    id: str
    part_id: str
    entry_type: str
    delta_units: int
    balance_after_units: int
    source_ref_type: str
    source_ref_id: str
    occurred_at: str
    created_at: str
