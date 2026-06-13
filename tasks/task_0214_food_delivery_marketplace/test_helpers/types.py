"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Food Delivery Marketplace data model described in the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RESTAURANT = "Restaurant"
    CUSTOMER = "Customer"
    DASHER = "Dasher"
    SUPPORT = "Support"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class RestaurantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class MenuItemStatus(str, Enum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class OrderFulfillmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PLACED = "PLACED"
    ROUTED = "ROUTED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderBillingStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class OrderLineItemStatus(str, Enum):
    ORDERED = "ORDERED"
    SHORTED = "SHORTED"


class DeliveryStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    REASSIGNED = "REASSIGNED"
    CANCELLED = "CANCELLED"


class OrderIssueStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EarningsRecordStatus(str, Enum):
    ACCRUED = "ACCRUED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class DasherAvailability(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class RefundDestination(str, Enum):
    ORIGINAL = "ORIGINAL"
    WALLET = "WALLET"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Every entity below carries the full common-field set
# (id / created_at / updated_at / version) EXCEPT TipAdjustment, which is a
# log-style record carrying only id + created_at (PRD §2.4).
# ---------------------------------------------------------------------------
class Zone(TypedDict):
    id: str
    name: str
    base_delivery_fee_cents: int
    per_km_fee_cents: int
    small_order_threshold_cents: int
    small_order_fee_cents: int
    service_fee_bps: int
    surge_tier_1_demand: int
    surge_tier_2_demand: int
    surge_multiplier_tier_0: float
    surge_multiplier_tier_1: float
    surge_multiplier_tier_2: float
    delivery_fee_cap_cents: int
    dasher_min_guarantee_cents: int
    dasher_per_km_pay_cents: int
    dasher_base_pay_cents: int
    active_order_count: int
    created_at: str
    updated_at: str
    version: int


class Restaurant(TypedDict):
    id: str
    zone_id: str
    name: str
    route_distance_km: int
    is_open: bool
    prep_minutes: int
    max_concurrent_prep: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    restaurant_id: str
    name: str
    price_cents: int
    available: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Dasher(TypedDict):
    id: str
    name: str
    home_zone_id: str
    max_batch_size: int
    active_delivery_count: int
    lifetime_earnings_cents: int
    availability: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    restaurant_id: str
    zone_id: str
    scheduled_for: Optional[str]
    order_subtotal_cents: int
    service_fee_cents: int
    delivery_fee_quote_cents: int
    delivery_fee_final_cents: Optional[int]
    tip_cents: int
    surge_multiplier_applied: float
    eta_minutes: int
    refunded_cents: int
    fulfillment_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class OrderLineItem(TypedDict):
    id: str
    order_id: str
    menu_item_id: str
    quantity: int
    unit_price_cents: int
    extended_price_cents: int
    service_fee_cents: int
    fulfilled_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    order_id: str
    dasher_id: str
    route_distance_km: int
    pay_quote_cents: int
    settled_pay_cents: Optional[int]
    offered_at: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


# Log-style entity: only id + created_at (PRD §2.4).
class TipAdjustment(TypedDict):
    id: str
    order_id: str
    delta_cents: int
    reason: Optional[str]
    resulting_tip_cents: int
    created_at: str


class OrderIssue(TypedDict):
    id: str
    order_id: str
    line_item_id: str
    missing_quantity: int
    refund_destination: str
    refund_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EarningsRecord(TypedDict):
    id: str
    dasher_id: str
    delivery_id: str
    base_component_cents: int
    tip_component_cents: int
    guarantee_topup_cents: int
    settled_pay_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
