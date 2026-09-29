"""Domain types for the ship-from-store fulfillment network API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------- roles


class UserRole(str, Enum):
    NETWORK_PLANNER = "NetworkPlanner"
    STORE_ASSOCIATE = "StoreAssociate"
    CARRIER_COORDINATOR = "CarrierCoordinator"
    CUSTOMER_CARE = "CustomerCare"


# ------------------------------------------------------------ enums


class NodeStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    PROBATION = "PROBATION"
    DEACTIVATED = "DEACTIVATED"


class EligibilityScoreBasis(str, Enum):
    COLD_START = "COLD_START"
    TRAILING_WINDOW = "TRAILING_WINDOW"


class PackageClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class PackageType(str, Enum):
    POLY_MAILER = "POLY_MAILER"
    SMALL_BOX = "SMALL_BOX"
    MEDIUM_BOX = "MEDIUM_BOX"
    LARGE_BOX = "LARGE_BOX"


class AdjustmentReason(str, Enum):
    CYCLE_COUNT = "CYCLE_COUNT"
    SHRINK = "SHRINK"
    RECEIPT = "RECEIPT"
    MARKDOWN_PULL = "MARKDOWN_PULL"


class CarrierPickupStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CLOSED = "CLOSED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class ServiceLevel(str, Enum):
    GROUND = "GROUND"
    EXPEDITED = "EXPEDITED"


class OrderRoutingStatus(str, Enum):
    UNROUTED = "UNROUTED"
    ROUTING = "ROUTING"
    ROUTED = "ROUTED"
    PARTIALLY_ROUTED = "PARTIALLY_ROUTED"
    UNROUTABLE = "UNROUTABLE"


class OrderFulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_ASSIGNED = "PARTIALLY_ASSIGNED"
    FULLY_ASSIGNED = "FULLY_ASSIGNED"
    SHIPPED = "SHIPPED"
    DC_FALLBACK = "DC_FALLBACK"
    CANCELLED = "CANCELLED"


class RoutingRunMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    COMMIT = "COMMIT"


class RoutingRunInitiatedBy(str, Enum):
    PLANNER = "PLANNER"
    SYSTEM_REROUTE = "SYSTEM_REROUTE"
    SYSTEM_DEACTIVATION = "SYSTEM_DEACTIVATION"


class RoutingRunStatus(str, Enum):
    EVALUATED = "EVALUATED"
    COMMITTED = "COMMITTED"
    NO_ELIGIBLE_NODE = "NO_ELIGIBLE_NODE"


class CandidateIneligibleReason(str, Enum):
    NODE_NOT_ELIGIBLE = "NODE_NOT_ELIGIBLE"
    CUTOFF_PASSED = "CUTOFF_PASSED"
    CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
    LABOR_EXHAUSTED = "LABOR_EXHAUSTED"
    NO_ATP = "NO_ATP"
    HAZMAT_NOT_CERTIFIED = "HAZMAT_NOT_CERTIFIED"
    EXCLUDED_BY_PRIOR_FAILURE = "EXCLUDED_BY_PRIOR_FAILURE"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    PICKED = "PICKED"
    SHORT_PICKED = "SHORT_PICKED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RejectReasonCode(str, Enum):
    NO_STOCK_ON_FLOOR = "NO_STOCK_ON_FLOOR"
    LABOR_UNAVAILABLE = "LABOR_UNAVAILABLE"
    DAMAGED_UNITS = "DAMAGED_UNITS"
    STORE_CLOSED = "STORE_CLOSED"


class CancelReasonCode(str, Enum):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    STORE_SHORTAGE = "STORE_SHORTAGE"
    SLA_RISK = "SLA_RISK"
    SHORT_PICK_SHORTFALL = "SHORT_PICK_SHORTFALL"
    PICK_SLA_EXPIRED = "PICK_SLA_EXPIRED"
    NODE_DEACTIVATED = "NODE_DEACTIVATED"
    SUPERSEDED = "SUPERSEDED"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class NodeAction(str, Enum):
    NONE = "NONE"
    PROBATION = "PROBATION"
    DEACTIVATION = "DEACTIVATION"
    RECOVERY = "RECOVERY"


class BreachFlag(str, Enum):
    FILL_RATE = "FILL_RATE"
    CYCLE_TIME = "CYCLE_TIME"
    CANCELLATION_RATE = "CANCELLATION_RATE"


class NotificationType(str, Enum):
    REJECTION_REROUTED = "REJECTION_REROUTED"
    SHORT_PICK_REROUTED = "SHORT_PICK_REROUTED"
    CANCELLATION_PARTIAL = "CANCELLATION_PARTIAL"
    CANCELLATION_FULL = "CANCELLATION_FULL"
    DC_FALLBACK = "DC_FALLBACK"
    UNROUTABLE = "UNROUTABLE"
    NODE_DEACTIVATED_REROUTED = "NODE_DEACTIVATED_REROUTED"


class NotificationChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"


# ------------------------------------------------------- entity shapes
# Entities that carry id + created_at + updated_at + version.


class Store(TypedDict):
    id: str
    store_code: str
    region_code: str
    origin_zone: int
    daily_unit_capacity: int
    units_committed_epoch: int
    staffed_labor_minutes: int
    reserved_labor_minutes: float
    labor_standard_minutes_per_order: float
    pick_labor_minutes_per_unit: float
    labor_rate_cents_per_minute: int
    cutoff_utc_minutes: int
    hazmat_certified: bool
    node_status: str
    eligibility_score: float
    eligibility_score_basis: str
    review_score: float
    consecutive_breach_windows: int
    deactivated_at_epoch: Optional[int]
    reactivation_count: int
    created_at: str
    updated_at: str
    version: int


class Sku(TypedDict):
    id: str
    sku_code: str
    unit_weight_grams: int
    unit_price_cents: int
    package_class: str
    hazmat_flag: bool
    created_at: str
    updated_at: str
    version: int


class StoreInventory(TypedDict):
    id: str
    store_id: str
    sku_id: str
    on_hand_units: int
    reserved_units: int
    safety_stock_units: int
    available_to_promise_units: int
    last_adjustment_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackagingSupply(TypedDict):
    id: str
    store_id: str
    package_type: str
    on_hand_units: int
    reorder_point_units: int
    reorder_flag: bool
    lifetime_consumed_units: int
    created_at: str
    updated_at: str
    version: int


class CarrierPickup(TypedDict):
    id: str
    store_id: str
    carrier_code: str
    window_start_utc: str
    window_end_utc: str
    parcel_capacity: int
    reserved_parcels: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict):
    id: str
    order_code: str
    customer_ref: str
    destination_zone: int
    service_level: str
    promised_ship_by_utc: str
    routing_status: str
    fulfillment_status: str
    total_units: int
    shipped_units: int
    unassigned_units: int
    dc_fallback_units: int
    split_count: int
    reroute_attempt_count: int
    provisional_cost_cents: int
    final_cost_cents: Optional[int]
    cost_variance_cents: Optional[int]
    dc_baseline_cost_cents: int
    cost_index_bps: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    sku_id: str
    quantity: int
    unit_price_cents: int
    assigned_units: int
    shipped_units: int
    cancelled_units: int
    dc_fallback_units: int
    open_units: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


class RoutingRun(TypedDict):
    id: str
    order_id: str
    mode: str
    initiated_by: str
    excluded_store_ids: List[str]
    candidate_count: int
    selected_store_count: int
    planned_split_count: int
    projected_cost_cents: int
    projected_dc_cost_cents: int
    projected_cost_index_bps: int
    unfulfillable_units: int
    guardrail_overridden: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FulfillmentAssignment(TypedDict):
    id: str
    order_id: str
    store_id: str
    routing_run_id: str
    carrier_pickup_id: Optional[str]
    superseded_by_routing_run_id: Optional[str]
    epoch: int
    status: str
    assigned_units: int
    picked_units: int
    shortfall_units: int
    labor_minutes_reserved: float
    labor_minutes_actual: Optional[float]
    package_type: Optional[str]
    derived_package_type: str
    billable_weight_grams: int
    provisional_cost_cents: int
    final_cost_cents: Optional[int]
    pick_deadline_utc: str
    accepted_at: Optional[str]
    picked_at: Optional[str]
    packed_at: Optional[str]
    shipped_at: Optional[str]
    cycle_time_minutes: Optional[int]
    reroute_generation: int
    reject_reason_code: Optional[str]
    cancel_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NodePerformanceWindow(TypedDict):
    id: str
    store_id: str
    epoch: int
    status: str
    opened_at_utc: str
    closed_at_utc: Optional[str]
    assignments_created: int
    assignments_shipped: int
    assignments_rejected: int
    assignments_cancelled: int
    units_promised: int
    units_shipped: int
    fill_rate: float
    avg_cycle_time_minutes: float
    cancellation_rate: float
    breach_flags: List[str]
    breached: bool
    store_cost_per_order_cents: int
    dc_cost_per_order_cents: int
    cost_index_bps: int
    cost_disadvantaged: bool
    node_action: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------- immutable rows: id + created_at only


class RoutingCandidate(TypedDict):
    id: str
    routing_run_id: str
    store_id: str
    iteration: int
    eligible: bool
    ineligible_reason: Optional[str]
    coverage_units: int
    coverage_ratio: float
    cost_estimate_cents: int
    delivery_days: int
    routing_score: Optional[float]
    rank: Optional[int]
    selected: bool
    assigned_units: int
    created_at: str


class AssignmentLine(TypedDict):
    id: str
    assignment_id: str
    order_line_id: str
    units_assigned: int
    units_picked: int
    units_cancelled: int
    created_at: str


class CustomerNotification(TypedDict):
    id: str
    order_id: str
    assignment_id: Optional[str]
    notification_type: str
    channel: str
    units_affected: int
    body_summary: str
    sent_at_utc: str
    created_at: str


class CostComparison(TypedDict):
    order_id: str
    variant: str
    parcel_count: int
    component_sum_cents: int
    split_penalty_cents: int
    reroute_overhead_cents: int
    pre_fee_subtotal_cents: int
    network_fee_rate: float
    network_fee_cents: int
    store_cost_cents: int
    dc_baseline_cost_cents: int
    cost_index_bps: int
    savings_vs_dc_cents: int
