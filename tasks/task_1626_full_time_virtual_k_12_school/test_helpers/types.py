"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the standard
four system-managed properties (id, created_at, updated_at, version) per the
PRD common-resource-properties section.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ENROLLMENT_OFFICER = "EnrollmentOfficer"
    FINANCE_OFFICER = "FinanceOfficer"
    ACADEMIC_DIRECTOR = "AcademicDirector"
    PROCTOR_COORDINATOR = "ProctorCoordinator"
    SPECIAL_ED_COORDINATOR = "SpecialEdCoordinator"


class EnrollmentStatus(str, Enum):
    APPLIED = "APPLIED"
    ELIGIBLE = "ELIGIBLE"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    REENROLL_PENDING = "REENROLL_PENDING"


class TermStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class WithdrawalReason(str, Enum):
    MOVED_DISTRICT = "MOVED_DISTRICT"
    RETURN_TO_BRICK_AND_MORTAR = "RETURN_TO_BRICK_AND_MORTAR"
    HOMESCHOOL = "HOMESCHOOL"
    DROPOUT = "DROPOUT"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class ProrationMode(str, Enum):
    DAILY_ATTENDANCE = "DAILY_ATTENDANCE"
    CALENDAR_ELAPSED = "CALENDAR_ELAPSED"


class StipendType(str, Enum):
    DEVICE = "DEVICE"
    INTERNET = "INTERNET"


class IssueStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"
    FORFEITED = "FORFEITED"


class TeacherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AssignmentSubject(str, Enum):
    ELA = "ELA"
    MATH = "MATH"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"
    SPECIAL_ED = "SPECIAL_ED"


class TeacherAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ENDED = "ENDED"


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    PARTIAL = "PARTIAL"
    ABSENT_UNEXCUSED = "ABSENT_UNEXCUSED"
    ABSENT_EXCUSED = "ABSENT_EXCUSED"


class WindowSubject(str, Enum):
    ELA = "ELA"
    MATH = "MATH"
    SCIENCE = "SCIENCE"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ProctorAssignmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    SPEECH_THERAPY = "SPEECH_THERAPY"
    OCCUPATIONAL_THERAPY = "OCCUPATIONAL_THERAPY"
    COUNSELING = "COUNSELING"
    RESOURCE_ROOM = "RESOURCE_ROOM"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class District(TypedDict):
    id: str
    district_code: str
    state_code: str
    funding_rate_cents: int
    enrollment_cap: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    legal_name: str
    date_of_birth: str
    grade_level: int
    district_of_residence_id: str
    special_education_flag: bool
    enrollment_status: str
    residency_verified_at: Optional[str]
    funding_days_claimed: int
    funding_claim_cents: int
    truancy_flag: bool
    truancy_unexcused_count: int
    created_at: str
    updated_at: str
    version: int


class EnrollmentTerm(TypedDict):
    id: str
    student_id: str
    term_start_date: str
    term_end_date: Optional[str]
    term_status: str
    withdrawal_reason: Optional[str]
    proration_mode: Optional[str]
    claimable_days: int
    created_at: str
    updated_at: str
    version: int


class DeviceStipend(TypedDict):
    id: str
    student_id: str
    stipend_type: str
    amount_cents: int
    issue_status: str
    issued_at: Optional[str]
    return_due_date: Optional[str]
    clawback_cents: int
    created_at: str
    updated_at: str
    version: int


class Teacher(TypedDict):
    id: str
    full_name: str
    certification_state_codes: List[str]
    caseload_cap: int
    current_caseload: int
    teacher_status: str
    created_at: str
    updated_at: str
    version: int


class TeacherAssignment(TypedDict):
    id: str
    teacher_id: str
    student_id: str
    subject: str
    assignment_status: str
    assigned_at: str
    ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict):
    id: str
    student_id: str
    attendance_date: str
    synchronous_minutes: int
    engagement_check_ins: int
    attendance_status: str
    excused_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssessmentWindow(TypedDict):
    id: str
    assessment_name: str
    subject: str
    window_start: str
    window_end: str
    window_status: str
    created_at: str
    updated_at: str
    version: int


class TestSite(TypedDict):
    id: str
    site_name: str
    state_code: str
    seat_capacity: int
    seats_booked: int
    created_at: str
    updated_at: str
    version: int


class ProctorAssignment(TypedDict):
    id: str
    student_id: str
    assessment_window_id: str
    test_site_id: str
    assignment_status: str
    booked_at: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceDelivery(TypedDict):
    id: str
    student_id: str
    service_type: str
    scheduled_at: str
    duration_minutes: int
    provider_id: str
    delivery_status: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
