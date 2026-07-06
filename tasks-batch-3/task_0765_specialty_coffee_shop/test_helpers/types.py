"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD exactly. Every persisted resource in this
system carries the common fields id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    MANAGER = "Manager"
    BARISTA = "Barista"
    CUSTOMER = "Customer"


# --------------------------------------------------------------------------
# Status / enum value sets
# --------------------------------------------------------------------------
class RoastLevel(str, Enum):
    LIGHT = "LIGHT"
    MEDIUM = "MEDIUM"
    DARK = "DARK"


class RotationStatus(str, Enum):
    RESERVE = "RESERVE"
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"


class ModifierGroup(str, Enum):
    MILK = "MILK"
    SHOT = "SHOT"
    SYRUP = "SYRUP"


class MenuCategory(str, Enum):
    BEVERAGE = "BEVERAGE"
    FOOD = "FOOD"
    RETAIL_BAG = "RETAIL_BAG"


class Size(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class RequiredEquipmentType(str, Enum):
    ESPRESSO = "ESPRESSO"
    BATCH_BREW = "BATCH_BREW"
    GRINDER = "GRINDER"
    NONE = "NONE"


class EquipmentType(str, Enum):
    ESPRESSO = "ESPRESSO"
    BATCH_BREW = "BATCH_BREW"
    GRINDER = "GRINDER"


class EquipmentStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    NEEDS_CALIBRATION = "NEEDS_CALIBRATION"
    IN_MAINTENANCE = "IN_MAINTENANCE"


class MaintenanceKind(str, Enum):
    CALIBRATION = "CALIBRATION"
    REPAIR = "REPAIR"
    CLEANING = "CLEANING"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StationRole(str, Enum):
    ESPRESSO = "ESPRESSO"
    BAR = "BAR"
    CATERING = "CATERING"


class BaristaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Tier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class Channel(str, Enum):
    MOBILE_APP = "MOBILE_APP"
    IN_STORE = "IN_STORE"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    VOIDED = "VOIDED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class Frequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class CateringStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    COUNTING = "COUNTING"
    CLOSED = "CLOSED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all entities carry common fields)
# --------------------------------------------------------------------------
class BeanLot(TypedDict):
    id: str
    origin: str
    roast_level: str
    received_grams: int
    consumed_grams: int
    waste_grams_total: int
    on_hand_grams: int
    par_grams: int
    price_per_gram_cents: int
    rotation_status: str
    reorder_needed: bool
    created_at: str
    updated_at: str
    version: int


class Modifier(TypedDict):
    id: str
    name: str
    modifier_group: str
    surcharge_cents: int
    extra_bean_grams: int
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    name: str
    category: str
    base_price_cents: int
    size: str
    required_equipment_type: str
    bean_grams: int
    origin_required: bool
    bean_origin: Optional[str]
    availability: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    name: str
    equipment_type: str
    status: str
    shots_since_calibration: int
    calibration_drift_pct: float
    needs_calibration: bool
    last_calibrated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict):
    id: str
    equipment_id: str
    start_at: str
    end_at: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Barista(TypedDict):
    id: str
    name: str
    station_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    status: str
    points_balance: int
    lifetime_points: int
    tier: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    member_id: Optional[str]
    channel: str
    lines: list
    points_redeemed: int
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    service_fee_cents: int
    discount_cents: int
    total_cents: int
    points_earned_provisional: int
    points_earned_final: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    bean_origin: str
    frequency: str
    bags_per_cycle: int
    next_ship_at: str
    price_per_cycle_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CateringEvent(TypedDict):
    id: str
    member_id: Optional[str]
    client_name: str
    assigned_equipment_id: str
    assigned_barista_id: str
    scheduled_start: str
    scheduled_end: str
    headcount: int
    travel_fee_cents: int
    quoted_total_cents: int
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyReconciliation(TypedDict):
    id: str
    business_date: str
    bean_lot_id: str
    status: str
    opening_bean_on_hand_grams: int
    opening_waste_grams: int
    counted_revenue_cents: Optional[int]
    counted_bean_on_hand_grams: Optional[int]
    expected_revenue_cents: int
    revenue_variance_cents: int
    ledger_usage_grams: int
    logged_waste_grams: int
    expected_usage_grams: int
    shrink_grams: int
    created_at: str
    updated_at: str
    version: int
