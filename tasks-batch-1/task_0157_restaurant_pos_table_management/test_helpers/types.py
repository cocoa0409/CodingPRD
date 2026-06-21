"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources described in the Restaurant POS PRD. Entities that carry
the full id/created_at/updated_at/version set are distinguished from the two
immutable line-detail records (item modifier, tip allocation) which carry only
id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    MANAGER = "Manager"
    SERVER = "Server"
    HOST = "Host"
    KITCHEN_STAFF = "KitchenStaff"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class TableOccupancyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SEATED = "SEATED"
    DIRTY = "DIRTY"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    SEATED = "SEATED"
    CANCELLED = "CANCELLED"


class SeatingStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"


class CheckStatus(str, Enum):
    OPEN = "OPEN"
    PRESENTED = "PRESENTED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class CourseStatus(str, Enum):
    BUILDING = "BUILDING"
    FIRED = "FIRED"


class OrderItemStatus(str, Enum):
    PENDING = "PENDING"
    FIRED = "FIRED"
    SERVED = "SERVED"
    VOIDED = "VOIDED"
    COMPED = "COMPED"


class TipPoolStatus(str, Enum):
    ACCUMULATING = "ACCUMULATING"
    DISTRIBUTED = "DISTRIBUTED"


class PaymentStatus(str, Enum):
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class Station(str, Enum):
    GRILL = "GRILL"
    FRY = "FRY"
    SAUTE = "SAUTE"
    COLD = "COLD"
    BAR = "BAR"
    EXPO = "EXPO"


class StaffRole(str, Enum):
    SERVER = "SERVER"
    BARTENDER = "BARTENDER"
    BUSSER = "BUSSER"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    GIFT = "GIFT"


class DistributionMode(str, Enum):
    EVEN_BY_HOURS = "EVEN_BY_HOURS"
    WEIGHTED_BY_ROLE = "WEIGHTED_BY_ROLE"


# ---------------------------------------------------------------------------
# Entity TypedDicts — full common-field set (id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Restaurant(TypedDict):
    id: str
    name: str
    tax_rate_bps: int
    large_party_threshold: int
    auto_gratuity_bps: int
    comp_cap_bps: int
    min_rest_minutes: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    restaurant_id: str
    name: str
    station: str
    base_price_cents: int
    happy_hour_price_cents: int
    initial_available_count: int
    available_count: int
    is_86: bool
    created_at: str
    updated_at: str
    version: int


class HappyHourWindow(TypedDict):
    id: str
    restaurant_id: str
    day_of_week: int
    start_minute: int
    end_minute: int
    created_at: str
    updated_at: str
    version: int


class DiningTable(TypedDict):
    id: str
    restaurant_id: str
    table_number: str
    capacity: int
    occupancy_status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    restaurant_id: str
    party_name: str
    party_size: int
    status: str
    quoted_at: str
    seating_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Seating(TypedDict):
    id: str
    restaurant_id: str
    table_id: str
    waitlist_entry_id: Optional[str]
    party_size: int
    status: str
    seated_at: str
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Check(TypedDict):
    id: str
    restaurant_id: str
    seating_id: str
    server_staff_id: str
    party_size: int
    status: str
    provisional_subtotal_cents: int
    final_subtotal_cents: Optional[int]
    comp_total_cents: int
    auto_gratuity_cents: int
    tax_cents: int
    total_due_cents: int
    amount_paid_cents: int
    tip_cents: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    restaurant_id: str
    check_id: str
    course_number: int
    status: str
    fired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderItem(TypedDict):
    id: str
    restaurant_id: str
    course_id: str
    menu_item_id: str
    quantity: int
    status: str
    unit_price_cents: Optional[int]
    line_subtotal_cents: Optional[int]
    comp_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    restaurant_id: str
    name: str
    role: str
    tip_weight_bps: int
    created_at: str
    updated_at: str
    version: int


class StaffShift(TypedDict):
    id: str
    restaurant_id: str
    staff_id: str
    business_date: str
    clock_in_minute: int
    clock_out_minute: int
    hours_worked_x100: int
    created_at: str
    updated_at: str
    version: int


class TipPool(TypedDict):
    id: str
    restaurant_id: str
    business_date: str
    distribution_mode: str
    status: str
    pooled_cents: int
    distributed_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    restaurant_id: str
    check_id: str
    amount_cents: int
    tip_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable line-detail records — id + created_at only (no updated_at/version)
# ---------------------------------------------------------------------------
class ItemModifier(TypedDict):
    id: str
    restaurant_id: str
    order_item_id: str
    name: str
    surcharge_cents: int
    created_at: str


class TipAllocation(TypedDict):
    id: str
    restaurant_id: str
    tip_pool_id: str
    staff_shift_id: str
    amount_cents: int
    created_at: str
