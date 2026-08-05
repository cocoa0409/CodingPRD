"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource model in the PRD. Two resource kinds are immutable
records that carry only ``id`` and ``created_at`` (a LedgerEntry and a
SurveyResponse); their TypedDicts deliberately omit ``updated_at`` and
``version``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum --------------------------------------------------------------
class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    RESIDENT = "Resident"
    VENDOR = "Vendor"
    FRONT_DESK = "FrontDesk"


# --- Status enums -----------------------------------------------------------
class UnitOccupancyStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"


class ResidentAccountStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class MembershipTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class AmenityType(str, Enum):
    GYM = "GYM"
    POOL = "POOL"
    CLUBROOM = "CLUBROOM"


class AmenityStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MAINTENANCE = "MAINTENANCE"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    SUSPENDED = "SUSPENDED"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class RegistrationStatus(str, Enum):
    RESERVED = "RESERVED"
    WAITLISTED = "WAITLISTED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServiceRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ServicePriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


class Trade(str, Enum):
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    APPLIANCE = "APPLIANCE"
    GENERAL = "GENERAL"


class PackageStatus(str, Enum):
    RECEIVED = "RECEIVED"
    NOTIFIED = "NOTIFIED"
    PICKED_UP = "PICKED_UP"
    RETURNED = "RETURNED"


class GuestPassStatus(str, Enum):
    ISSUED = "ISSUED"
    CHECKED_IN = "CHECKED_IN"
    DEPARTED = "DEPARTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LedgerEntryType(str, Enum):
    RENT_CHARGE = "RENT_CHARGE"
    BOOKING_FEE = "BOOKING_FEE"
    DEPOSIT_FORFEIT = "DEPOSIT_FORFEIT"
    EVENT_FEE = "EVENT_FEE"
    SERVICE_CHARGE = "SERVICE_CHARGE"
    PENALTY = "PENALTY"
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


# --- Entity TypedDicts (common_fields: true) --------------------------------
class Property(TypedDict):
    id: str
    name: str
    address: str
    timezone: str
    guest_parking_capacity: int
    guest_window_hours: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    property_id: str
    unit_number: str
    bedrooms: int
    occupancy_status: str
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    unit_id: str
    full_name: str
    email: str
    membership_tier: str
    account_status: str
    rent_balance_cents: int
    hold_balance_cents: int
    wallet_credit_cents: int
    no_show_strikes: int
    retention_score: int
    created_at: str
    updated_at: str
    version: int


class Amenity(TypedDict):
    id: str
    property_id: str
    name: str
    amenity_type: str
    capacity: int
    base_rate_cents_per_hour: int
    deposit_cents: int
    buffer_minutes: int
    open_minute: int
    close_minute: int
    peak_start_minute: int
    peak_end_minute: int
    peak_multiplier: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AmenityBooking(TypedDict):
    id: str
    amenity_id: str
    resident_id: str
    start_at: str
    end_at: str
    status: str
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    deposit_hold_cents: int
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommunityEvent(TypedDict):
    id: str
    property_id: str
    amenity_id: Optional[str]
    title: str
    start_at: str
    end_at: str
    capacity: int
    fee_cents: int
    status: str
    reserved_count: int
    waitlist_count: int
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict):
    id: str
    event_id: str
    resident_id: str
    status: str
    fee_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    trades: List[str]
    hourly_rate_cents: int
    active_job_limit: int
    active_job_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    unit_id: str
    resident_id: str
    vendor_id: Optional[str]
    trade: str
    priority: str
    description: str
    status: str
    estimated_cost_cents: Optional[int]
    final_invoice_cents: Optional[int]
    triaged_by_user_id: Optional[str]
    invoice_approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    resident_id: str
    carrier: str
    status: str
    access_code: str
    received_at: str
    picked_up_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuestPass(TypedDict):
    id: str
    resident_id: str
    guest_name: str
    arrival_at: str
    expected_departure_at: str
    status: str
    pass_code: str
    created_at: str
    updated_at: str
    version: int


class Survey(TypedDict):
    id: str
    property_id: str
    title: str
    status: str
    response_count: int
    created_at: str
    updated_at: str
    version: int


# --- Immutable records (common_fields: false) -------------------------------
class LedgerEntry(TypedDict):
    id: str
    resident_id: str
    entry_type: str
    amount_cents: int
    source_type: str
    source_id: str
    description: str
    created_at: str


class SurveyResponse(TypedDict):
    id: str
    survey_id: str
    resident_id: str
    satisfaction_score: int
    comment: Optional[str]
    created_at: str
