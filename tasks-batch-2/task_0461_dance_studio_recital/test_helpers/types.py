"""Domain types: entity TypedDicts, status enums, role enum for the Dance Studio Recital API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    STUDIO_ADMIN = "StudioAdmin"
    INSTRUCTOR = "Instructor"
    PARENT = "Parent"
    ANONYMOUS = "Anonymous"


# --- Status enums ---
class FamilyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"


class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class StudentLevel(str, Enum):
    PETITE = "PETITE"
    NOVICE = "NOVICE"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    ELITE = "ELITE"


class TermStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Discipline(str, Enum):
    BALLET = "BALLET"
    JAZZ = "JAZZ"
    TAP = "TAP"
    HIPHOP = "HIPHOP"
    CONTEMPORARY = "CONTEMPORARY"
    ACRO = "ACRO"


class ClassSectionStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FULL = "FULL"
    CANCELLED = "CANCELLED"


class PlacementStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    WAITLIST_PROMOTED = "WAITLIST_PROMOTED"
    DROPPED = "DROPPED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLING_ACTIVE = "BILLING_ACTIVE"
    BILLING_PAUSED = "BILLING_PAUSED"
    BILLING_ENDED = "BILLING_ENDED"


class AttendanceResult(str, Enum):
    PRESENT = "PRESENT"
    ABSENT_EXCUSED = "ABSENT_EXCUSED"
    ABSENT_UNEXCUSED = "ABSENT_UNEXCUSED"


class CostumeStatus(str, Enum):
    SIZING_OPEN = "SIZING_OPEN"
    ORDERED = "ORDERED"


class CostumeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"


class SizeCode(str, Enum):
    CHILD_S = "CHILD_S"
    CHILD_M = "CHILD_M"
    CHILD_L = "CHILD_L"
    ADULT_S = "ADULT_S"
    ADULT_M = "ADULT_M"
    ADULT_L = "ADULT_L"


class RecitalStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    ON_SALE = "ON_SALE"
    SOLD_OUT = "SOLD_OUT"
    COMPLETED = "COMPLETED"


class SeatStatus(str, Enum):
    HELD = "HELD"
    PURCHASED = "PURCHASED"
    RELEASED = "RELEASED"


class TeamStatus(str, Enum):
    FORMING = "FORMING"
    LOCKED = "LOCKED"


class MembershipStatus(str, Enum):
    ROSTERED = "ROSTERED"
    RELEASED = "RELEASED"


class TripStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class ParticipantStatus(str, Enum):
    GOING = "GOING"
    WITHDRAWN = "WITHDRAWN"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    VOID = "VOID"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class Family(TypedDict):
    id: str
    email: str
    family_name: str
    autopay_enabled: bool
    payment_method_on_file: bool
    account_credit_cents: int
    sibling_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    family_id: str
    full_name: str
    birth_date: str
    age_as_of_cutoff: int
    level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Term(TypedDict):
    id: str
    name: str
    start_date: str
    end_date: str
    age_cutoff_date: str
    monthly_billing_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    name: str
    capacity: int
    turnover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    email: str
    max_weekly_sessions: int
    created_at: str
    updated_at: str
    version: int


class ClassSection(TypedDict):
    id: str
    term_id: str
    room_id: str
    instructor_id: str
    discipline: str
    required_level: str
    min_age: int
    max_age: int
    monthly_tuition_cents: int
    capacity_cap: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    section_id: str
    day_of_week: int
    start_minute: int
    end_minute: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    section_id: str
    family_id: str
    placement_status: str
    billing_status: str
    waitlist_rank: int
    monthly_charge_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at (no updated_at, no version)
class Attendance(TypedDict):
    id: str
    enrollment_id: str
    session_id: str
    occurred_on: str
    result: str
    makeup_eligible: bool
    makeup_consumed: bool
    created_at: str


class Costume(TypedDict):
    id: str
    section_id: str
    name: str
    unit_price_cents: int
    size_window_close_date: str
    rush_surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CostumeOrder(TypedDict):
    id: str
    costume_id: str
    enrollment_id: str
    size_code: str
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Recital(TypedDict):
    id: str
    term_id: str
    name: str
    show_datetime: str
    total_seats: int
    ticket_price_cents: int
    free_tickets_per_family: int
    seats_sold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeatAssignment(TypedDict):
    id: str
    recital_id: str
    family_id: str
    seat_label: str
    is_complimentary: bool
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CompetitionTeam(TypedDict):
    id: str
    name: str
    min_level: str
    roster_cap: int
    roster_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TeamMembership(TypedDict):
    id: str
    team_id: str
    student_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TravelTrip(TypedDict):
    id: str
    team_id: str
    destination: str
    depart_date: str
    return_date: str
    per_member_cost_cents: int
    chaperone_ratio: int
    chaperone_count: int
    participant_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TripParticipant(TypedDict):
    id: str
    trip_id: str
    membership_id: str
    family_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    family_id: str
    term_id: str
    billing_month: str
    tuition_cents: int
    fees_cents: int
    credit_applied_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
