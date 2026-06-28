"""Domain types for the Banquet Event Order API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status / enum domains
# ---------------------------------------------------------------------------
class EventStatus(str, Enum):
    INQUIRY = "INQUIRY"
    TENTATIVE = "TENTATIVE"
    DEFINITE = "DEFINITE"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingHoldStatus(str, Enum):
    HOLD = "HOLD"
    DEFINITE = "DEFINITE"
    RELEASED = "RELEASED"


class RoomBlockLinkStatus(str, Enum):
    RESERVED = "RESERVED"
    PICKED_UP = "PICKED_UP"
    RELEASED = "RELEASED"


class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class FunctionRoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SetupStyle(str, Enum):
    ROUNDS = "ROUNDS"
    THEATER = "THEATER"
    CLASSROOM = "CLASSROOM"
    RECEPTION = "RECEPTION"


class PricingMode(str, Enum):
    PER_PERSON = "PER_PERSON"
    CONSUMPTION = "CONSUMPTION"


class ServiceCategory(str, Enum):
    AV = "AV"
    LABOR = "LABOR"
    RENTAL_ITEM = "RENTAL_ITEM"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    CHECK = "CHECK"
    WIRE = "WIRE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_MANAGER = "SalesManager"
    BANQUET_CAPTAIN = "BanquetCaptain"
    ACCOUNTING_CLERK = "AccountingClerk"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Entities carrying common fields expose id, created_at, updated_at, version.
# Payment is the append-only log: it carries ONLY id + created_at (no updated_at,
# no version) per PRD §2.4.
# ---------------------------------------------------------------------------
class FunctionRoom(TypedDict):
    id: str
    name: str
    max_capacity: int
    turnover_buffer_minutes: int
    hourly_rental_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HotelRoomBlock(TypedDict):
    id: str
    block_name: str
    total_rooms: int
    nightly_rate_cents: int
    rooms_committed: int
    rooms_available: int
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    account_name: str
    event_date: str
    setup_style: str
    expected_attendance: int
    guarantee_count: Optional[int]
    actual_attendance: Optional[int]
    overset_pct: float
    service_charge_pct: float
    gratuity_pct: float
    sales_tax_pct: float
    status: str
    billable_count: int
    estimated_total_cents: int
    actualized_total_cents: Optional[int]
    paid_to_date_cents: int
    balance_due_cents: int
    created_at: str
    updated_at: str
    version: int


class FunctionRoomBooking(TypedDict):
    id: str
    event_id: str
    function_room_id: str
    start_utc: str
    end_utc: str
    setup_diagram_url: Optional[str]
    hold_status: str
    rental_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class MenuLine(TypedDict):
    id: str
    event_id: str
    name: str
    pricing_mode: str
    unit_price_cents: int
    consumption_qty: Optional[int]
    extended_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceLine(TypedDict):
    id: str
    event_id: str
    category: str
    description: str
    quantity: int
    unit_price_cents: int
    gratuity_eligible: bool
    extended_cents: int
    created_at: str
    updated_at: str
    version: int


class RoomBlockLink(TypedDict):
    id: str
    event_id: str
    hotel_room_block_id: str
    rooms_reserved: int
    check_in_date: str
    check_out_date: str
    rooms_picked_up: Optional[int]
    link_status: str
    created_at: str
    updated_at: str
    version: int


class PaymentScheduleItem(TypedDict):
    id: str
    event_id: str
    label: str
    due_date: str
    amount_due_cents: int
    sequence_no: int
    allocated_cents: int
    settled: bool
    created_at: str
    updated_at: str
    version: int


# Payment: common_fields:false — append-only, only id + created_at (no version/updated_at).
class Payment(TypedDict):
    id: str
    created_at: str
    event_id: str
    amount_cents: int
    method: str
    status: str
