"""Domain types: status enums, role enum and entity TypedDicts.

Ten resource types (`Store`, `Channel`, `MenuVersion`, `MenuItem`,
`ChannelListing`, `Order`, `CourierNetwork`, `DeliveryAssignment`, `Adjustment`,
`RemittanceStatement`) carry `id`, `created_at`, `updated_at` and `version`.
Four record types (`StoreHourWindow`, `AvailabilityEvent`, `OrderLine`,
`PosInjectionAttempt`) are append-only journal entries carrying only `id` and
`created_at` — they have no `updated_at` and no `version` at all (PRD §2.5).
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STORE_OPERATOR = "StoreOperator"
    CHANNEL_PARTNER = "ChannelPartner"
    COURIER_NETWORK_AGENT = "CourierNetworkAgent"
    SETTLEMENT_ANALYST = "SettlementAnalyst"


# --------------------------------------------------------------------------- #
# Status / enum vocabularies
# --------------------------------------------------------------------------- #
class ThrottleState(str, Enum):
    NORMAL = "NORMAL"
    THROTTLED = "THROTTLED"
    PAUSED = "PAUSED"


class ChannelType(str, Enum):
    MARKETPLACE = "MARKETPLACE"
    DIRECT = "DIRECT"
    AGGREGATOR = "AGGREGATOR"


class RoundingMode(str, Enum):
    CENT = "CENT"
    NICKEL = "NICKEL"


class SettlementMode(str, Enum):
    GROSS_MODE = "GROSS_MODE"
    NET_MODE = "NET_MODE"


class EightySixPolicy(str, Enum):
    HONOR_86 = "HONOR_86"
    IGNORE_86 = "IGNORE_86"


class ThrottlePolicy(str, Enum):
    SUPPRESS_ON_THROTTLE = "SUPPRESS_ON_THROTTLE"
    IGNORE_THROTTLE = "IGNORE_THROTTLE"


class AdjustmentReviewMode(str, Enum):
    CHANNEL_REVIEW = "CHANNEL_REVIEW"
    AUTO_ACCEPT = "AUTO_ACCEPT"


class MenuVersionState(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    EXHAUSTED = "EXHAUSTED"
    SUPERSEDED = "SUPERSEDED"


class AvailabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUPPRESSED = "SUPPRESSED"
    EIGHTY_SIXED = "EIGHTY_SIXED"
    THROTTLE_SUPPRESSED = "THROTTLE_SUPPRESSED"


class AvailabilityEventType(str, Enum):
    EIGHTY_SIX = "EIGHTY_SIX"
    RESTORE = "RESTORE"


class FulfillmentMode(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class InjectionStatus(str, Enum):
    PENDING = "PENDING"
    INJECTION_HELD = "INJECTION_HELD"
    ACCEPTED = "ACCEPTED"
    TABLET_FALLBACK = "TABLET_FALLBACK"
    FAILED = "FAILED"


class FulfillmentStatus(str, Enum):
    PREPARING = "PREPARING"
    READY = "READY"
    HANDED_OFF = "HANDED_OFF"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    SETTLEABLE = "SETTLEABLE"
    STATEMENT_ASSIGNED = "STATEMENT_ASSIGNED"
    SETTLED = "SETTLED"


class PosResultCode(str, Enum):
    OK = "OK"
    TIMEOUT = "TIMEOUT"
    PRINTER_DOWN = "PRINTER_DOWN"
    MENU_MISMATCH = "MENU_MISMATCH"


class InjectionAttemptOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class NetworkType(str, Enum):
    MARKETPLACE = "MARKETPLACE"
    COURIER = "COURIER"


class AssignmentState(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    HANDED_OFF = "HANDED_OFF"
    DELIVERED = "DELIVERED"


class AdjustmentType(str, Enum):
    REFUND = "REFUND"
    FEE_CREDIT = "FEE_CREDIT"


class AdjustmentState(str, Enum):
    DRAFT = "DRAFT"
    CHANNEL_REVIEW = "CHANNEL_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    REVERSED = "REVERSED"


class StatementState(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class StatementTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class QuoteVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"


# --------------------------------------------------------------------------- #
# First-class resources — id + created_at + updated_at + version
# --------------------------------------------------------------------------- #
class Store(TypedDict):
    id: str
    brand_code: str
    name: str
    timezone_offset_minutes: int
    base_prep_minutes: int
    prep_capacity_per_bucket: int
    pos_retry_limit: int
    tablet_backlog_threshold: int
    throttle_state: str
    active_menu_version_id: Optional[str]
    last_published_at: Optional[str]
    open_order_count: int
    reserved_prep_slots: int
    tablet_backlog_count: int
    created_at: str
    updated_at: str
    version: int


class Channel(TypedDict):
    id: str
    code: str
    name: str
    channel_type: str
    markup_bps: int
    rounding_mode: str
    service_fee_cents: int
    commission_bps: int
    settlement_mode: str
    eighty_six_policy: str
    throttle_policy: str
    adjustment_review_mode: str
    accepts_delivery: bool
    listing_count: int
    created_at: str
    updated_at: str
    version: int


class MenuVersion(TypedDict):
    id: str
    brand_code: str
    version_label: str
    state: str
    item_count: int
    published_store_count: int
    published_at: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    menu_version_id: str
    sku: str
    name: str
    base_price_cents: int
    tax_bps: int
    is_delivery_eligible: bool
    created_at: str
    updated_at: str
    version: int


class ChannelListing(TypedDict):
    id: str
    store_id: str
    channel_id: str
    menu_item_id: str
    sku: str
    base_price_cents: int
    price_cents: int
    suppressed: bool
    eighty_sixed: bool
    availability_state: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    store_id: str
    channel_id: str
    menu_version_id: str
    external_ref: str
    fulfillment_mode: str
    injection_status: str
    fulfillment_status: str
    settlement_status: str
    bucket_index: int
    promised_ready_at: str
    subtotal_cents: int
    tax_cents: int
    markup_cents: int
    service_fee_cents: int
    tip_cents: int
    channel_collected_cents: int
    commission_cents: int
    brand_net_cents: int
    refunded_total_cents: int
    injection_attempt_count: int
    remittance_statement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourierNetwork(TypedDict):
    id: str
    code: str
    name: str
    network_type: str
    priority_rank: int
    per_delivery_fee_cents: int
    handoff_sla_seconds: int
    dispatch_buffer_seconds: int
    max_concurrent_assignments: int
    is_active: bool
    open_assignment_count: int
    penalty_accrued_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliveryAssignment(TypedDict):
    id: str
    order_id: str
    courier_network_id: str
    state: str
    offered_at: str
    accepted_at: Optional[str]
    handoff_deadline_at: Optional[str]
    occupancy_until: str
    handoff_at: Optional[str]
    delivered_at: Optional[str]
    handoff_lateness_seconds: Optional[int]
    handoff_penalty_cents: int
    delivery_fee_cents: int
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class Adjustment(TypedDict):
    id: str
    order_id: str
    channel_id: str
    adjustment_type: str
    amount_cents: int
    reason_code: str
    commission_relief_cents: int
    state: str
    revision_round: int
    proposed_by_user_id: str
    accepted_at: Optional[str]
    reversed_at: Optional[str]
    remittance_statement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemittanceStatement(TypedDict):
    id: str
    channel_id: str
    period_start: str
    period_end: str
    state: str
    order_count: int
    gross_sales_cents: int
    adjustment_total_cents: int
    tier_base_cents: int
    tier: str
    commission_cents: int
    rebate_cents: int
    net_payable_cents: int
    open_adjustment_count: int
    reconciled_by_user_id: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Append-only journal entries — id + created_at only, no updated_at, no version
# --------------------------------------------------------------------------- #
class StoreHourWindow(TypedDict):
    id: str
    store_id: str
    day_of_week: int
    opens_at_minute: int
    closes_at_minute: int
    window_minutes: int
    created_at: str


class AvailabilityEvent(TypedDict):
    id: str
    store_id: str
    menu_item_id: str
    event_type: str
    actor_channel_id: Optional[str]
    effective_at: str
    propagated_listing_count: int
    skipped_listing_count: int
    held_order_count: int
    created_at: str


class OrderLine(TypedDict):
    id: str
    order_id: str
    sku: str
    quantity: int
    base_price_cents: int
    unit_price_cents: int
    tax_bps: int
    line_subtotal_cents: int
    line_tax_cents: int
    created_at: str


class PosInjectionAttempt(TypedDict):
    id: str
    order_id: str
    attempt_number: int
    pos_result_code: str
    attempted_at: str
    outcome: str
    created_at: str


APPEND_ONLY_FORBIDDEN_KEYS = ("updated_at", "version")
