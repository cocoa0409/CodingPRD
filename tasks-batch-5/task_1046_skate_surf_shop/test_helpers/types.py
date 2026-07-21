"""Domain types: entity TypedDicts, status enums, role enum.

All types reflect the Skate & Surf Shop PRD. Every entity is mutable and carries
id + created_at + updated_at + version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    ASSOCIATE = "Associate"
    INSTRUCTOR = "Instructor"
    MEMBER = "Member"


# --------------------------------------------------------------------------- enums
class ProductCategory(str, Enum):
    DECK = "DECK"
    TRUCK = "TRUCK"
    WHEELS = "WHEELS"
    BEARINGS = "BEARINGS"
    GRIP = "GRIP"
    WAX = "WAX"
    SURFBOARD = "SURFBOARD"
    ACCESSORY = "ACCESSORY"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class MemberTier(str, Enum):
    STANDARD = "STANDARD"
    PRO = "PRO"
    TEAM = "TEAM"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Discipline(str, Enum):
    SKATE = "SKATE"
    SURF = "SURF"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ServiceBayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RentalUnitKind(str, Enum):
    SKATEBOARD = "SKATEBOARD"
    SURFBOARD = "SURFBOARD"
    WETSUIT = "WETSUIT"


class RentalUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RETIRED = "RETIRED"


class BoardBuildStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPONENTS_RESERVED = "COMPONENTS_RESERVED"
    ASSEMBLED = "ASSEMBLED"
    SETUP_COMPLETE = "SETUP_COMPLETE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    GRIP = "GRIP"
    WHEEL = "WHEEL"
    WAX = "WAX"


class ServiceOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class RentalStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class LessonStatus(str, Enum):
    BOOKED = "BOOKED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TradeInStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPRAISED = "APPRAISED"
    CASH_SETTLED = "CASH_SETTLED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    RETURNED = "RETURNED"


class PayoutMethod(str, Enum):
    CASH = "CASH"
    STORE_CREDIT = "STORE_CREDIT"
    CONSIGNMENT = "CONSIGNMENT"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EventRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CANCELLED = "CANCELLED"


# ------------------------------------------------------------------------- entities
class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    unit_price_cents: int
    buildable_component: bool
    stock_on_hand: int
    stock_reserved: int
    reorder_threshold: int
    status: str
    stock_available: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    tier: str
    status: str
    points_balance: int
    lifetime_points: int
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict, total=False):
    id: str
    full_name: str
    discipline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict, total=False):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalUnit(TypedDict, total=False):
    id: str
    name: str
    kind: str
    daily_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardBuild(TypedDict, total=False):
    id: str
    member_id: str
    component_lines: List[dict]
    status: str
    provisional_total_cents: Optional[int]
    final_total_cents: Optional[int]
    reserved_at: Optional[str]
    assembled_at: Optional[str]
    setup_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict, total=False):
    id: str
    member_id: str
    bay_id: str
    build_id: Optional[str]
    service_type: str
    parts_lines: List[dict]
    slot_start: str
    slot_end: str
    status: str
    labor_total_cents: Optional[int]
    parts_total_cents: Optional[int]
    total_cents: Optional[int]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rental(TypedDict, total=False):
    id: str
    member_id: str
    unit_id: str
    lesson_id: Optional[str]
    start_date: str
    end_date: str
    deposit_cents: int
    status: str
    rental_total_cents: Optional[int]
    late_fee_cents: Optional[int]
    returned_on: Optional[str]
    checked_out_at: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lesson(TypedDict, total=False):
    id: str
    member_id: str
    instructor_id: str
    discipline: str
    start_at: str
    end_at: str
    fee_cents: int
    status: str
    confirmed_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict, total=False):
    id: str
    member_id: str
    description: str
    status: str
    appraised_value_cents: Optional[int]
    list_price_cents: Optional[int]
    payout_cents: Optional[int]
    payout_method: Optional[str]
    appraised_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict, total=False):
    id: str
    member_id: str
    product_name: str
    qty: int
    status: str
    quoted_price_cents: Optional[int]
    deposit_cents: Optional[int]
    quoted_at: Optional[str]
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    entry_points_cost: int
    status: str
    registration_count: int
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict, total=False):
    id: str
    event_id: str
    member_id: str
    status: str
    points_charged: int
    created_at: str
    updated_at: str
    version: int
