"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    BOARD_CLERK = "BoardClerk"
    APPOINTING_AUTHORITY = "AppointingAuthority"
    CONFIRMING_MEMBER = "ConfirmingMember"
    ETHICS_OFFICER = "EthicsOfficer"
    APPLICANT = "Applicant"
    PUBLIC_AUDITOR = "PublicAuditor"


class BoardType(str, Enum):
    BOARD = "BOARD"
    COMMISSION = "COMMISSION"
    AUTHORITY = "AUTHORITY"


class BoardStatus(str, Enum):
    ACTIVE = "ACTIVE"


class SeatCategory(str, Enum):
    AT_LARGE = "AT_LARGE"
    DISTRICT = "DISTRICT"
    EX_OFFICIO = "EX_OFFICIO"


class ResidencyRequirement(str, Enum):
    IN_JURISDICTION = "IN_JURISDICTION"
    DISTRICT_SPECIFIC = "DISTRICT_SPECIFIC"
    NONE = "NONE"


class OccupancyStatus(str, Enum):
    VACANT = "VACANT"
    FILLED = "FILLED"
    HOLDOVER = "HOLDOVER"


class VacancyReason(str, Enum):
    NEW_SEAT = "NEW_SEAT"
    RESIGNATION = "RESIGNATION"
    TERM_EXPIRY = "TERM_EXPIRY"
    REMOVAL = "REMOVAL"


class VacancyStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FILLED = "FILLED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class AppointmentStatus(str, Enum):
    NOMINATED = "NOMINATED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class TermStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOLDOVER = "HOLDOVER"
    EXPIRED = "EXPIRED"
    VACATED = "VACATED"
    COMPLETED = "COMPLETED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NOTICED = "NOTICED"
    HELD = "HELD"


class Presence(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"


class FilingType(str, Enum):
    FINANCIAL_DISCLOSURE = "FINANCIAL_DISCLOSURE"
    ETHICS_PLEDGE = "ETHICS_PLEDGE"


class DisclosureStatus(str, Enum):
    PENDING = "PENDING"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"
    CLOSED = "CLOSED"


class RemovalReason(str, Enum):
    RESIGNATION = "RESIGNATION"
    TERM_LIMIT = "TERM_LIMIT"
    ATTENDANCE = "ATTENDANCE"
    ETHICS_VIOLATION = "ETHICS_VIOLATION"
    FOR_CAUSE = "FOR_CAUSE"


class RemovalStatus(str, Enum):
    INITIATED = "INITIATED"
    EXECUTED = "EXECUTED"


class ReappointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# ---- Entity TypedDicts (common_fields: true unless noted) ----

class Board(TypedDict):
    id: str
    name: str
    jurisdiction: str
    board_type: str
    authorized_seat_count: int
    quorum_count: int
    term_length_months: int
    max_consecutive_terms: int
    max_cumulative_years: float
    attendance_threshold_pct: float
    sunshine_notice_days: int
    max_holdover_days: int
    is_sunshine_subject: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict):
    id: str
    board_id: str
    seat_number: int
    seat_category: str
    residency_requirement: str
    required_district: Optional[str]
    occupancy_status: str
    created_at: str
    updated_at: str
    version: int


class Vacancy(TypedDict):
    id: str
    seat_id: str
    reason: str
    application_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    residence_district: str
    resides_in_jurisdiction: bool
    is_registered_voter: bool
    employer: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    applicant_id: str
    vacancy_id: str
    residency_attested: bool
    statement: Optional[str]
    return_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    application_id: str
    seat_id: str
    applicant_id: str
    term_start_date: str
    term_end_date: str
    term_sequence_number: int
    nominated_by_user_id: str
    yes_votes: Optional[int]
    no_votes: Optional[int]
    confirmed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Term(TypedDict):
    id: str
    appointment_id: str
    seat_id: str
    applicant_id: str
    board_id: str
    term_start_date: str
    term_end_date: str
    term_sequence_number: int
    is_holdover: bool
    present_count: int
    absent_count: int
    excused_count: int
    provisional_attendance_rate: Optional[float]
    final_attendance_rate: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Meeting(TypedDict):
    id: str
    board_id: str
    scheduled_date: str
    notice_posted_at: Optional[str]
    notice_compliant: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — AttendanceRecord carries ONLY id + created_at
class AttendanceRecord(TypedDict):
    id: str
    term_id: str
    meeting_id: str
    presence: str
    created_at: str


class DisclosureFiling(TypedDict):
    id: str
    term_id: str
    board_id: str
    filing_type: str
    due_date: str
    filed_at: Optional[str]
    content: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RemovalAction(TypedDict):
    id: str
    term_id: str
    reason: str
    effective_date: str
    initiated_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReappointmentRequest(TypedDict):
    id: str
    term_id: str
    seat_id: str
    applicant_id: str
    requested_term_start: str
    consecutive_terms_at_request: Optional[int]
    cumulative_years_at_request: Optional[float]
    resulting_appointment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
