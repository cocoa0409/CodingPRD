"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources and lifecycles described in the Intercity Ticketing PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    SCHEDULE_MANAGER = "ScheduleManager"
    FARE_ANALYST = "FareAnalyst"
    PASSENGER = "Passenger"
    GATE_AGENT = "GateAgent"
    SUPPORT_AGENT = "SupportAgent"


# ─── Status / mode enums ──────────────────────────────
class OperatorMode(str, Enum):
    RAIL = "RAIL"
    BUS = "BUS"


class FareCode(str, Enum):
    ECONOMY = "ECONOMY"
    BUSINESS = "BUSINESS"


class SeatingMode(str, Enum):
    RESERVED = "RESERVED"
    OPEN = "OPEN"


class FareClassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class ServiceDateLifecycle(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class ServiceDateSales(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class FundingKind(str, Enum):
    CASH = "CASH"
    PASS = "PASS"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXCHANGED = "EXCHANGED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    CREDITED = "CREDITED"


class LegState(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class TicketState(str, Enum):
    ISSUED = "ISSUED"
    SCANNED = "SCANNED"
    VOID = "VOID"


class TravelPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class Accommodation(str, Enum):
    WHEELCHAIR_SPACE = "WHEELCHAIR_SPACE"
    COMPANION_SEAT = "COMPANION_SEAT"
    SERVICE_ANIMAL = "SERVICE_ANIMAL"


class AccessibilityStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class SettlementKind(str, Enum):
    CASH = "CASH"
    TRAVEL_CREDIT = "TRAVEL_CREDIT"


class RefundDestination(str, Enum):
    CASH = "CASH"
    TRAVEL_CREDIT = "TRAVEL_CREDIT"


# ─── Entity TypedDicts ────────────────────────────────
# Every entity below carries the full id/created_at/updated_at/version triple,
# EXCEPT RefundCreditNote (the settlement note), which is append-only and
# immutable: it carries only id + created_at (PRD §2.4).

class Operator(TypedDict):
    id: str
    name: str
    mode: str
    default_connection_buffer_min: int
    exchange_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class FareClass(TypedDict):
    id: str
    operator_id: str
    code: str
    seating_mode: str
    surcharge_cents: int
    refundable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    operator_id: str
    origin_code: str
    destination_code: str
    depart_minute_of_day: int
    arrive_minute_of_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceDate(TypedDict):
    id: str
    route_id: str
    departure_date: str
    seats_total: int
    base_fare_cents: int
    seats_held: int
    seats_sold: int
    seats_available: int
    load_factor: float
    lifecycle: str
    sales: str
    created_at: str
    updated_at: str
    version: int


class Passenger(TypedDict):
    id: str
    full_name: str
    email: str
    needs_accessibility: bool
    created_at: str
    updated_at: str
    version: int


class TravelPass(TypedDict):
    id: str
    passenger_id: str
    operator_id: str
    rides_total: int
    rides_consumed: int
    rides_remaining: int
    status: str
    expires_on: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    passenger_id: str
    booking_status: str
    payment_status: str
    funding_kind: str
    pass_id: Optional[str]
    total_fare_cents: int
    total_paid_cents: int
    hold_expires_at: str
    created_at: str
    updated_at: str
    version: int


class BookingLeg(TypedDict):
    id: str
    booking_id: str
    service_date_id: str
    fare_class_id: str
    leg_order: int
    seat_number: Optional[str]
    fare_cents: int
    leg_state: str
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    booking_id: str
    booking_leg_id: str
    barcode: str
    state: str
    created_at: str
    updated_at: str
    version: int


class BaggageItem(TypedDict):
    id: str
    booking_id: str
    weight_kg: float
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class AccessibilityRequest(TypedDict):
    id: str
    booking_leg_id: str
    accommodation: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only settlement note — common_fields:false. NO updated_at, NO version.
class RefundCreditNote(TypedDict):
    id: str
    booking_id: str
    settlement_kind: str
    gross_cents: int
    penalty_cents: int
    net_cents: int
    created_at: str
