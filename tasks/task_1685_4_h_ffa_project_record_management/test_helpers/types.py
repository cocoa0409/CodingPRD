"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD resource model. Clubs, volunteers, members, projects,
animal tags, record books, meetings, rooms, fair entries, stall assignments,
pens, award applications, and scholarship applications carry id + created_at +
updated_at + version. Ledger entries, attendance rows, screening events, and
treasury transactions are immutable audit lines and carry only id + created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    VOLUNTEER = "Volunteer"
    MEMBER = "Member"


class ClubStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ScreeningStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DENIED = "DENIED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    GRADUATED = "GRADUATED"


class EligibilityPosture(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    CONDITIONAL = "CONDITIONAL"
    INELIGIBLE = "INELIGIBLE"


class ProjectType(str, Enum):
    BEEF = "BEEF"
    SHEEP = "SHEEP"
    SWINE = "SWINE"
    CROPS = "CROPS"
    FOODS = "FOODS"
    ROBOTICS = "ROBOTICS"


class ProjectStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    NONE = "NONE"


class Species(str, Enum):
    BEEF = "BEEF"
    SHEEP = "SHEEP"
    SWINE = "SWINE"


class TaggingStatus(str, Enum):
    TAGGED = "TAGGED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RecordBookStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EntryKind(str, Enum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"
    HOURS = "HOURS"


class EntryStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"


class FairLevel(str, Enum):
    COUNTY = "COUNTY"
    STATE = "STATE"


class FairEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    CONFIRMED = "CONFIRMED"
    SCRATCHED = "SCRATCHED"
    EXHIBITED = "EXHIBITED"


class StallStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class AwardTrack(str, Enum):
    DEGREE = "DEGREE"
    STAR = "STAR"
    SCHOLARSHIP = "SCHOLARSHIP"


class AwardStatus(str, Enum):
    DRAFT = "DRAFT"
    NOMINATED = "NOMINATED"
    ENDORSED = "ENDORSED"
    EVALUATED = "EVALUATED"
    AWARDED = "AWARDED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AwardTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"
    NONE = "NONE"


class ScholarshipStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DECLINED = "DECLINED"


class EventKind(str, Enum):
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    REFERENCE_CHECK = "REFERENCE_CHECK"
    INTERVIEW = "INTERVIEW"


class EventOutcome(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    FAIL = "FAIL"


class TxnKind(str, Enum):
    DUES_PAYMENT = "DUES_PAYMENT"
    EXPENSE_REIMBURSEMENT = "EXPENSE_REIMBURSEMENT"


class TxnStatus(str, Enum):
    POSTED = "POSTED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


# --- Entity TypedDicts (mutable resources: id + created_at + updated_at + version) ---


class Club(TypedDict, total=False):
    id: str
    name: str
    county_code: str
    treasury_balance_cents: int
    star_nomination_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    base_clearance: int
    risk_flags: int
    years_service: int
    screening_score: int
    screening_status: str
    club_id: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    full_name: str
    birth_date: str
    club_id: str
    enrollment_status: str
    is_club_officer: bool
    eligibility_posture: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    member_id: str
    project_type: str
    program_year: int
    status: str
    grade: str
    created_at: str
    updated_at: str
    version: int


class AnimalTag(TypedDict, total=False):
    id: str
    project_id: str
    tag_number: str
    species: str
    owned_since: str
    tagged_at: str
    tagging_status: str
    created_at: str
    updated_at: str
    version: int


class RecordBook(TypedDict, total=False):
    id: str
    project_id: str
    program_year: int
    status: str
    submitted_at: Optional[str]
    provisional_score: Optional[float]
    final_score: Optional[float]
    late_days: int
    created_at: str
    updated_at: str
    version: int


class Meeting(TypedDict, total=False):
    id: str
    club_id: str
    starts_at: str
    ends_at: str
    room_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class FairEntry(TypedDict, total=False):
    id: str
    member_id: str
    project_id: str
    fair_level: str
    status: str
    ownership_days_at_entry: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StallAssignment(TypedDict, total=False):
    id: str
    fair_entry_id: str
    pen_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Pen(TypedDict, total=False):
    id: str
    label: str
    animal_capacity: int
    created_at: str
    updated_at: str
    version: int


class AwardApplication(TypedDict, total=False):
    id: str
    member_id: str
    award_track: str
    record_book_id: str
    status: str
    rubric_score: Optional[float]
    award_tier: Optional[str]
    nominated_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScholarshipApp(TypedDict, total=False):
    id: str
    member_id: str
    linked_award_application_id: str
    status: str
    scholarship_points: Optional[int]
    created_at: str
    updated_at: str
    version: int


# --- Audit-line TypedDicts (id + created_at ONLY: no updated_at, no version) ---


class LedgerEntry(TypedDict, total=False):
    id: str
    record_book_id: str
    entry_kind: str
    amount_cents: int
    hours: float
    entry_status: str
    recorded_on: str
    created_at: str


class Attendance(TypedDict, total=False):
    id: str
    meeting_id: str
    member_id: str
    attendance_status: str
    created_at: str


class ScreeningEvent(TypedDict, total=False):
    id: str
    volunteer_id: str
    event_kind: str
    outcome: str
    created_at: str


class TreasuryTransaction(TypedDict, total=False):
    id: str
    club_id: str
    txn_kind: str
    amount_cents: int
    txn_status: str
    created_at: str
