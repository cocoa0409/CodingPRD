"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Role enum (PRD §2.1) ─────────────────────────────
class UserRole(str, Enum):
    TRAVEL_MANAGER = "TravelManager"
    TRAVELER = "Traveler"
    APPROVER = "Approver"
    FINANCE_OFFICER = "FinanceOfficer"
    SYSTEM = "System"


# ─── Field enums ──────────────────────────────────────
class AirClass(str, Enum):
    ECONOMY = "ECONOMY"
    PREMIUM_ECONOMY = "PREMIUM_ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class Grade(str, Enum):
    STANDARD = "STANDARD"
    MANAGER = "MANAGER"
    EXECUTIVE = "EXECUTIVE"
    VIP = "VIP"


class VendorType(str, Enum):
    AIR = "AIR"
    HOTEL = "HOTEL"
    CAR = "CAR"


class SegmentType(str, Enum):
    AIR = "AIR"
    HOTEL = "HOTEL"
    CAR = "CAR"


class FareBasis(str, Enum):
    REFUNDABLE = "REFUNDABLE"
    NONREFUNDABLE = "NONREFUNDABLE"


class ApprovalLevel(str, Enum):
    NONE = "NONE"
    MANAGER = "MANAGER"
    EXEC = "EXEC"


# ─── Status enums (PRD §3 state machines) ─────────────
class TravelerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class NegotiatedRateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class TripRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_MANAGER = "PENDING_MANAGER"
    PENDING_EXEC = "PENDING_EXEC"
    APPROVED = "APPROVED"
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    TICKETED = "TICKETED"
    EXCHANGED = "EXCHANGED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class GroupBookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class CreditStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_USED = "PARTIALLY_USED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class MatchStatus(str, Enum):
    MATCHED = "MATCHED"
    PRICE_VARIANCE = "PRICE_VARIANCE"
    UNMATCHED = "UNMATCHED"


# ─── Entity TypedDicts ────────────────────────────────
# All top-level entities carry the full common-field set (PRD §2.4):
# id, created_at, updated_at, version.
class TravelPolicy(TypedDict):
    id: str
    name: str
    region: str
    max_air_class: str
    max_hotel_nightly_cents: int
    advance_purchase_days: int
    requires_manager_approval_over_cents: int
    requires_exec_approval_over_cents: int
    exchange_penalty_cents: int
    credit_validity_days: int
    created_at: str
    updated_at: str
    version: int


class Traveler(TypedDict):
    id: str
    full_name: str
    email: str
    grade: str
    policy_id: str
    home_iata: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    vendor_type: str
    is_preferred: bool
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NegotiatedRate(TypedDict):
    id: str
    vendor_id: str
    rate_code: str
    origin: str
    destination: str
    negotiated_fare_cents: int
    market_fare_cents: int
    cap_usage_count: int
    valid_from: str
    valid_to: str
    consumed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TripRequest(TypedDict):
    id: str
    traveler_id: str
    origin: str
    destination: str
    depart_date: str
    return_date: str
    purpose: str
    market_estimate_cents: int
    estimated_cost_cents: int
    actual_cost_cents: int
    approval_level_required: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    trip_request_id: str
    traveler_id: str
    vendor_id: str
    negotiated_rate_id: Optional[str]
    segment_type: str
    fare_basis: str
    fare_cents: int
    credit_applied_cents: int
    exchange_fee_cents: int
    depart_datetime: str
    return_datetime: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GroupBooking(TypedDict):
    id: str
    vendor_id: str
    organizer_traveler_id: str
    block_size: int
    confirmed_count: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UnusedTicketCredit(TypedDict):
    id: str
    traveler_id: str
    origin_booking_id: str
    vendor_id: str
    redeemed_by_booking_id: Optional[str]
    face_value_cents: int
    residual_value_cents: int
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    vendor_id: str
    billing_period: str
    invoiced_total_cents: int
    reconciled_total_cents: int
    variance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    id: str
    invoice_id: str
    booking_id: Optional[str]
    billed_amount_cents: int
    matched_amount_cents: int
    match_status: str
    created_at: str
    updated_at: str
    version: int
