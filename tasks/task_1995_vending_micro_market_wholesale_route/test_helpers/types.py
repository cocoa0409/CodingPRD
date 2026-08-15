"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    WHOLESALE_ADMIN = "WholesaleAdmin"
    OPERATOR_MANAGER = "OperatorManager"
    ROUTE_PLANNER = "RoutePlanner"
    WAREHOUSE_OPS = "WarehouseOps"
    CREDIT_ADJUSTER = "CreditAdjuster"
    TELEMETRY_GATEWAY = "TelemetryGateway"


class Tender(str, Enum):
    CASH = "CASH"
    CASHLESS = "CASHLESS"


class OperatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProductCategory(str, Enum):
    BEVERAGE = "BEVERAGE"
    SNACK = "SNACK"
    CANDY = "CANDY"
    CHILLED = "CHILLED"
    FROZEN = "FROZEN"


class LocationType(str, Enum):
    OFFICE = "OFFICE"
    SCHOOL = "SCHOOL"
    HOSPITAL = "HOSPITAL"
    GYM = "GYM"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class PlanogramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class OrderSource(str, Enum):
    MANUAL = "MANUAL"
    TELEMETRY_SUGGESTED = "TELEMETRY_SUGGESTED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNINVOICED = "UNINVOICED"
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class DiscountType(str, Enum):
    PERCENT_OFF = "PERCENT_OFF"
    CENTS_OFF = "CENTS_OFF"


class StackingClass(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    STACKABLE = "STACKABLE"


class PromotionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"
    SETTLED = "SETTLED"


class IssueType(str, Enum):
    PART_REPLACEMENT = "PART_REPLACEMENT"
    REPAIR = "REPAIR"
    PREVENTIVE = "PREVENTIVE"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


# --- Entity representations -------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# TelemetryEvent is the append-only exception: id + created_at only.


class Operator(TypedDict, total=False):
    id: str
    name: str
    default_tender: str
    credit_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    route_code: str
    delivery_weekdays: List[str]
    daily_case_capacity: int
    min_order_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    eligible_location_types: List[str]
    case_pack_qty: int
    base_price_cents: int
    cost_cents: int
    shelf_life_days: int
    perishability_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict, total=False):
    id: str
    operator_id: str
    name: str
    location_type: str
    route_id: str
    on_hand_projection: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Planogram(TypedDict, total=False):
    id: str
    location_id: str
    name: str
    slots: List[Dict[str, Any]]
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TelemetryEvent(TypedDict, total=False):
    # Append-only DEX log (PRD §2.4): id + created_at only — no updated_at, no version.
    id: str
    location_id: str
    recorded_at: str
    cash_collected_cents: int
    cashless_sales_cents: int
    items: List[Dict[str, Any]]
    created_at: str


class ReplenishmentOrder(TypedDict, total=False):
    id: str
    operator_id: str
    location_id: str
    route_id: str
    source: str
    requested_delivery_date: str
    lines: List[Dict[str, Any]]
    total_cases: int
    order_total_cents: int
    promo_discount_cents: int
    provisional_margin_per_vend_cents: Optional[int]
    realized_margin_per_vend_cents: Optional[int]
    cashless_fee_cents: Optional[int]
    amount_due_cents: int
    credit_applied_cents: int
    settled_tender: Optional[str]
    settlement_telemetry_event_id: Optional[str]
    fulfillment_status: str
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict, total=False):
    id: str
    product_id: str
    operator_id: Optional[str]
    discount_type: str
    discount_value: int
    starts_at: str
    ends_at: str
    stacking_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditClaim(TypedDict, total=False):
    id: str
    operator_id: str
    order_id: str
    lines: List[Dict[str, Any]]
    requested_credit_cents: int
    applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict, total=False):
    id: str
    location_id: str
    equipment_model: str
    issue_type: str
    parts: List[Dict[str, Any]]
    parts_total_cents: int
    service_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteAvailability(TypedDict, total=False):
    date: str
    daily_case_capacity: int
    firm_consumed_cases: int
    optimistic_consumed_cases: int
    firm_remaining_cases: int
    optimistic_remaining_cases: int
