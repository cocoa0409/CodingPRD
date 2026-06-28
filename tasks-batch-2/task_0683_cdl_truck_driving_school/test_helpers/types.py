"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the common audit fields id, created_at,
updated_at, and version (see PRD §2.4), so every TypedDict below includes them.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---------------------------------------------------------------

class UserRole(str, Enum):
    SCHOOL_ADMIN = "SchoolAdmin"
    REGISTRAR = "Registrar"
    INSTRUCTOR = "Instructor"
    THIRD_PARTY_EXAMINER = "ThirdPartyExaminer"


# --- Enum constants ----------------------------------------------------------

class CdlClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"


class EnrollmentStatus(str, Enum):
    APPLIED = "APPLIED"
    PREREQ_PENDING = "PREREQ_PENDING"
    TRAINING = "TRAINING"
    TEST_READY = "TEST_READY"
    PASSED = "PASSED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class PrereqDocumentKind(str, Enum):
    DOT_MEDICAL = "DOT_MEDICAL"
    CLP_PERMIT = "CLP_PERMIT"


class PrereqDocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ClockSessionPhase(str, Enum):
    CLASSROOM = "CLASSROOM"
    RANGE = "RANGE"
    ROAD = "ROAD"


class ClockSessionStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SkillsTestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SkillsTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    GRADED = "GRADED"
    VOIDED = "VOIDED"


class SponsorshipOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    FULFILLED = "FULFILLED"
    FORFEITED = "FORFEITED"


class FinancePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class CompletionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    TRANSMITTED = "TRANSMITTED"


class TruckStatus(str, Enum):
    AVAILABLE = "AVAILABLE"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"


# --- Entity TypedDicts -------------------------------------------------------

class Program(TypedDict):
    id: str
    name: str
    cdl_class: str
    classroom_required_hours: float
    range_required_hours: float
    road_required_hours: float
    tuition_cents: int
    skills_pass_threshold: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    unit_number: str
    cdl_class: str
    turnaround_buffer_minutes: int
    status: str
    reserved_minutes: int
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    cdl_class: str
    examiner_certified: bool
    status: str
    reserved_minutes: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    program_id: str
    student_name: str
    dot_medical_verified: bool
    permit_verified: bool
    status: str
    logged_classroom_hours: float
    logged_range_hours: float
    logged_road_hours: float
    projected_road_hours: float
    sponsoring_carrier_id: Optional[str]
    fmcsa_reported: bool
    created_at: str
    updated_at: str
    version: int


class PrereqDocument(TypedDict):
    id: str
    enrollment_id: str
    kind: str
    reference_code: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClockSession(TypedDict):
    id: str
    enrollment_id: str
    truck_id: Optional[str]
    instructor_id: str
    phase: str
    starts_at: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SkillsTest(TypedDict):
    id: str
    enrollment_id: str
    examiner_id: str
    supersedes_test_id: Optional[str]
    pre_trip_score: float
    basic_control_score: float
    road_score: float
    weighted_score: float
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict):
    id: str
    name: str
    commitment_months: int
    reimbursement_cents: int
    created_at: str
    updated_at: str
    version: int


class SponsorshipOffer(TypedDict):
    id: str
    enrollment_id: str
    carrier_id: str
    months_served: int
    clawback_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancePlan(TypedDict):
    id: str
    enrollment_id: str
    term_months: int
    tuition_cents: int
    down_payment_cents: int
    financed_cents: int
    total_interest_cents: int
    installment_cents: int
    final_installment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CompletionReport(TypedDict):
    id: str
    enrollment_id: str
    reported_classroom_hours: float
    reported_range_hours: float
    reported_road_hours: float
    passing_test_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
