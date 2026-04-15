"""Domain types derived from scaffold Tables 1, 2, 7."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# State / phase enums
# ---------------------------------------------------------------------------

class SemesterPhase(str, Enum):
    PLANNING = "PLANNING"
    OPEN_ENROLLMENT = "OPEN_ENROLLMENT"
    CLOSED_ENROLLMENT = "CLOSED_ENROLLMENT"
    FINALIZED = "FINALIZED"


class EnrollmentStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"
    WITHDRAWN = "WITHDRAWN"
    REJECTED = "REJECTED"


class CrossDeptPermissionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class AcademicStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class CourseLevel(str, Enum):
    INTRODUCTORY = "INTRODUCTORY"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    GRADUATE = "GRADUATE"


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    PROFESSOR = "Professor"
    STUDENT = "Student"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Semester(TypedDict, total=False):
    id: str
    term_label: str
    year: int
    registration_opens: str
    registration_closes: str
    late_drop_deadline: str
    phase: str
    opened_on: str
    modified_on: str
    enrollment_seq: int


class Department(TypedDict, total=False):
    id: str
    semester_id: str
    dept_code: str
    dept_name: str
    cross_dept_open: bool
    opened_on: str
    modified_on: str
    enrollment_seq: int


class Course(TypedDict, total=False):
    id: str
    department_id: str
    course_code: str
    title: str
    credit_hours: int
    level: str
    min_gpa: float
    prerequisite_ids: List[str]
    corequisite_ids: List[str]
    is_active: bool
    opened_on: str
    modified_on: str
    enrollment_seq: int


class Section(TypedDict, total=False):
    id: str
    course_id: str
    section_number: str
    instructor_id: str
    capacity: int
    waitlist_cap: int
    schedule_days: str
    schedule_start: str
    schedule_end: str
    location: str
    seats_enrolled: int
    seats_available: int
    waitlist_count: int
    requires_approval: bool
    enrollment_seq: int
    opened_on: str
    modified_on: str


class Instructor(TypedDict, total=False):
    id: str
    semester_id: str
    employee_number: str
    full_name: str
    home_department_id: str
    can_approve_cross_dept: bool
    opened_on: str
    modified_on: str
    enrollment_seq: int


class Student(TypedDict, total=False):
    id: str
    semester_id: str
    student_number: str
    full_name: str
    major_department_id: str
    academic_standing: str
    cumulative_gpa: float
    max_credits: int
    credits_enrolled: int
    credits_available: int
    completed_course_ids: List[str]
    opened_on: str
    modified_on: str
    enrollment_seq: int


class Enrollment(TypedDict, total=False):
    id: str
    section_id: str
    student_id: str
    status: str
    waitlist_position: Optional[int]
    enrolled_on: Optional[str]
    dropped_on: Optional[str]
    approval_note: Optional[str]
    is_cross_dept: bool
    enrollment_seq: int
    opened_on: str
    modified_on: str


class CrossDeptPermission(TypedDict, total=False):
    id: str
    semester_id: str
    student_id: str
    target_department_id: str
    granted_by: str
    max_courses: int
    courses_used: int
    status: str
    opened_on: str
    modified_on: str
    enrollment_seq: int


class ScheduleConflict(TypedDict, total=False):
    id: str
    student_id: str
    section_a_id: str
    section_b_id: str
    overlap_days: str
    overlap_minutes: int
    detected_on: str


class WaitlistPromotion(TypedDict, total=False):
    id: str
    enrollment_id: str
    section_id: str
    previous_position: int
    trigger_event: str
    promoted_on: str


class PrerequisiteGraph(TypedDict, total=False):
    course_id: str
    dependency_chain: List[str]
    depth: int
    has_cycle: bool
