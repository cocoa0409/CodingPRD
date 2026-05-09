"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# ─── Role enum (PRD §2.1: exactly four roles) ─────────────────────────
class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    STUDENT = "Student"
    PROFESSOR = "Professor"
    FINANCE = "Finance"


# ─── Status enums (PRD §3, state machines) ────────────────────────────
class DepartmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISSOLVED = "DISSOLVED"


class StudentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    GRADUATED = "GRADUATED"


class ProfessorRank(str, Enum):
    ASSISTANT = "ASSISTANT"
    ASSOCIATE = "ASSOCIATE"
    FULL = "FULL"


class TermStatus(str, Enum):
    PLANNING = "PLANNING"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    IN_SESSION = "IN_SESSION"
    CONCLUDED = "CONCLUDED"


class CourseOfferingStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    IN_SESSION = "IN_SESSION"
    CONCLUDED = "CONCLUDED"


class EnrollmentRequestAcademicStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"
    SETTLED = "SETTLED"


class EnrollmentRequestFinancialStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    PAID = "PAID"


class OverLimitApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    AWAITING_PRIMARY = "AWAITING_PRIMARY"
    AWAITING_SECONDARY = "AWAITING_SECONDARY"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class WaitlistEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROMOTED = "PROMOTED"
    EXPIRED = "EXPIRED"
    CANCELED = "CANCELED"


class DepartmentAccessGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


# ─── Downstream sync event types (PRD §2.12) ──────────────────────────
class SyncEventType(str, Enum):
    ENROLLMENT_APPROVED = "ENROLLMENT_APPROVED"
    ENROLLMENT_CANCELED = "ENROLLMENT_CANCELED"
    TUITION_BILLED = "TUITION_BILLED"
    TUITION_PAID = "TUITION_PAID"
    OVER_LIMIT_GRANTED = "OVER_LIMIT_GRANTED"
    CAPACITY_REDUCED_CANCELED = "CAPACITY_REDUCED_CANCELED"
    WAITLIST_PROMOTED = "WAITLIST_PROMOTED"


# ─── Entity TypedDicts ─────────────────────────────────────────────────
# common_fields: true entities carry id + created_at + updated_at + version

class Department(TypedDict):
    id: str
    code: str
    name: str
    campus_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Campus(TypedDict):
    id: str
    code: str
    name: str
    commute_minutes_to: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    program_id: str
    program_department_id: str
    home_campus_id: str
    year_in_program: int
    gpa: float
    fraud_score: int
    completed_course_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Professor(TypedDict):
    id: str
    department_id: str
    full_name: str
    rank: str
    is_chair: bool
    max_concurrent_teaching_minutes_per_week: int
    created_at: str
    updated_at: str
    version: int


class Term(TypedDict):
    id: str
    code: str
    registration_open_at: int
    registration_close_at: int
    classes_start_at: int
    exam_window_start_at: int
    exam_window_end_at: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    code: str
    title: str
    credits: float
    owning_department_id: str
    prerequisite_course_ids: List[Dict[str, str]]
    equivalent_course_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class CourseOffering(TypedDict):
    id: str
    term_id: str
    course_id: str
    campus_id: str
    instructor_id: str
    base_capacity: int
    capacity: int
    enrolled_count: int
    scheduled_meetings: List[Dict[str, int]]
    requires_lab_equipment_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LabEquipment(TypedDict):
    id: str
    campus_id: str
    name: str
    setup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class EnrollmentRequest(TypedDict):
    id: str
    student_id: str
    offering_id: str
    term_id: str
    priority_score: Optional[int]
    provisional_credit_charge: Optional[float]
    final_credit_charge: Optional[float]
    academic_status: str
    financial_status: str
    created_at: str
    updated_at: str
    version: int


class OverLimitApplication(TypedDict):
    id: str
    student_id: str
    term_id: str
    requested_extension_credits: float
    justification: str
    primary_signer_id: str
    secondary_signer_id: str
    granted_credits: float
    timeout_deadline_at: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DepartmentAccessGrant(TypedDict):
    id: str
    source_department_id: str
    target_department_id: str
    course_categories_allowed: List[str]
    status: str
    bidirectional: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — ONLY id + created_at, no updated_at/version

class WaitlistEntry(TypedDict):
    id: str
    offering_id: str
    enrollment_request_id: str
    position: int
    priority_score: int
    queued_at: int
    status: str
    created_at: str


class CreditEquivalencePolicy(TypedDict):
    id: str
    source_program_id: str
    target_program_id: str
    source_course_id: str
    target_course_id: str
    transfer_factor: float
    created_at: str


class SyncEvent(TypedDict):
    id: str
    subject_entity: str
    subject_id: str
    event_type: str
    target_systems: List[str]
    payload: Dict[str, Any]
    created_at: str
