"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the Scuba Dive Certification API contract exactly.
Entities that are immutable once created (CertificationCard, Waiver) carry only
id + created_at — no updated_at, no version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Enums -----------------------------------------------------------------

class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    INSTRUCTOR = "Instructor"
    DIVER = "Diver"


class CertLevel(str, Enum):
    NONE = "NONE"
    OPEN_WATER = "OPEN_WATER"
    ADVANCED = "ADVANCED"


class MedicalStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"


class InstructorRating(str, Enum):
    DIVEMASTER = "DIVEMASTER"
    INSTRUCTOR = "INSTRUCTOR"


class CourseType(str, Enum):
    OPEN_WATER = "OPEN_WATER"
    ADVANCED = "ADVANCED"


class Specialty(str, Enum):
    NONE = "NONE"
    ENRICHED_AIR = "ENRICHED_AIR"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ELIGIBLE = "ELIGIBLE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class SessionType(str, Enum):
    POOL = "POOL"
    OPEN_WATER = "OPEN_WATER"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SessionBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    ATTENDED = "ATTENDED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class DiveTripStatus(str, Enum):
    OPEN = "OPEN"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class TripBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    DEPARTED = "DEPARTED"


class RentalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    VOIDED = "VOIDED"


class Gas(str, Enum):
    AIR = "AIR"
    NITROX = "NITROX"


class ServiceType(str, Enum):
    VIP = "VIP"
    HYDRO = "HYDRO"


class GearServiceStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts -----------------------------------------------------

class Diver(TypedDict):
    id: str
    full_name: str
    email: str
    cert_level: str
    nitrox_certified: bool
    medical_status: str
    deposit_on_hold_cents: int
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    rating: str
    active_session_count: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    title: str
    course_type: str
    required_pool_sessions: int
    required_open_water_sessions: int
    price_cents: int
    grants_specialty: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    diver_id: str
    course_id: str
    status: str
    elearning_pct: int
    pool_sessions_attended: int
    open_water_sessions_attended: int
    completion_pct: int
    certification_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    course_id: str
    session_type: str
    primary_instructor_id: str
    assistant_count: int
    starts_at: str
    ends_at: str
    max_students: int
    confirmed_seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionBooking(TypedDict):
    id: str
    session_id: str
    enrollment_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable — common_fields: false (id + created_at only)
class CertificationCard(TypedDict):
    id: str
    diver_id: str
    enrollment_id: str
    level: str
    specialty: str
    issued_at: str
    created_at: str


# Immutable — common_fields: false (id + created_at only)
class Waiver(TypedDict):
    id: str
    diver_id: str
    medical_flagged: bool
    signed_at: str
    expires_at: str
    created_at: str


class Boat(TypedDict):
    id: str
    name: str
    capacity: int
    turnaround_minutes: int
    created_at: str
    updated_at: str
    version: int


class DiveTrip(TypedDict):
    id: str
    boat_id: str
    starts_at: str
    ends_at: str
    min_cert_level: str
    base_fare_cents: int
    fill_addon_cents: int
    confirmed_divers: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TripBooking(TypedDict):
    id: str
    trip_id: str
    diver_id: str
    tanks: int
    party_size: int
    total_cents: int
    deposit_cents: int
    balance_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict):
    id: str
    diver_id: str
    item_description: str
    daily_rate_cents: int
    deposit_cents: int
    checkout_at: str
    scheduled_return_at: str
    actual_return_at: Optional[str]
    damage_fee_cents: int
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    deposit_refund_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FillService(TypedDict):
    id: str
    diver_id: str
    gas: str
    o2_pct: int
    tank_capacity_liters: int
    price_cents: int
    created_at: str
    updated_at: str
    version: int


class GearServiceOrder(TypedDict):
    id: str
    diver_id: str
    service_type: str
    serviced_at: Optional[str]
    next_due_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
