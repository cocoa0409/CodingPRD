"""Domain types: entity TypedDicts, status enums, and the role enum for the
Wedding & Event Planning API (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    PLANNER = "Planner"
    CLIENT = "Client"
    VENDOR = "Vendor"


# --- Status enums (PRD §3) ---
class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKING = "BOOKING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    SIGNED = "SIGNED"
    COUNTERSIGNED = "COUNTERSIGNED"
    VOID = "VOID"


class COIStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class VendorBookingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VendorPaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    VOID = "VOID"


class GuestRsvpStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


# --- Enumerated input value sets ---
class PackageType(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    DAY_OF = "DAY_OF"


class VendorCategory(str, Enum):
    CATERING = "CATERING"
    FLORAL = "FLORAL"
    RENTAL = "RENTAL"
    PHOTO = "PHOTO"
    VENUE = "VENUE"
    STAFFING = "STAFFING"
    OTHER = "OTHER"


class MealChoice(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    VEGETARIAN = "VEGETARIAN"
    VEGAN = "VEGAN"
    KIDS = "KIDS"


class PaymentType(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"


class TimelineZone(str, Enum):
    CEREMONY_SPACE = "CEREMONY_SPACE"
    RECEPTION_HALL = "RECEPTION_HALL"
    KITCHEN = "KITCHEN"
    LOADING_DOCK = "LOADING_DOCK"
    SUITE = "SUITE"


class BlockType(str, Enum):
    LOAD_IN = "LOAD_IN"
    SETUP = "SETUP"
    CEREMONY = "CEREMONY"
    COCKTAIL = "COCKTAIL"
    RECEPTION = "RECEPTION"
    TEARDOWN = "TEARDOWN"


class StaffRole(str, Enum):
    COORDINATOR = "COORDINATOR"
    SERVER = "SERVER"
    BARTENDER = "BARTENDER"
    SECURITY = "SECURITY"
    RUNNER = "RUNNER"


# --- Entity TypedDicts ---
# Every resource carries the full audit quad: id + created_at + updated_at +
# version (PRD §2.4).
class EventProject(TypedDict):
    id: str
    couple_names: str
    event_date: str
    venue_name: str
    package_type: str
    total_budget_cents: int
    guest_count_estimate: int
    active_contract_id: Optional[str]
    committed_spend_cents: int
    projected_spend_cents: int
    budget_balance_cents: int
    total_deposits_due_cents: int
    estimated_headcount: int
    confirmed_headcount: int
    cancellation_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    event_id: str
    package_type: str
    planner_fee_cents: int
    revision_count: int
    signed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    category: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class COI(TypedDict):
    id: str
    vendor_id: str
    policy_number: str
    coverage_amount_cents: int
    coverage_expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorBooking(TypedDict):
    id: str
    event_id: str
    vendor_id: str
    service_description: str
    estimated_cost_cents: int
    contracted_cost_cents: Optional[int]
    deposit_cents: Optional[int]
    balance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorPayment(TypedDict):
    id: str
    vendor_booking_id: str
    payment_type: str
    amount_cents: int
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TimelineBlock(TypedDict):
    id: str
    event_id: str
    label: str
    zone: str
    block_type: str
    start_offset_min: int
    end_offset_min: int
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    event_id: str
    guest_name: str
    party_size: int
    meal_choice: str
    rsvp_status: str
    created_at: str
    updated_at: str
    version: int


class Table(TypedDict):
    id: str
    event_id: str
    table_label: str
    capacity: int
    occupied_seats: int
    created_at: str
    updated_at: str
    version: int


class SeatAssignment(TypedDict):
    id: str
    event_id: str
    guest_id: str
    table_id: str
    seats_used: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    event_id: str
    staff_name: str
    role_title: str
    hourly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    event_id: str
    staff_member_id: str
    shift_start_offset_min: int
    shift_end_offset_min: int
    labor_cost_cents: int
    created_at: str
    updated_at: str
    version: int
