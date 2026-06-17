"""Domain types: entity TypedDicts, status enums, role enum (Photo Booth Rental API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enums ─────────────────────────────────────────────────────────────

class BoothType(str, Enum):
    OPEN_AIR = "OPEN_AIR"
    ENCLOSED = "ENCLOSED"
    MIRROR = "MIRROR"
    ROAMING_360 = "ROAMING_360"


class BoothStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class AttendantStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class AddOnCode(str, Enum):
    PROPS = "PROPS"
    BACKDROP = "BACKDROP"
    ATTENDANT = "ATTENDANT"
    ALBUM = "ALBUM"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class AttendantAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class GalleryStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    OPERATIONS_MANAGER = "OperationsManager"
    FINANCE_CLERK = "FinanceClerk"
    CUSTOMER = "Customer"
    ANONYMOUS = "Anonymous"


# ─── Entity TypedDicts ─────────────────────────────────────────────────
# Entities with common_fields: true carry id + created_at + updated_at + version.

class BoothModel(TypedDict):
    id: str
    name: str
    booth_type: str
    footprint_sqft: int
    max_prints_per_hour: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    booth_model_id: str
    name: str
    base_price: float
    included_hours: int
    included_prints: int
    overtime_rate_per_hour: float
    idle_rate_per_hour: float
    overage_print_rate: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class Booth(TypedDict):
    id: str
    booth_model_id: str
    asset_tag: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Attendant(TypedDict):
    id: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    home_zip: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    customer_id: str
    package_id: str
    booth_id: Optional[str]
    event_start: str
    event_end: str
    venue_distance_miles: int
    requested_setup_lead_min: int
    schedule_status: str
    payment_status: str
    quote_subtotal: float
    deposit_due: float
    balance_due: float
    travel_fee: float
    final_subtotal: Optional[float]
    amount_paid: float
    amount_refunded: float
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    code: str
    name: str
    unit_price: float
    requires_attendant: bool
    max_qty: int
    created_at: str
    updated_at: str
    version: int


class BookingAddOn(TypedDict):
    id: str
    booking_id: str
    add_on_id: str
    qty: int
    line_total: float
    created_at: str
    updated_at: str
    version: int


class AttendantAssignment(TypedDict):
    id: str
    booking_id: str
    attendant_id: str
    occupied_start: str
    occupied_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EventLog(TypedDict):
    id: str
    booking_id: str
    actual_setup_start: Optional[str]
    actual_coverage_start: Optional[str]
    actual_coverage_end: Optional[str]
    actual_teardown_end: Optional[str]
    actual_print_count: Optional[int]
    finalized: bool
    created_at: str
    updated_at: str
    version: int


class Gallery(TypedDict):
    id: str
    booking_id: str
    photo_count: int
    status: str
    access_pin: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only money event. Carries ONLY id + created_at.
class Payment(TypedDict):
    id: str
    booking_id: str
    kind: str
    amount: float
    created_at: str
