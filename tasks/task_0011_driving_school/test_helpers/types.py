"""Domain types for the Driving School API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---

class UserRole(str, Enum):
    ADMIN = "Admin"
    STUDENT = "Student"
    INSTRUCTOR = "Instructor"
    EXAMINER = "Examiner"
    COMPLAINT_HANDLER = "ComplaintHandler"


# --- Vehicle types (PRD §3.2) ---

class VehicleType(str, Enum):
    MANUAL_C1 = "MANUAL_C1"
    AUTO_C2 = "AUTO_C2"
    TRUCK_B2 = "TRUCK_B2"
    MOTORCYCLE_E = "MOTORCYCLE_E"


# --- Status enums ---

class StudentEnrollmentStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    PENDING_MEDICAL = "PENDING_MEDICAL"
    PENDING_PACKAGE = "PENDING_PACKAGE"
    PENDING_CONTRACT = "PENDING_CONTRACT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class TrainingStage(str, Enum):
    THEORY = "THEORY"
    BASIC = "BASIC"
    HIGHWAY = "HIGHWAY"
    COMPLETED = "COMPLETED"


class MedicalCertStatus(str, Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class PracticeStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ExamStatus(str, Enum):
    BOOKED = "BOOKED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ExamType(str, Enum):
    THEORY_TEST = "THEORY_TEST"
    BASIC_TEST = "BASIC_TEST"
    FINAL_TEST = "FINAL_TEST"


class SimulatorStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class ComplaintCategory(str, Enum):
    SCHEDULING = "SCHEDULING"
    INSTRUCTOR_CONDUCT = "INSTRUCTOR_CONDUCT"
    BILLING = "BILLING"
    FACILITY = "FACILITY"
    OTHER = "OTHER"


class AuthoritySubmissionStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"


# --- TypedDicts (common_fields=true entities carry id/created_at/updated_at/version) ---

class Student(TypedDict, total=False):
    id: str
    full_name: str
    id_number: str
    id_card_country: str
    id_verified: bool
    medical_cert_status: str
    medical_cert_expires_on: Optional[str]
    course_package_id: Optional[str]
    contract_signed_at: Optional[str]
    training_stage: str
    enrollment_status: str
    cycle_start_date: Optional[str]
    no_show_count_this_cycle: int
    reschedule_count_this_cycle: int
    minutes_remaining_provisional: int
    minutes_remaining_final: int
    simulator_sessions_remaining: int
    exam_attempts_remaining: int
    has_passed_theory: bool
    has_passed_basic_practical: bool
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    vehicle_qualifications: List[str]
    status: str
    last_rest_date: Optional[str]
    working_minutes_today: int
    working_minutes_this_week: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    plate_number: str
    vehicle_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


# CoursePackage is common_fields=false: only id + created_at + payload fields
class CoursePackage(TypedDict, total=False):
    id: str
    name: str
    total_minutes: int
    total_price_cents: int
    included_simulator_sessions: int
    included_exam_attempts: int
    per_minute_overage_price_cents: int
    per_simulator_session_overage_price_cents: int
    created_at: str


class PracticeAppointment(TypedDict, total=False):
    id: str
    student_id: str
    instructor_id: str
    vehicle_id: str
    vehicle_type: str
    training_stage: str
    scheduled_start_at: str
    scheduled_end_at: str
    scheduled_minutes: int
    status: str
    reschedule_of_id: Optional[str]
    cancelled_at: Optional[str]
    cancellation_actor_role: Optional[str]
    check_in_at: Optional[str]
    check_out_at: Optional[str]
    gps_track_distance_km: Optional[float]
    gps_validated: Optional[bool]
    recorded_minutes: Optional[int]
    late_cancellation_fee_cents: Optional[int]
    no_show_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ExamAppointment(TypedDict, total=False):
    id: str
    student_id: str
    exam_type: str
    scheduled_at: str
    examiner_id: str
    status: str
    score: Optional[int]
    passing_score: int
    retake_index: int
    prerequisite_stage: str
    created_at: str
    updated_at: str
    version: int


class SimulatorSession(TypedDict, total=False):
    id: str
    student_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    charged_to_package: bool
    overage_cents: int
    created_at: str
    updated_at: str
    version: int


# TrainingHourRecord is append-only: id + created_at only
class TrainingHourRecord(TypedDict, total=False):
    id: str
    student_id: str
    source_appointment_id: str
    training_stage: str
    minutes_recorded: int
    gps_validated: bool
    authority_submission_status: str
    submitted_at: Optional[str]
    created_at: str


class Complaint(TypedDict, total=False):
    id: str
    student_id: str
    instructor_id: Optional[str]
    category: str
    description: str
    level: int
    status: str
    assigned_handler_id: Optional[str]
    assigned_handler_role: Optional[str]
    response_text: Optional[str]
    resolution_summary: Optional[str]
    escalated_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# AuditLog is append-only: id + created_at only
class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    entity_type: str
    entity_id: str
    action: str
    occurred_at: str
    created_at: str
