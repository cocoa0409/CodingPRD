"""Domain types: entity TypedDicts, status enums, role enum.

Most entities carry the common bookkeeping fields id, created_at, updated_at,
and an integer version (PRD 2.4). Room and Vehicle are lightweight reference
resources that carry only id and created_at — no updated_at and no version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    CENTER_ADMIN = "CenterAdmin"
    COORDINATOR = "Coordinator"
    PARTICIPANT = "Participant"
    AUDITOR = "Auditor"


# --- Status / enum value sets ---
class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class GrantAwardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FundedServiceStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class FundingStatus(str, Enum):
    FUNDED = "FUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    UNFUNDED = "UNFUNDED"


class ActivitySessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class ActivitySignupStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"


class TripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class MealServiceDayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MealReservationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    CHECKED_IN = "CHECKED_IN"


class WellnessEnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"


class ProjectedGraduationStatus(str, Enum):
    WILL_GRADUATE = "WILL_GRADUATE"
    AT_RISK = "AT_RISK"


class ServiceCategory(str, Enum):
    CONGREGATE_MEAL = "CONGREGATE_MEAL"
    TRANSPORTATION = "TRANSPORTATION"
    WELLNESS = "WELLNESS"
    ACTIVITY = "ACTIVITY"


# --- Entity TypedDicts ---
# common_fields: true — id + created_at + updated_at + version
class Participant(TypedDict):
    id: str
    full_name: str
    birth_date: str
    gender: str
    ethnicity: str
    race: str
    poverty_status: str
    lives_alone: bool
    rural: bool
    veteran: bool
    disability_count: int
    status: str
    funded_cents: int
    age: int
    created_at: str
    updated_at: str
    version: int


class GrantAward(TypedDict):
    id: str
    title: str
    oaa_title: str
    category: str
    authorized_cents: int
    committed_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    donor_name: str
    category: str
    amount_cents: int
    remaining_cents: int
    restricted: bool
    created_at: str
    updated_at: str
    version: int


class FundedService(TypedDict):
    id: str
    participant_id: str
    category: str
    quantity: int
    service_date: str
    grant_award_id: str
    donation_id: Optional[str]
    billable_cents: int
    grant_amount_cents: int
    donation_amount_cents: int
    unfunded_amount_cents: int
    funding_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ActivitySession(TypedDict):
    id: str
    title: str
    category: str
    room_id: str
    starts_at: str
    ends_at: str
    capacity: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ActivitySignup(TypedDict):
    id: str
    session_id: str
    participant_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportationRequest(TypedDict):
    id: str
    participant_id: str
    vehicle_id: str
    linked_session_id: str
    starts_at: str
    ends_at: str
    eligibility_status: str
    trip_status: str
    created_at: str
    updated_at: str
    version: int


class MealServiceDay(TypedDict):
    id: str
    service_date: str
    site_name: str
    capacity: int
    reserved_count: int
    available_seats: int
    served_count: int
    provisional_reimbursable_units: int
    final_reimbursable_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MealReservation(TypedDict):
    id: str
    service_day_id: str
    participant_id: str
    suggested_contribution_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WellnessProgram(TypedDict):
    id: str
    title: str
    model: str
    total_sessions: int
    fidelity_min_sessions: int
    created_at: str
    updated_at: str
    version: int


class WellnessEnrollment(TypedDict):
    id: str
    program_id: str
    participant_id: str
    sessions_attended: int
    consecutive_absences: int
    absences_total: int
    projected_graduation_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerShift(TypedDict):
    id: str
    volunteer_name: str
    role: str
    hours: float
    service_date: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — id + created_at only (no updated_at, no version)
class Room(TypedDict):
    id: str
    name: str
    capacity: int
    created_at: str


class Vehicle(TypedDict):
    id: str
    name: str
    seat_capacity: int
    created_at: str
