"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    SCHOOL_ADMIN = "SchoolAdmin"
    STUDENT = "Student"
    PARENT = "Parent"
    GUARDIAN = "Guardian"
    DORM_PARENT = "DormParent"
    NURSE = "Nurse"
    DEAN = "Dean"
    FRONT_DESK = "FrontDesk"


class TermStatus(str, Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class DormPosture(str, Enum):
    OPEN = "OPEN"
    CLOSED_FOR_BREAK = "CLOSED_FOR_BREAK"


class GenderPolicy(str, Enum):
    MALE_ONLY = "MALE_ONLY"
    FEMALE_ONLY = "FEMALE_ONLY"
    ANY = "ANY"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FULL = "FULL"
    BLOCKED = "BLOCKED"


class GuardianStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class StaffRole(str, Enum):
    DORM_PARENT = "DORM_PARENT"
    NURSE = "NURSE"
    DEAN = "DEAN"
    FRONT_DESK = "FRONT_DESK"


class Gender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ON_LEAVE = "ON_LEAVE"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class DisciplineStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"
    ENDED = "ENDED"


class LeaveType(str, Enum):
    WEEKEND_OVERNIGHT = "WEEKEND_OVERNIGHT"
    DAY_PASS = "DAY_PASS"
    BREAK_TRAVEL = "BREAK_TRAVEL"


class LeaveStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PARENT_APPROVED = "PARENT_APPROVED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    SIGNED_OUT = "SIGNED_OUT"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"


class SignEventType(str, Enum):
    SIGN_OUT = "SIGN_OUT"
    SIGN_IN = "SIGN_IN"


class ShiftSlot(str, Enum):
    WEEKDAY_NIGHT = "WEEKDAY_NIGHT"
    WEEKEND_DAY = "WEEKEND_DAY"
    WEEKEND_NIGHT = "WEEKEND_NIGHT"


class DutyShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SWAP_PENDING = "SWAP_PENDING"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class CheckKind(str, Enum):
    BED_CHECK = "BED_CHECK"
    STUDY_HALL = "STUDY_HALL"


class CheckResult(str, Enum):
    PRESENT = "PRESENT"
    LATE_ARRIVAL = "LATE_ARRIVAL"
    ABSENT_EXCUSED = "ABSENT_EXCUSED"
    ABSENT_UNEXCUSED = "ABSENT_UNEXCUSED"


class MedicationSlot(str, Enum):
    MORNING = "MORNING"
    NOON = "NOON"
    EVENING = "EVENING"
    BEDTIME = "BEDTIME"


class MedicationOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOLD = "HOLD"
    DISCONTINUED = "DISCONTINUED"
    COMPLETED = "COMPLETED"


class AdministrationOutcome(str, Enum):
    ADMINISTERED = "ADMINISTERED"
    REFUSED = "REFUSED"
    OMITTED_HOLD = "OMITTED_HOLD"


class CaseCategory(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class DisciplineCaseStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    SANCTIONED = "SANCTIONED"
    APPEALED = "APPEALED"
    DISMISSED = "DISMISSED"
    CLOSED = "CLOSED"


class SanctionType(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    PROBATION = "PROBATION"
    SUSPENSION = "SUSPENSION"
    EXPULSION = "EXPULSION"


class BreakKind(str, Enum):
    THANKSGIVING = "THANKSGIVING"
    WINTER = "WINTER"
    SPRING = "SPRING"
    SUMMER = "SUMMER"


class BreakPeriodStatus(str, Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class BreakHousingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class StorageUnitStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"


class StorageReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    RETRIEVED = "RETRIEVED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


# --- Entity TypedDicts ---
# PRD §2.5: most resources carry id, created_at, updated_at, version.
# SignEvent, NightCheck, and MedicationAdministration are append-only event
# records and carry only id and created_at (no updated_at, no version).

class Term(TypedDict):
    id: str
    name: str
    starts_on: str
    ends_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dorm(TypedDict):
    id: str
    name: str
    gender_policy: str
    curfew_weekday: str
    curfew_weekend: str
    posture: str
    beds_total: int
    occupancy_physical: int
    occupancy_projected: int
    beds_available: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    dorm_id: str
    room_number: str
    beds: int
    status: str
    beds_assigned: int
    beds_available: int
    created_at: str
    updated_at: str
    version: int


class Parent(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict):
    id: str
    full_name: str
    email: str
    city: str
    max_wards: int
    wards_assigned: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    full_name: str
    staff_role: str
    dorm_id: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    legal_name: str
    grade: int
    gender: str
    is_international: bool
    parent_id: str
    guardian_id: Optional[str]
    sleep_schedule: int
    cleanliness: int
    noise_tolerance: int
    guests_comfort: int
    enrollment_status: str
    discipline_standing: str
    demerit_points: int
    demerit_points_provisional: int
    weekend_leaves_used: int
    weekend_leave_allowance: int
    created_at: str
    updated_at: str
    version: int


class DormAssignment(TypedDict):
    id: str
    student_id: str
    room_id: str
    term_id: str
    roommate_assignment_id: Optional[str]
    status: str
    compatibility_score: Optional[int]
    check_in_at: Optional[str]
    check_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeaveRequest(TypedDict):
    id: str
    student_id: str
    leave_type: str
    destination: str
    departs_at: str
    returns_at: str
    status: str
    decided_by_parent_id: Optional[str]
    decided_by_staff_id: Optional[str]
    denial_reason: Optional[str]
    signed_out_at: Optional[str]
    returned_at: Optional[str]
    late_return_minutes: int
    created_at: str
    updated_at: str
    version: int


# Append-only event record: id + created_at only (no updated_at, no version).
class SignEvent(TypedDict):
    id: str
    student_id: str
    event_type: str
    occurred_at: str
    leave_request_id: Optional[str]
    recorded_by_staff_id: str
    minutes_late: int
    created_at: str


class DutyShift(TypedDict):
    id: str
    dorm_id: str
    staff_id: str
    duty_date: str
    shift_slot: str
    status: str
    swap_requested_to_id: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only event record: id + created_at only (no updated_at, no version).
class NightCheck(TypedDict):
    id: str
    duty_shift_id: str
    student_id: str
    check_kind: str
    result: str
    checked_at: str
    points_assessed: int
    created_at: str


class MedicationOrder(TypedDict):
    id: str
    student_id: str
    medication_name: str
    dose_mg: float
    slot: str
    doses_total: int
    doses_remaining: int
    refill_threshold: int
    low_stock: bool
    is_controlled: bool
    prescriber_name: str
    status: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only event record: id + created_at only (no updated_at, no version).
class MedicationAdministration(TypedDict):
    id: str
    order_id: str
    scheduled_date: str
    outcome: str
    administered_by_staff_id: str
    witness_staff_id: Optional[str]
    notes: Optional[str]
    created_at: str


class DisciplineCase(TypedDict):
    id: str
    student_id: str
    reported_by_staff_id: str
    category: str
    description: str
    points_proposed: int
    status: str
    hearing_officer_id: Optional[str]
    hearing_at: Optional[str]
    sanction_type: Optional[str]
    points_assessed: int
    decided_at: Optional[str]
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class BreakPeriod(TypedDict):
    id: str
    name: str
    kind: str
    starts_on: str
    ends_on: str
    housing_available: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BreakHousingRequest(TypedDict):
    id: str
    student_id: str
    break_period_id: str
    reason: Optional[str]
    status: str
    room_id: Optional[str]
    room_charge_cents: int
    storage_total_cents: int
    deposit_credit_cents: int
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class StorageUnit(TypedDict):
    id: str
    label: str
    capacity_cuft: int
    status: str
    used_cuft: int
    created_at: str
    updated_at: str
    version: int


class StorageReservation(TypedDict):
    id: str
    storage_unit_id: str
    student_id: str
    break_period_id: str
    volume_cuft: int
    weeks: int
    items_description: str
    early_bird: bool
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
