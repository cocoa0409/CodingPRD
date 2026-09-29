"""Domain types for the dropship / endless-aisle vendor program.

Status enums, enumerated value sets and entity TypedDicts derived from the PRD's
entity catalogue and state machines.
"""

from enum import Enum
from typing import List, Optional, TypedDict

# ─── Roles ────────────────────────────────────────────


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    VENDOR_OPS_ANALYST = "VendorOpsAnalyst"
    MERCHANDISE_MANAGER = "MerchandiseManager"
    VENDOR_USER = "VendorUser"
    CARE_AGENT = "CareAgent"


ALL_ROLES: List[str] = [r.value for r in UserRole]


# ─── Status / state enums ─────────────────────────────


class VendorOnboardingStatus(str, Enum):
    DRAFT = "DRAFT"
    INTEGRATION_TESTING = "INTEGRATION_TESTING"
    CERTIFIED = "CERTIFIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VendorSuspensionReason(str, Enum):
    SCORECARD_PROBATION = "SCORECARD_PROBATION"
    MANUAL_OPS = "MANUAL_OPS"


class PerformanceTier(str, Enum):
    UNRATED = "UNRATED"
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    SILVER = "SILVER"
    WATCH = "WATCH"
    PROBATION = "PROBATION"


class CostModel(str, Enum):
    COMMISSION = "COMMISSION"
    WHOLESALE = "WHOLESALE"


class IntegrationMessageType(str, Enum):
    CATALOG = "CATALOG"
    INVENTORY = "INVENTORY"
    ORDER = "ORDER"
    SHIP_CONFIRM = "SHIP_CONFIRM"


ALL_MESSAGE_TYPES: List[str] = [m.value for m in IntegrationMessageType]


class IntegrationTestStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class IntegrationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ItemStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPPRESSED = "SUPPRESSED"


class ItemSuppressionReason(str, Enum):
    MANUAL = "MANUAL"
    VENDOR_SUSPENDED = "VENDOR_SUSPENDED"
    ZERO_AVAILABILITY = "ZERO_AVAILABILITY"


class ShipMethod(str, Enum):
    GROUND = "GROUND"
    TWO_DAY = "TWO_DAY"
    FREIGHT_LTL = "FREIGHT_LTL"


class ReverseFreightOwner(str, Enum):
    VENDOR = "VENDOR"
    RETAILER = "RETAILER"


class RestockPolicy(str, Enum):
    VENDOR_RESTOCK = "VENDOR_RESTOCK"
    RETAILER_RESTOCK = "RETAILER_RESTOCK"
    DESTROY = "DESTROY"


class ServiceabilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BlackoutReason(str, Enum):
    HOLIDAY = "HOLIDAY"
    PEAK_FREEZE = "PEAK_FREEZE"
    CAPACITY = "CAPACITY"
    SYSTEM_CUTOVER = "SYSTEM_CUTOVER"


class BlackoutStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class SnapshotSource(str, Enum):
    VENDOR_FEED = "VENDOR_FEED"
    MANUAL_ADJUST = "MANUAL_ADJUST"


class SnapshotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class OrderFulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class OrderFinancialStatus(str, Enum):
    PENDING = "PENDING"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class PromiseVariant(str, Enum):
    QUOTED = "QUOTED"
    RECOMPUTED = "RECOMPUTED"


class LineStatus(str, Enum):
    PENDING_TRANSMIT = "PENDING_TRANSMIT"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    BACKORDERED = "BACKORDERED"
    SHIPPED = "SHIPPED"
    CANCELLED_BY_VENDOR = "CANCELLED_BY_VENDOR"


class AckDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    BACKORDERED = "BACKORDERED"
    REJECTED = "REJECTED"


class Carrier(str, Enum):
    UPS = "UPS"
    FEDEX = "FEDEX"
    USPS = "USPS"
    LTL_CARRIER = "LTL_CARRIER"


class ReturnReasonCode(str, Enum):
    DEFECTIVE = "DEFECTIVE"
    NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"
    BUYER_REMORSE = "BUYER_REMORSE"
    LATE_DELIVERY = "LATE_DELIVERY"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class RoutingDestination(str, Enum):
    VENDOR = "VENDOR"
    RETAILER_DC = "RETAILER_DC"


class ReturnRejectionReason(str, Enum):
    OUTSIDE_DEFECT_WINDOW = "OUTSIDE_DEFECT_WINDOW"
    NOT_RECEIVED = "NOT_RECEIVED"
    POLICY = "POLICY"


class MetricVariant(str, Enum):
    EVENT_EQUAL = "EVENT_EQUAL"
    UNIT_WEIGHTED = "UNIT_WEIGHTED"


class ScorecardStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


# ─── Entity TypedDicts ────────────────────────────────
# Every entity below carries id + created_at + updated_at + version, except
# ShipmentConfirmation which is an append-only log carrying only id + created_at.


class Vendor(TypedDict):
    id: str
    vendor_code: str
    legal_name: str
    cost_model: str
    commission_rate_bps: Optional[int]
    wholesale_discount_bps: Optional[int]
    inventory_refresh_cadence_minutes: int
    safety_buffer_units: int
    oversell_grace_units: int
    default_lead_time_days: int
    ack_sla_hours: int
    ship_sla_grace_hours: int
    onboarding_status: str
    integration_round: int
    certified_by_user_id: Optional[str]
    activated_by_user_id: Optional[str]
    suspension_reason: Optional[str]
    performance_tier: str
    promise_padding_days: int
    settlement_balance_cents: int
    chargeback_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class IntegrationTest(TypedDict):
    id: str
    vendor_id: str
    message_type: str
    round_number: int
    sample_payload_digest: str
    reported_error_count: Optional[int]
    status: str
    evaluated_by_user_id: Optional[str]
    defect_notes: Optional[str]
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DropshipItem(TypedDict):
    id: str
    vendor_id: str
    fallback_item_id: Optional[str]
    sku: str
    lead_time_days: int
    ship_method: str
    unit_retail_cents: int
    unit_wholesale_cost_cents: Optional[int]
    reverse_freight_owner: Optional[str]
    restock_policy: Optional[str]
    defect_window_days: int
    status: str
    suppression_reason: Optional[str]
    effective_on_hand_units: int
    inventory_is_stale: bool
    reserved_units: int
    available_units: int
    last_inventory_refresh_at: Optional[str]
    lifetime_reserved_units: int
    lifetime_released_units: int
    lifetime_shipped_units: int
    unit_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceabilityRule(TypedDict):
    id: str
    vendor_id: str
    zone_code: str
    ship_method: str
    transit_days: int
    cutoff_hour_utc: int
    surcharge_cents: int
    status: str
    inactivated_by_suspension: bool
    created_at: str
    updated_at: str
    version: int


class VendorBlackout(TypedDict):
    id: str
    vendor_id: str
    start_date: str
    end_date: str
    reopen_buffer_days: int
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InventorySnapshot(TypedDict):
    id: str
    item_id: str
    on_hand_units: int
    effective_from: str
    effective_to: Optional[str]
    source: str
    status: str
    feed_sequence: int
    created_at: str
    updated_at: str
    version: int


class DropshipOrder(TypedDict):
    id: str
    order_ref: str
    customer_zone_code: str
    placed_at: str
    fulfillment_status: str
    financial_status: str
    quoted_promise_date: Optional[str]
    recomputed_promise_date: Optional[str]
    promise_variant_in_effect: str
    total_retail_cents: int
    total_cost_cents: int
    margin_cents: int
    refunded_cents: int
    net_retail_cents: int
    retailer_absorbed_cents: int
    created_at: str
    updated_at: str
    version: int


class DropshipOrderLine(TypedDict):
    id: str
    order_id: str
    item_id: str
    line_number: int
    quantity: int
    unit_retail_cents: int
    unit_cost_cents: int
    surcharge_cents: int
    status: str
    transmitted_at: Optional[str]
    acknowledged_at: Optional[str]
    shipped_at: Optional[str]
    ack_deadline_at: Optional[str]
    ship_deadline_at: Optional[str]
    ack_sla_breached: bool
    ship_sla_breached: bool
    transmit_attempt_count: int
    line_promise_date: Optional[str]
    returned_units: int
    created_at: str
    updated_at: str
    version: int


class ShipmentConfirmation(TypedDict):
    """Append-only shipment log: carries only id and created_at."""

    id: str
    line_id: str
    carrier: str
    tracking_number: str
    ship_date: str
    shipped_units: int
    package_count: int
    ship_hours: float
    on_time: bool
    created_at: str


class ReturnAuthorization(TypedDict):
    id: str
    line_id: str
    routed_vendor_id: Optional[str]
    reason_code: str
    quantity_returned: int
    status: str
    routing_destination: Optional[str]
    reverse_freight_owner: Optional[str]
    restock_disposition: Optional[str]
    refund_base_cents: Optional[int]
    restocking_fee_cents: Optional[int]
    customer_freight_charge_cents: Optional[int]
    refund_cents: Optional[int]
    vendor_chargeback_cents: Optional[int]
    restocked_units: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorScorecard(TypedDict):
    id: str
    vendor_id: str
    period_start: str
    period_end: str
    metric_variant: str
    seeded_prior_avg_ship_hours: Optional[float]
    seeded_prior_on_time_ship_rate_bps: Optional[int]
    seeded_prior_cancellation_rate_bps: Optional[int]
    seeded_prior_defect_rate_bps: Optional[int]
    transmitted_line_count: int
    shipped_line_count: int
    cancelled_line_count: int
    defect_return_count: int
    transmitted_unit_count: int
    shipped_unit_count: int
    cancelled_unit_count: int
    defect_unit_count: int
    on_time_ship_rate_bps: Optional[int]
    cancellation_rate_bps: Optional[int]
    defect_rate_bps: Optional[int]
    avg_ship_hours: Optional[float]
    composite_score: Optional[float]
    tier: str
    promise_padding_days: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Line-status groupings used by availability and rollup rules ───

OPEN_LINE_STATUSES: List[str] = [
    LineStatus.PENDING_TRANSMIT.value,
    LineStatus.TRANSMITTED.value,
    LineStatus.ACKNOWLEDGED.value,
    LineStatus.BACKORDERED.value,
]
