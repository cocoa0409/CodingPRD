"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    OPS_MANAGER = "OpsManager"
    SALES_AGENT = "SalesAgent"
    FINANCE = "Finance"
    AUDITOR = "Auditor"


class DepartureStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    GUARANTEED = "GUARANTEED"
    DEPARTED = "DEPARTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class OccupancyBand(str, Enum):
    SMALL = "SMALL"
    STANDARD = "STANDARD"
    LARGE = "LARGE"


class ReservationStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    TRAVELED = "TRAVELED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class ResourceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"


class HotelBlockStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    VOIDED = "VOIDED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


# ---- Entities carrying common fields (id + created_at + updated_at + version) ----

class TourProduct(TypedDict):
    id: str
    name: str
    duration_days: int
    base_price_per_person_cents: int
    deposit_per_person_cents: int
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict):
    id: str
    code: str
    seat_capacity: int
    day_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    name: str
    license_no: str
    day_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Guide(TypedDict):
    id: str
    name: str
    day_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Departure(TypedDict):
    id: str
    tour_product_id: str
    name: str
    start_date: str
    end_date: str
    guaranteed_min_pax: int
    itinerary_days: list
    coach_id: Optional[str]
    driver_id: Optional[str]
    guide_id: Optional[str]
    status: str
    confirmed_pax: int
    occupancy_band: str
    settlement_net_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class HotelBlock(TypedDict):
    id: str
    departure_id: str
    hotel_name: str
    city: str
    room_count: int
    nights: int
    rate_per_room_night_cents: int
    rooms_committed: int
    status: str
    block_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    departure_id: str
    lead_name: str
    pax_count: int
    rooms_requested: int
    insurance_opt_in: bool
    reservation_status: str
    payment_status: str
    quoted_per_person_cents: int
    final_per_person_cents: Optional[int]
    base_subtotal_cents: int
    service_fee_cents: int
    insurance_premium_cents: int
    booking_total_cents: int
    deposit_due_cents: int
    amount_paid_cents: int
    amount_refunded_cents: int
    penalty_charged_cents: Optional[int]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Passenger(TypedDict):
    id: str
    booking_id: str
    full_name: str
    is_lead: bool
    roommate_passenger_id: Optional[str]
    seat_no: Optional[int]
    room_no: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict):
    id: str
    booking_id: str
    passenger_id: str
    kind: str
    face_value_cents: int
    status: str
    redeemed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---- Append-only ledger record (id + created_at only) ----

class Payment(TypedDict):
    id: str
    booking_id: str
    kind: str
    amount_cents: int
    method: Optional[str]
    created_at: str
