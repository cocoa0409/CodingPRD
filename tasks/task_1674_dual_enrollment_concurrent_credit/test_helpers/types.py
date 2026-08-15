"""Domain types: entity TypedDicts, status enums, role enum (PRD 2.1, 2.6, 3.x)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    DUAL_CREDIT_ADMIN = "DualCreditAdmin"
    HS_COORDINATOR = "HsCoordinator"
    INSTRUCTOR = "Instructor"
    CREDENTIAL_REVIEWER = "CredentialReviewer"
    COLLEGE_REGISTRAR = "CollegeRegistrar"
    BURSAR = "Bursar"


class HighSchoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InstitutionType(str, Enum):
    COLLEGE = "COLLEGE"
    HIGH_SCHOOL = "HIGH_SCHOOL"


class TermStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class StudentStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"


class CourseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class GradeLetter(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class EnrollmentGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"
    W = "W"


class CredentialStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DeliveryMode(str, Enum):
    HS_CAMPUS = "HS_CAMPUS"
    COLLEGE_CAMPUS = "COLLEGE_CAMPUS"
    ONLINE = "ONLINE"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    IN_SESSION = "IN_SESSION"
    GRADING = "GRADING"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TranscriptStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class FundingModel(str, Enum):
    STATE_PROGRAM = "STATE_PROGRAM"
    DISTRICT_CONTRACT = "DISTRICT_CONTRACT"
    FAMILY_RESPONSIBLE = "FAMILY_RESPONSIBLE"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOIDED = "VOIDED"


class RefundStatus(str, Enum):
    NONE = "NONE"
    DUE = "DUE"
    PROCESSED = "PROCESSED"


class Payer(str, Enum):
    STATE = "STATE"
    DISTRICT = "DISTRICT"
    FAMILY = "FAMILY"


# --- common_fields entities: id + created_at + updated_at + version ---


class HighSchool(TypedDict):
    id: str
    name: str
    district_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AcademicTerm(TypedDict):
    id: str
    institution_type: str
    high_school_id: Optional[str]
    name: str
    start_date: str
    end_date: str
    add_deadline: str
    drop_deadline: str
    withdraw_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    high_school_id: str
    grade_level: int
    status: str
    college_gpa: float
    hs_gpa: float
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    course_code: str
    title: str
    college_credit_hours: int
    hs_credit_units: float
    placement_exam_code: str
    min_placement_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    high_school_id: str
    created_at: str
    updated_at: str
    version: int


class CredentialApplication(TypedDict):
    id: str
    instructor_id: str
    course_id: str
    qualification_summary: str
    status: str
    reviewed_by: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourseOffering(TypedDict):
    id: str
    course_id: str
    college_term_id: str
    hs_term_id: str
    high_school_id: str
    instructor_id: str
    capacity: int
    delivery_mode: str
    seats_taken: int
    seats_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    offering_id: str
    status: str
    grade: Optional[str]
    waitlist_seq: Optional[int]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TranscriptEntry(TypedDict):
    id: str
    enrollment_id: str
    institution: str
    grade: str
    credit_value: float
    grade_points: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingAgreement(TypedDict):
    id: str
    high_school_id: str
    college_term_id: str
    funding_model: str
    tuition_cents_per_credit: int
    state_rate_cents_per_credit: int
    district_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    enrollment_id: str
    funding_agreement_id: str
    tuition_total_cents: int
    state_amount_cents: int
    district_amount_cents: int
    family_amount_cents: int
    paid_state_cents: int
    paid_district_cents: int
    paid_family_cents: int
    refund_pct: Optional[int]
    refund_estimate_cents: Optional[int]
    est_state_refund_cents: Optional[int]
    est_district_refund_cents: Optional[int]
    est_family_refund_cents: Optional[int]
    refund_paid_cents: Optional[int]
    status: str
    refund_status: str
    created_at: str
    updated_at: str
    version: int


class ArticulationAgreement(TypedDict):
    id: str
    course_id: str
    target_institution: str
    transfer_credit_hours: float
    min_grade_for_transfer: str
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only records (PRD 2.6): carry ONLY id + created_at ---


class Prerequisite(TypedDict):
    id: str
    course_id: str
    requires_course_id: str
    min_grade: str
    created_at: str


class PlacementRecord(TypedDict):
    id: str
    student_id: str
    exam_code: str
    score: int
    taken_at: str
    expires_at: str
    created_at: str


class Payment(TypedDict):
    id: str
    invoice_id: str
    payer: str
    amount_cents: int
    note: Optional[str]
    created_at: str
