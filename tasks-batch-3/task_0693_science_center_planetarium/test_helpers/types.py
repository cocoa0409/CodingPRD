"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Status enums ---

class VenueType(str, Enum):
    DOME = "DOME"
    THEATER = "THEATER"
    GALLERY = "GALLERY"
    CLASSROOM = "CLASSROOM"
    RENTAL_HALL = "RENTAL_HALL"


class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"


class MembershipTier(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FAMILY = "FAMILY"
    PATRON = "PATRON"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ShowEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    SOLD_OUT = "SOLD_OUT"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ShowBookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class GroupBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class ProgramKind(str, Enum):
    CAMP = "CAMP"
    CLASS = "CLASS"


class ProgramSessionStatus(str, Enum):
    ENROLLING = "ENROLLING"
    FULL = "FULL"
    STARTED = "STARTED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class RentalEventStatus(str, Enum):
    INQUIRY = "INQUIRY"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class SponsorKind(str, Enum):
    DONOR = "DONOR"
    SPONSOR = "SPONSOR"


class SponsorStatus(str, Enum):
    PLEDGED = "PLEDGED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    LAPSED = "LAPSED"


class ContributionStatus(str, Enum):
    RECEIVED = "RECEIVED"


class AccommodationSubjectType(str, Enum):
    SHOW_BOOKING = "SHOW_BOOKING"
    REGISTRATION = "REGISTRATION"
    RENTAL = "RENTAL"


class AccommodationKind(str, Enum):
    WHEELCHAIR = "WHEELCHAIR"
    ASL_INTERPRETER = "ASL_INTERPRETER"
    SENSORY_FRIENDLY = "SENSORY_FRIENDLY"
    ASSISTIVE_LISTENING = "ASSISTIVE_LISTENING"


class AccommodationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FULFILLED = "FULFILLED"


class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    BOX_OFFICE_OPERATOR = "BoxOfficeOperator"
    GROUP_SALES_AGENT = "GroupSalesAgent"
    MEMBERSHIP_CLERK = "MembershipClerk"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    EVENTS_MANAGER = "EventsManager"
    DEVELOPMENT_OFFICER = "DevelopmentOfficer"
    ACCESSIBILITY_COORDINATOR = "AccessibilityCoordinator"


# --- Entity TypedDicts ---
# Entities carrying common_fields: id, created_at, updated_at, version.

class Venue(TypedDict):
    id: str
    name: str
    venue_type: str
    seated_capacity: int
    turnover_buffer_minutes: int
    accessible_seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    primary_member_name: str
    tier: str
    astc_eligible: bool
    home_zip: str
    party_size: int
    status: str
    activated_at: Optional[str]
    expires_at: Optional[str]
    dues_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class ShowEvent(TypedDict):
    id: str
    venue_id: str
    title: str
    starts_at: str
    ends_at: str
    base_price_cents: int
    feature_surcharge_cents: int
    seats_sold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShowBooking(TypedDict):
    id: str
    show_event_id: str
    membership_id: Optional[str]
    party_size: int
    accessible_seats_requested: int
    gross_price_cents: int
    member_discount_cents: int
    net_price_cents: int
    expected_show_version: int
    status: str
    held_at: str
    created_at: str
    updated_at: str
    version: int


class GroupBooking(TypedDict):
    id: str
    show_event_id: str
    organization_name: str
    student_count: int
    chaperone_count: int
    actual_student_count: Optional[int]
    actual_chaperone_count: Optional[int]
    total_seats: int
    deposit_cents: int
    balance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramSession(TypedDict):
    id: str
    venue_id: str
    title: str
    program_kind: str
    min_age: int
    max_age: int
    starts_at: str
    capacity: int
    tuition_cents: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    program_session_id: str
    membership_id: Optional[str]
    participant_name: str
    participant_age: int
    tuition_charged_cents: Optional[int]
    waitlist_position: Optional[int]
    expected_session_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalEvent(TypedDict):
    id: str
    venue_id: str
    host_name: str
    starts_at: str
    ends_at: str
    guest_count: int
    actual_guest_count: Optional[int]
    base_rental_cents: int
    deposit_cents: int
    total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict):
    id: str
    org_name: str
    sponsor_kind: str
    pledged_cents: int
    received_cents: int
    fulfillment_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Contribution carries common_fields: false — append-only, ONLY id + created_at.
class Contribution(TypedDict):
    id: str
    sponsor_id: str
    amount_cents: int
    expected_sponsor_version: int
    status: str
    created_at: str


class AccommodationRequest(TypedDict):
    id: str
    subject_type: str
    show_booking_id: Optional[str]
    registration_id: Optional[str]
    rental_event_id: Optional[str]
    accommodation_kind: str
    status: str
    created_at: str
    updated_at: str
    version: int
