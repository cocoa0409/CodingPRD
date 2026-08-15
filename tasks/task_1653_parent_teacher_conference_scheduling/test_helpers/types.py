"""Domain types: entity TypedDicts, status enums, role enum (PRD 2.1, 2.5)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SCHOOL_ADMIN = "SchoolAdmin"
    FRONT_OFFICE_STAFF = "FrontOfficeStaff"
    TEACHER = "Teacher"
    FAMILY_GUARDIAN = "FamilyGuardian"
    INTERPRETER = "Interpreter"


class WindowStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    BOOKING_OPEN = "BOOKING_OPEN"
    LOCKED = "LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class WindowFormat(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    SECONDARY = "SECONDARY"


class TeacherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class GradeBand(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    SECONDARY = "SECONDARY"
    BOTH = "BOTH"


class FamilyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    HELD = "HELD"
    BOOKED = "BOOKED"
    RETIRED = "RETIRED"


class ChannelAllowed(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"
    EITHER = "EITHER"


class Channel(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    EXCUSED = "EXCUSED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"


class CancelReason(str, Enum):
    FAMILY_REQUEST = "FAMILY_REQUEST"
    STAFF_REQUEST = "STAFF_REQUEST"
    TEACHER_INACTIVE = "TEACHER_INACTIVE"
    FAMILY_RESTRICTED = "FAMILY_RESTRICTED"
    STUDENT_WITHDRAWN = "STUDENT_WITHDRAWN"
    RESCHEDULED = "RESCHEDULED"


class BookedByRole(str, Enum):
    FAMILY_SELF = "FAMILY_SELF"
    FRONT_OFFICE = "FRONT_OFFICE"


class InterpreterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    UNFILLED = "UNFILLED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    EXHAUSTED = "EXHAUSTED"


class ChannelPref(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"
    EITHER = "EITHER"


class AttendanceOutcome(str, Enum):
    ATTENDED = "ATTENDED"
    LATE = "LATE"
    NO_SHOW = "NO_SHOW"
    EXCUSED = "EXCUSED"


class OutreachKind(str, Enum):
    NO_SHOW_FOLLOW_UP = "NO_SHOW_FOLLOW_UP"
    RESCHEDULE_ASSIST = "RESCHEDULE_ASSIST"
    LANGUAGE_ACCESS = "LANGUAGE_ACCESS"


class OutreachStatus(str, Enum):
    OPEN = "OPEN"
    CONTACTED = "CONTACTED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Primary resources carry id + created_at + updated_at + version (PRD 2.5).
# StudentTeacherLink and AttendanceRecord are append-only: id + created_at only.
# ---------------------------------------------------------------------------


class ConferenceWindow(TypedDict, total=False):
    id: str
    name: str
    term_label: str
    format: str
    slot_length_minutes: int
    buffer_minutes: int
    travel_minutes: int
    day_windows: List[dict]
    booking_open_at: str
    booking_close_at: str
    teacher_daily_conf_cap: int
    family_conf_cap: int
    cancel_cutoff_hours: int
    waitlist_offer_ttl_hours: int
    no_show_strike_threshold: int
    auto_no_show_grace_hours: int
    status: str
    ops_run_index: int
    slots_total_count: int
    slots_open_count: int
    slots_held_count: int
    slots_booked_count: int
    bookings_confirmed_count: int
    waitlist_waiting_count: int
    created_at: str
    updated_at: str
    version: int


class Teacher(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    grade_band: str
    subjects: List[str]
    room_location: Optional[str]
    supports_in_person: bool
    supports_virtual: bool
    daily_conf_cap_override: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict, total=False):
    id: str
    primary_guardian_name: str
    email: str
    phone: Optional[str]
    preferred_language: str
    status: str
    no_show_strike_count: int
    strikes_cleared_total: int
    attendance_risk_strict: float
    attendance_risk_score: float
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    family_id: str
    full_name: str
    grade_level: int
    enrollment_status: str
    created_at: str
    updated_at: str
    version: int


class StudentTeacherLink(TypedDict, total=False):
    # Append-only resource: id + created_at only (PRD 2.5).
    id: str
    student_id: str
    teacher_id: str
    is_homeroom: bool
    required_conference: bool
    created_at: str


class TimeSlot(TypedDict, total=False):
    id: str
    window_id: str
    teacher_id: str
    day_label: str
    start_at: str
    end_at: str
    channel_allowed: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    window_id: str
    family_id: str
    student_id: str
    teacher_id: str
    slot_id: str
    channel: str
    interpreter_language: Optional[str]
    booked_by_role: str
    status: str
    cancel_reason: Optional[str]
    rescheduled_from_booking_id: Optional[str]
    family_compactness_score: float
    created_at: str
    updated_at: str
    version: int


class Interpreter(TypedDict, total=False):
    id: str
    full_name: str
    languages: List[str]
    supports_in_person: bool
    supports_virtual: bool
    max_consecutive_minutes: int
    base_minutes_per_window: int
    hourly_rate_cents: int
    status: str
    committed_minutes: int
    created_at: str
    updated_at: str
    version: int


class InterpreterRequest(TypedDict, total=False):
    id: str
    booking_id: str
    window_id: str
    language: str
    channel_required: str
    interpreter_id: Optional[str]
    assigned_minutes: int
    declined_interpreter_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    window_id: str
    family_id: str
    student_id: str
    teacher_id: str
    channel_pref: str
    status: str
    offers_made_count: int
    offered_slot_id: Optional[str]
    offer_expires_at: Optional[str]
    declined_slot_ids: List[str]
    priority_score: float
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict, total=False):
    # Append-only resource: id + created_at only (PRD 2.5).
    id: str
    booking_id: str
    outcome: str
    marked_by_role: str
    marked_by_user_id: str
    note: Optional[str]
    created_at: str


class OutreachTask(TypedDict, total=False):
    id: str
    family_id: str
    window_id: Optional[str]
    booking_id: Optional[str]
    kind: str
    status: str
    attempts_count: int
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int
