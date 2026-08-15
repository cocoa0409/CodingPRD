"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class TermStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    PUBLISHED = "PUBLISHED"


class FacultyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    SEPARATED = "SEPARATED"


class FacultyRank(str, Enum):
    ADJUNCT = "ADJUNCT"
    LECTURER = "LECTURER"
    ASSISTANT_PROFESSOR = "ASSISTANT_PROFESSOR"
    ASSOCIATE_PROFESSOR = "ASSOCIATE_PROFESSOR"
    PROFESSOR = "PROFESSOR"


class CourseType(str, Enum):
    LECTURE = "LECTURE"
    LAB = "LAB"
    SEMINAR = "SEMINAR"


class Modality(str, Enum):
    IN_PERSON = "IN_PERSON"
    ONLINE = "ONLINE"
    HYBRID = "HYBRID"


class MeetingDay(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"


class QualificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SCHEDULED = "SCHEDULED"
    STAFFED = "STAFFED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    RESCINDED = "RESCINDED"
    CANCELLED = "CANCELLED"


class GrantType(str, Enum):
    RESEARCH_BUYOUT = "RESEARCH_BUYOUT"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    SABBATICAL = "SABBATICAL"


class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class OverloadStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CHAIR_ENDORSED = "CHAIR_ENDORSED"
    DEAN_APPROVED = "DEAN_APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class UserRole(str, Enum):
    DEPARTMENT_CHAIR = "DepartmentChair"
    FACULTY_MEMBER = "FacultyMember"
    DEAN_OFFICE = "DeanOffice"
    REGISTRAR = "Registrar"
    SYSTEM_ADMIN = "SystemAdmin"


class WorkloadTerm(TypedDict, total=False):
    id: str
    term_code: str
    title: str
    start_date: str
    census_date: str
    base_teaching_credits: float
    comp_budget_cents: int
    comp_budget_spent_cents: int
    lecture_multiplier: float
    lab_multiplier: float
    seminar_multiplier: float
    online_premium_credits: float
    large_class_threshold: int
    large_class_bonus_credits: float
    overload_comp_rate_cents: int
    union_max_overload_credits: float
    reassignment_notice_days: int
    late_cancel_stipend_cents: int
    flat_release_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FacultyMember(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    rank: str
    is_union_covered: bool
    base_load_credits: float
    base_salary_cents: int
    preferred_course_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict, total=False):
    id: str
    course_code: str
    title: str
    course_type: str
    base_credits: float
    default_enrollment_cap: int
    allowed_modalities: List[str]
    created_at: str
    updated_at: str
    version: int


class Qualification(TypedDict, total=False):
    id: str
    faculty_id: str
    course_id: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CourseSection(TypedDict, total=False):
    id: str
    term_id: str
    course_id: str
    section_number: str
    modality: str
    meeting_day: str
    start_minute: int
    end_minute: int
    enrollment_cap: int
    enrolled_count: int
    is_late_cancelled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    term_id: str
    section_id: str
    faculty_id: str
    credit_units: float
    final_credit_units: Optional[float]
    stipend_cents: int
    matches_preference: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleaseTimeGrant(TypedDict, total=False):
    id: str
    term_id: str
    faculty_id: str
    grant_type: str
    credits_released: float
    start_date: str
    end_date: str
    buyout_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class OverloadRequest(TypedDict, total=False):
    id: str
    term_id: str
    faculty_id: str
    overload_credits: float
    comp_cents: int
    endorsed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadSheet(TypedDict, total=False):
    id: str
    term_id: str
    faculty_id: str
    teaching_credits: float
    release_credits: float
    effective_obligation_credits: float
    overload_credits: float
    underload_credits: float
    created_at: str
    updated_at: str
    version: int
