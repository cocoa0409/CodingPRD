"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# ──────────────────────────────────────────────────────────
# Role enum — five roles recognized by the platform.
# ──────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CUSTOMER = "Customer"
    RESTAURANT = "Restaurant"
    RIDER = "Rider"
    CUSTOMER_SERVICE = "CustomerService"
    PLATFORM_ADMIN = "PlatformAdmin"


# ──────────────────────────────────────────────────────────
# Status enums — one per entity that has a state machine.
# ──────────────────────────────────────────────────────────

class RestaurantStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class RiderStatus(str, Enum):
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    ON_DELIVERY = "ON_DELIVERY"
    SUSPENDED = "SUSPENDED"


class RiderBonusTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    RESTAURANT_ACCEPTED = "RESTAURANT_ACCEPTED"
    PREPARING = "PREPARING"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REFUND_REQUESTED = "REFUND_REQUESTED"
    REFUNDED = "REFUNDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    FULLY_REFUNDED = "FULLY_REFUNDED"
    VOIDED = "VOIDED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RouteGroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class FineSubjectType(str, Enum):
    RIDER = "RIDER"
    RESTAURANT = "RESTAURANT"
    CUSTOMER = "CUSTOMER"


class FineReason(str, Enum):
    LATE_DELIVERY = "LATE_DELIVERY"
    ABUSIVE_RETURN = "ABUSIVE_RETURN"
    RESTAURANT_STOCKOUT = "RESTAURANT_STOCKOUT"
    RIDER_NO_SHOW = "RIDER_NO_SHOW"


class FineSettlementStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class ReturnReason(str, Enum):
    QUALITY_ISSUE = "QUALITY_ISSUE"
    WRONG_ITEM = "WRONG_ITEM"
    LATE = "LATE"
    OTHER = "OTHER"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


class WorkOrderOpenedByRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    RIDER = "RIDER"
    RESTAURANT = "RESTAURANT"
    CUSTOMER_SERVICE = "CUSTOMER_SERVICE"


class WorkOrderCategory(str, Enum):
    DELIVERY_LATE = "DELIVERY_LATE"
    FOOD_QUALITY = "FOOD_QUALITY"
    MISSING_ITEM = "MISSING_ITEM"
    RIDER_BEHAVIOR = "RIDER_BEHAVIOR"
    RESTAURANT_BEHAVIOR = "RESTAURANT_BEHAVIOR"
    PAYMENT_ISSUE = "PAYMENT_ISSUE"
    OTHER = "OTHER"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    AWAITING_INFO = "AWAITING_INFO"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


# ──────────────────────────────────────────────────────────
# TypedDicts — common-fields entities carry id/created_at/updated_at/version.
# Append-only entities (Assignment, RouteGroup, Fine) carry only id + created_at.
# ──────────────────────────────────────────────────────────

class Restaurant(TypedDict, total=False):
    id: str
    name: str
    address: str
    lat: float
    lng: float
    status: str
    commission_rate_override: Optional[float]
    pending_settlement_cents: int
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict, total=False):
    id: str
    name: str
    phone: str
    status: str
    on_time_rate: float
    acceptance_rate: float
    rating: float
    bonus_tier: str
    wallet_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    name: str
    phone: str
    address: str
    lat: float
    lng: float
    credit_balance_cents: int
    trust_score: float
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict, total=False):
    id: str
    restaurant_id: str
    name: str
    price_cents: int
    is_listed: bool
    created_at: str
    updated_at: str
    version: int


class OrderItem(TypedDict, total=False):
    menu_item_id: str
    name: str
    unit_price_cents: int
    quantity: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    restaurant_id: str
    status: str
    items: List[OrderItem]
    subtotal_cents: int
    distance_km: float
    is_peak: bool
    provisional_delivery_fee_cents: int
    final_delivery_fee_cents: Optional[int]
    provisional_commission_cents: int
    final_commission_cents: Optional[int]
    promised_delivery_time: str
    actual_delivery_time: Optional[str]
    minutes_late: Optional[int]
    payment_status: str
    created_at: str
    updated_at: str
    version: int


# Assignment, RouteGroup, Fine: append-only (common_fields: false).
# Per PRD §2.4, only id + created_at are exposed; no updated_at, no version.

class Assignment(TypedDict, total=False):
    id: str
    order_id: str
    rider_id: str
    status: str
    offered_at: str
    accepted_at: Optional[str]
    picked_up_at: Optional[str]
    delivered_at: Optional[str]
    route_group_id: Optional[str]
    final_delivery_fee_cents: Optional[int]
    created_at: str


class RouteGroup(TypedDict, total=False):
    id: str
    rider_id: str
    assignment_ids: List[str]
    merged_at: str
    status: str
    created_at: str


class Fine(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    order_id: str
    reason: str
    amount_cents: int
    settlement_status: str
    created_at: str


class Return(TypedDict, total=False):
    id: str
    order_id: str
    reason: str
    requested_refund_cents: int
    status: str
    approved_refund_cents: Optional[int]
    reviewer_cs_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    opened_by_role: str
    opened_by_id: str
    related_order_id: Optional[str]
    related_return_id: Optional[str]
    category: str
    status: str
    assigned_cs_user_id: Optional[str]
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int
