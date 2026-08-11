"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the four common system-managed fields (id, created_at,
updated_at, version) described in PRD section "Common Resource Properties".
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    FRONT_DESK = "FrontDesk"
    TECHNICIAN = "Technician"
    MANAGER = "Manager"


class GearType(str, Enum):
    SKI = "SKI"
    SNOWBOARD = "SNOWBOARD"
    BOOT = "BOOT"
    POLES = "POLES"


class EquipmentTier(str, Enum):
    STANDARD = "STANDARD"
    PERFORMANCE = "PERFORMANCE"
    DEMO = "DEMO"
    JUNIOR = "JUNIOR"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OUT = "OUT"
    AWAITING_INSPECTION = "AWAITING_INSPECTION"
    IN_SERVICE = "IN_SERVICE"
    RETIRED = "RETIRED"
    LOST = "LOST"
    SOLD = "SOLD"


class SkierType(str, Enum):
    TYPE_1 = "TYPE_1"
    TYPE_2 = "TYPE_2"
    TYPE_3 = "TYPE_3"


class CustomerStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    BARRED = "BARRED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class ReservationItemStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"
    RETURNED = "RETURNED"


class TuneService(str, Enum):
    WAX = "WAX"
    EDGE_TUNE = "EDGE_TUNE"
    BASE_GRIND = "BASE_GRIND"
    BINDING_ADJUST = "BINDING_ADJUST"


class TuneTicketStatus(str, Enum):
    INTAKE = "INTAKE"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    QUALITY_CHECK = "QUALITY_CHECK"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class SeasonLeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SETTLED = "SETTLED"


class PackageTier(str, Enum):
    JUNIOR_SKI = "JUNIOR_SKI"
    JUNIOR_BOARD = "JUNIOR_BOARD"


class DemoCreditStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class PurchaseOrderStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class DamageSeverity(str, Enum):
    COSMETIC = "COSMETIC"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    TOTAL_LOSS = "TOTAL_LOSS"


class DamageAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    INVOICED = "INVOICED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class WindowPosture(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class PickupBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PickupMethod(str, Enum):
    SHOP = "SHOP"
    SLOPE_SIDE = "SLOPE_SIDE"


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    height_cm: float
    weight_kg: float
    boot_sole_mm: int
    skier_type: str
    standing: str
    late_return_count: int
    created_at: str
    updated_at: str
    version: int


class EquipmentItem(TypedDict, total=False):
    id: str
    gear_type: str
    size_label: str
    tier: str
    status: str
    din_min: float
    din_max: float
    purchase_price_cents: int
    base_daily_rate_cents: int
    accrued_rental_days: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    customer_id: str
    start_date: str
    end_date: str
    pickup_method: str
    fulfillment_status: str
    payment_status: str
    quoted_total_cents: int
    deposit_minimum_cents: int
    final_total_cents: Optional[int]
    deposit_authorized_cents: int
    deposit_captured_cents: int
    deposit_released_cents: int
    created_at: str
    updated_at: str
    version: int


class ReservationItem(TypedDict, total=False):
    id: str
    reservation_id: str
    equipment_item_id: Optional[str]
    gear_type_requested: str
    tier_requested: str
    status: str
    daily_rate_cents: Optional[int]
    din_setting: Optional[float]
    assigned_at: Optional[str]
    planned_days: int
    actual_days: Optional[int]
    late_days: Optional[int]
    line_final_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TuneTicket(TypedDict, total=False):
    id: str
    customer_id: str
    equipment_item_id: Optional[str]
    own_gear_description: Optional[str]
    services: List[str]
    rush: bool
    parts_surcharge_cents: int
    labor_minutes: int
    status: str
    promised_at: str
    quoted_price_cents: Optional[int]
    final_price_cents: Optional[int]
    rework_count: int
    junior_discount_applied: bool
    created_at: str
    updated_at: str
    version: int


class SeasonLease(TypedDict, total=False):
    id: str
    junior_customer_id: str
    guardian_customer_id: str
    season_start_date: str
    season_end_date: str
    package_tier: str
    deposit_cents: int
    equipment_item_id: Optional[str]
    status: str
    swap_count: int
    activated_at: Optional[str]
    buyout_price_straight_line_cents: Optional[int]
    buyout_price_usage_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DemoCredit(TypedDict, total=False):
    id: str
    customer_id: str
    equipment_item_id: str
    demo_date: str
    fee_paid_cents: int
    credit_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    customer_id: str
    equipment_item_id: str
    demo_credit_id: Optional[str]
    list_price_cents: int
    credit_applied_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageAssessment(TypedDict, total=False):
    id: str
    reservation_id: str
    equipment_item_id: str
    severity: str
    notes: Optional[str]
    charge_cents: int
    deposit_captured_cents: int
    remainder_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupWindow(TypedDict, total=False):
    id: str
    service_date: str
    start_time: str
    end_time: str
    location_label: str
    van_capacity: int
    booked_count: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class PickupBooking(TypedDict, total=False):
    id: str
    pickup_window_id: str
    reservation_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShopDayCapacity(TypedDict, total=False):
    id: str
    service_date: str
    base_labor_minutes: int
    rush_reserved_minutes: int
    booked_minutes: int
    rush_booked_minutes: int
    created_at: str
    updated_at: str
    version: int
