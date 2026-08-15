"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    CLUB_ADMIN = "ClubAdmin"
    MEMBER = "Member"
    DUTY_OFFICER = "DutyOfficer"
    INSTRUCTOR = "Instructor"
    TOW_PILOT = "TowPilot"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RESIGNED = "RESIGNED"


class SuspensionReason(str, Enum):
    ARREARS = "ARREARS"
    MANUAL = "MANUAL"


class BadgeLevel(str, Enum):
    NONE = "NONE"
    A = "A"
    B = "B"
    C = "C"
    BRONZE = "BRONZE"
    SILVER = "SILVER"


class AircraftKind(str, Enum):
    GLIDER = "GLIDER"
    TOW_PLANE = "TOW_PLANE"


class AircraftStatus(str, Enum):
    AIRWORTHY = "AIRWORTHY"
    GROUNDED = "GROUNDED"
    RETIRED = "RETIRED"


class GroundedReason(str, Enum):
    INSPECTION_OVERDUE = "INSPECTION_OVERDUE"
    ANNUAL_OVERDUE = "ANNUAL_OVERDUE"
    MANUAL = "MANUAL"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_OUT = "CHECKED_OUT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class FlightStatus(str, Enum):
    IN_FLIGHT = "IN_FLIGHT"
    LANDED = "LANDED"
    RECONCILED = "RECONCILED"
    VOIDED = "VOIDED"


class TowSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class DutySlotStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    SWAP_PENDING = "SWAP_PENDING"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AvailabilityStatus(str, Enum):
    OPEN = "OPEN"
    CANCELLED = "CANCELLED"


class MaintenanceKind(str, Enum):
    INSPECTION_100H = "INSPECTION_100H"
    ANNUAL = "ANNUAL"
    REPAIR = "REPAIR"


class ProgressKind(str, Enum):
    SOLO_SIGNOFF = "SOLO_SIGNOFF"
    CHECKRIDE_PASS = "CHECKRIDE_PASS"
    BADGE_A = "BADGE_A"
    BADGE_B = "BADGE_B"
    BADGE_C = "BADGE_C"
    BADGE_BRONZE = "BADGE_BRONZE"
    BADGE_SILVER = "BADGE_SILVER"


class ProgressStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED_OFF = "SIGNED_OFF"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RetrieveStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CREW_ASSIGNED = "CREW_ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MembershipTier(TypedDict):
    id: str
    tier_code: str
    monthly_dues_cents: int
    tow_fee_discount_pct: float
    included_tows_per_month: int
    student_tier: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    tier_id: str
    status: str
    is_instructor: bool
    is_tow_pilot: bool
    account_balance_cents: int
    pending_dues_cents: int
    suspension_reason: Optional[str]
    solo_endorsed: bool
    badge_level: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    registration: str
    kind: str
    status: str
    total_time_hours: float
    hours_since_inspection: float
    annual_due_date: str
    grounded_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DutyRosterSlot(TypedDict):
    id: str
    duty_date: str
    member_id: str
    status: str
    swap_with_slot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstructorAvailability(TypedDict):
    id: str
    instructor_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    aircraft_id: str
    member_id: str
    instructor_id: Optional[str]
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict):
    id: str
    reservation_id: str
    tow_slot_id: str
    release_altitude_ft: int
    takeoff_at: str
    landed_at: Optional[str]
    status: str
    flight_minutes: Optional[int]
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    retrieve_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TowSlot(TypedDict):
    id: str
    tow_plane_id: str
    tow_pilot_id: str
    start_at: str
    end_at: str
    capacity: int
    confirmed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only maintenance log entry (PRD §2.4): carries ONLY id + created_at.
class MaintenanceRecord(TypedDict):
    id: str
    aircraft_id: str
    kind: str
    performed_at: str
    hobbs_hours_at_service: float
    notes: Optional[str]
    created_at: str


class StudentProgress(TypedDict):
    id: str
    student_id: str
    instructor_id: str
    kind: str
    status: str
    dual_hours_at_signoff: Optional[float]
    signed_off_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetrieveRequest(TypedDict):
    id: str
    flight_id: str
    distance_km: float
    status: str
    pilot_share_cents: int
    club_share_cents: int
    crew_member_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
