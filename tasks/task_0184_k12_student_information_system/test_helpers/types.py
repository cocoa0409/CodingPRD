"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the common fields id, created_at, updated_at,
and version (PRD §2.6 — "There are no immutable, version-less entities in this
system").
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    TEACHER = "Teacher"
    ADMINISTRATOR = "Administrator"
    STATE_REPORTING_OFFICER = "StateReportingOfficer"
    PARENT = "Parent"


# --- Status enums ---
class StudentStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    NO_SHOW = "NO_SHOW"


class SectionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ScheduleAssignmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    DROPPED = "DROPPED"


class AttendanceCode(str, Enum):
    PRESENT = "PRESENT"
    ABSENT_EXCUSED = "ABSENT_EXCUSED"
    ABSENT_UNEXCUSED = "ABSENT_UNEXCUSED"
    TARDY = "TARDY"


class AttendanceSource(str, Enum):
    TEACHER = "TEACHER"
    SYSTEM_SUSPENSION = "SYSTEM_SUSPENSION"


class AttendanceRecordStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"


class DailyCode(str, Enum):
    PRESENT = "PRESENT"
    PARTIAL = "PARTIAL"
    ABSENT = "ABSENT"


class GradingMode(str, Enum):
    STANDARDS = "STANDARDS"
    TRADITIONAL = "TRADITIONAL"


class ReportCardStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    REOPENED = "REOPENED"


class IncidentCategory(str, Enum):
    DISRUPTION = "DISRUPTION"
    FIGHTING = "FIGHTING"
    TRUANCY = "TRUANCY"
    ACADEMIC_DISHONESTY = "ACADEMIC_DISHONESTY"
    WEAPON = "WEAPON"


class IncidentStatus(str, Enum):
    REFERRED = "REFERRED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADJUDICATED = "ADJUDICATED"
    DISMISSED = "DISMISSED"


class ConsequenceType(str, Enum):
    WARNING = "WARNING"
    DETENTION = "DETENTION"
    IN_SCHOOL_SUSPENSION = "IN_SCHOOL_SUSPENSION"
    OUT_OF_SCHOOL_SUSPENSION = "OUT_OF_SCHOOL_SUSPENSION"


class ConsequenceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESCINDED = "RESCINDED"


class AdaMethod(str, Enum):
    AGGREGATE_MEMBERSHIP = "AGGREGATE_MEMBERSHIP"
    DAYS_PRESENT = "DAYS_PRESENT"


class AdaReportStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.6) ---
class School(TypedDict):
    id: str
    name: str
    state_code: str
    ada_method: str
    minimum_daily_minutes: int
    current_school_day_index: int
    session_total_days: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    school_id: str
    state_student_id: str
    first_name: str
    last_name: str
    grade_level: str
    birth_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    school_id: str
    entry_day_index: int
    exit_day_index: Optional[int]
    fte: float
    membership_days: int
    present_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    school_id: str
    course_code: str
    title: str
    credit_value: float
    grading_mode: str
    created_at: str
    updated_at: str
    version: int


class Section(TypedDict):
    id: str
    course_id: str
    school_id: str
    teacher_user_id: str
    period: int
    meeting_minutes: int
    capacity: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScheduleAssignment(TypedDict):
    id: str
    enrollment_id: str
    section_id: str
    period: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict):
    id: str
    schedule_assignment_id: str
    enrollment_id: str
    day_index: int
    period: int
    code: str
    source: str
    present_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyAttendance(TypedDict):
    id: str
    enrollment_id: str
    day_index: int
    present_minutes_total: int
    daily_code: str
    ada_eligible: bool
    created_at: str
    updated_at: str
    version: int


class StandardScore(TypedDict):
    id: str
    schedule_assignment_id: str
    section_id: str
    standard_code: str
    weight: float
    mastery_level: Optional[int]
    percentage_points: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ReportCard(TypedDict):
    id: str
    enrollment_id: str
    term_label: str
    overall_gpa: Optional[float]
    credits_earned: float
    line_items: list
    status: str
    created_at: str
    updated_at: str
    version: int


class DisciplineIncident(TypedDict):
    id: str
    enrollment_id: str
    referring_user_id: str
    category: str
    severity: int
    incident_day_index: int
    adjudicator_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisciplineConsequence(TypedDict):
    id: str
    incident_id: str
    enrollment_id: str
    type: str
    start_day_index: Optional[int]
    duration_days: int
    absence_code_applied: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdaFundingReport(TypedDict):
    id: str
    school_id: str
    as_of_day_index: int
    method_used: str
    total_ada: float
    funded_enrollment_count: int
    certifier_user_id: Optional[str]
    drafter_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
