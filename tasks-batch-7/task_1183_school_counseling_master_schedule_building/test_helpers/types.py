"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


class TermPosture(str, Enum):
    COLLECTING = "COLLECTING"
    TALLYING = "TALLYING"
    BUILDING = "BUILDING"
    PUBLISHED = "PUBLISHED"
    CHANGE_WINDOW = "CHANGE_WINDOW"
    LOCKED = "LOCKED"
    REBALANCING = "REBALANCING"


class SpecialProgram(str, Enum):
    NONE = "NONE"
    IEP = "IEP"
    ELL = "ELL"
    GIFTED = "GIFTED"
    ATHLETE = "ATHLETE"


class RoomType(str, Enum):
    STANDARD = "STANDARD"
    LAB = "LAB"
    GYM = "GYM"
    STUDIO = "STUDIO"


class SubjectArea(str, Enum):
    ENGLISH = "ENGLISH"
    MATH = "MATH"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"
    WORLD_LANGUAGE = "WORLD_LANGUAGE"
    PE_HEALTH = "PE_HEALTH"
    ARTS = "ARTS"
    ELECTIVE = "ELECTIVE"


class CourseRequestState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    PLACED = "PLACED"
    UNPLACED = "UNPLACED"
    WITHDRAWN = "WITHDRAWN"


class SectionState(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class ScheduleEntryState(str, Enum):
    ENROLLED = "ENROLLED"
    DROPPED = "DROPPED"
    MOVED = "MOVED"


class ScheduleEntryOrigin(str, Enum):
    AUTO_PLACEMENT = "AUTO_PLACEMENT"
    CHANGE_REQUEST = "CHANGE_REQUEST"
    RECOVERY_PLACEMENT = "RECOVERY_PLACEMENT"
    REBALANCE = "REBALANCE"


class ChangeRequestKind(str, Enum):
    DROP = "DROP"
    ADD = "ADD"
    SWAP = "SWAP"


class ChangeRequestState(str, Enum):
    SUBMITTED = "SUBMITTED"
    COUNSELOR_REVIEW = "COUNSELOR_REVIEW"
    REVISED = "REVISED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class AppointmentState(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class RecoveryPlacementState(str, Enum):
    PENDING = "PENDING"
    PLACED = "PLACED"
    EXPIRED = "EXPIRED"
    WAIVED = "WAIVED"


class UserRole(str, Enum):
    ADMINISTRATOR = "Administrator"
    COUNSELOR = "Counselor"
    STUDENT = "Student"


# common_fields: true — carries id + created_at + updated_at + version
class AcademicTerm(TypedDict, total=False):
    id: str
    code: str
    posture: str
    periods_per_day: int
    max_students_per_section: int
    class_size_target: int
    singleton_section_cap: int
    change_window_open: bool
    change_request_max_per_student: int
    rebalance_epoch: int
    total_requested_seats: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    external_ref: str
    full_name: str
    grade_level: int
    special_program: str
    counselor_id: str
    earned_credits: float
    planned_credit_load: float
    credit_deficient: bool
    created_at: str
    updated_at: str
    version: int


class Counselor(TypedDict, total=False):
    id: str
    full_name: str
    max_caseload: int
    caseload_count: int
    created_at: str
    updated_at: str
    version: int


class Teacher(TypedDict, total=False):
    id: str
    full_name: str
    max_sections: int
    assigned_section_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at
class TeacherQualification(TypedDict, total=False):
    id: str
    teacher_id: str
    course_id: str
    qualified_at: str
    created_at: str


class Room(TypedDict, total=False):
    id: str
    room_number: str
    capacity: int
    room_type: str
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict, total=False):
    id: str
    course_code: str
    title: str
    credits: float
    subject_area: str
    required_room_type: str
    singleton: bool
    grade_band_min: int
    grade_band_max: int
    special_program_exclusive: str
    prerequisite_course_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourseRequest(TypedDict, total=False):
    id: str
    student_id: str
    course_id: str
    term_id: str
    priority_rank: int
    is_alternate: bool
    state: str
    tally_weight: float
    created_at: str
    updated_at: str
    version: int


class Section(TypedDict, total=False):
    id: str
    term_id: str
    course_id: str
    teacher_id: Optional[str]
    room_id: Optional[str]
    period: int
    capacity: int
    enrolled_count: int
    cohort_counts: Dict[str, int]
    state: str
    under_enrolled: bool
    created_at: str
    updated_at: str
    version: int


class ScheduleEntry(TypedDict, total=False):
    id: str
    student_id: str
    section_id: str
    term_id: str
    state: str
    origin: str
    moved_to_section_id: Optional[str]
    epoch_placed: int
    created_at: str
    updated_at: str
    version: int


class ScheduleChangeRequest(TypedDict, total=False):
    id: str
    student_id: str
    term_id: str
    kind: str
    drop_entry_id: Optional[str]
    add_section_id: Optional[str]
    reason: str
    state: str
    reviewed_by_counselor_id: Optional[str]
    decided_by_admin: bool
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    counselor_id: str
    student_id: str
    start_at: str
    end_at: str
    state: str
    no_show_count_snapshot: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at
class CreditAudit(TypedDict, total=False):
    id: str
    student_id: str
    term_id: str
    required_credits: float
    projected_credits: float
    deficiency_credits: float
    deficient_subjects: List[str]
    audit_epoch: int
    created_at: str


class RecoveryPlacement(TypedDict, total=False):
    id: str
    student_id: str
    term_id: str
    target_course_id: str
    section_id: Optional[str]
    state: str
    priority_score: float
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at
class RebalanceRun(TypedDict, total=False):
    id: str
    term_id: str
    epoch: int
    moves_proposed: int
    imbalance_score_before: float
    imbalance_score_after: float
    executed_at: str
    created_at: str
