"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    VOLUNTEER = "Volunteer"
    APPLICANT = "Applicant"


class ApplicantStage(str, Enum):
    REGISTERED = "REGISTERED"
    SCREENED = "SCREENED"
    IN_PIPELINE = "IN_PIPELINE"
    FILED = "FILED"
    NATURALIZED = "NATURALIZED"


class ScreeningOutcome(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    ELIGIBLE_WITH_EXEMPTION = "ELIGIBLE_WITH_EXEMPTION"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ScreeningStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    PENDING_PROMOTION = "PENDING_PROMOTION"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"


class AttendanceOutcome(str, Enum):
    PRESENT = "PRESENT"
    ABSENT_EXCUSED = "ABSENT_EXCUSED"
    ABSENT_UNEXCUSED = "ABSENT_UNEXCUSED"


class AccreditationLevel(str, Enum):
    TRAINEE = "TRAINEE"
    GENERAL = "GENERAL"
    LEGAL = "LEGAL"
    LAPSED = "LAPSED"


class WorkshopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    COMPLETION_REVERSED = "COMPLETION_REVERSED"
    CANCELLED = "CANCELLED"


class WorkshopSeatStatus(str, Enum):
    RESERVED = "RESERVED"
    ATTENDED = "ATTENDED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class PacketStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_LEGAL_REVIEW = "IN_LEGAL_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    CERTIFIED = "CERTIFIED"
    FILED = "FILED"


class FeeWaiverTier(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"


class FeeWaiverStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class CaseStage(str, Enum):
    FILED = "FILED"
    RECEIPTED = "RECEIPTED"
    BIOMETRICS_COMPLETE = "BIOMETRICS_COMPLETE"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEW_PASSED = "INTERVIEW_PASSED"
    APPROVED_PENDING_OATH = "APPROVED_PENDING_OATH"
    OATH_SCHEDULED = "OATH_SCHEDULED"
    NATURALIZED = "NATURALIZED"
    APPLICATION_DENIED = "APPLICATION_DENIED"


class RfeStatus(str, Enum):
    NONE = "NONE"
    ISSUED = "ISSUED"
    RESPONDED = "RESPONDED"
    OVERDUE = "OVERDUE"


class MockInterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class MockOutcome(str, Enum):
    PASS = "PASS"
    NEEDS_RETRY = "NEEDS_RETRY"


class CeremonyStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONCLUDED = "CONCLUDED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# Attendance events and training credits are append-only: id + created_at only.


class Program(TypedDict):
    id: str
    name: str
    n400_fee_cents: int
    biometric_fee_cents: int
    translation_stipend_cents: int
    poverty_base_cents: int
    poverty_per_additional_cents: int
    full_waiver_threshold_pct: int
    partial_waiver_threshold_pct: int
    attendance_complete_bp: int
    attendance_midterm_floor_bp: int
    readiness_certify_threshold: int
    rfe_deadline_days: int
    accreditation_valid_months: int
    general_training_hours: int
    legal_supervised_hours: int
    renewal_training_hours: int
    promotion_offer_hours: int
    mock_buffer_minutes: int
    mock_max_attempts: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    preferred_language: str
    stage: str
    current_screening_id: Optional[str]
    voter_registration_referred: bool
    created_at: str
    updated_at: str
    version: int


class Screening(TypedDict):
    id: str
    applicant_id: str
    marital_to_citizen: bool
    lpr_months: int
    continuous_residence_months: int
    physical_presence_days: int
    age_years: int
    english_level: int
    civics_practice_pct: int
    has_legal_flag: bool
    outcome: str
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class ClassSection(TypedDict):
    id: str
    title: str
    weekday: str
    start_minute: int
    end_minute: int
    room_id: str
    instructor_volunteer_id: str
    capacity: int
    total_sessions: int
    enrolled_count: int
    pending_promotion_count: int
    waitlisted_count: int
    seats_open: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    applicant_id: str
    class_section_id: str
    status: str
    attendance_bp: int
    records_count: int
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict):
    # Append-only event log: carries only id + created_at (no updated_at, no version).
    id: str
    enrollment_id: str
    session_index: int
    outcome: str
    created_at: str


class Volunteer(TypedDict):
    id: str
    full_name: str
    email: str
    background_check_cleared: bool
    bar_number: Optional[str]
    accreditation_level: str
    lapsed_from_level: Optional[str]
    accredited_at: Optional[str]
    training_hours_24mo: int
    supervised_hours: int
    created_at: str
    updated_at: str
    version: int


class TrainingCredit(TypedDict):
    # Append-only event log: carries only id + created_at (no updated_at, no version).
    id: str
    volunteer_id: str
    topic: str
    hours: int
    earned_at: str
    created_at: str


class Workshop(TypedDict):
    id: str
    title: str
    supervising_volunteer_id: str
    assisting_volunteer_id: Optional[str]
    scheduled_start: str
    duration_hours: int
    capacity: int
    reserved_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkshopSeat(TypedDict):
    id: str
    workshop_id: str
    applicant_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ApplicationPacket(TypedDict):
    id: str
    applicant_id: str
    workshop_seat_id: str
    prepared_by_volunteer_id: str
    fee_waiver_request_id: Optional[str]
    status: str
    certified_by_volunteer_id: Optional[str]
    filing_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FeeWaiverRequest(TypedDict):
    id: str
    applicant_id: str
    household_size: int
    self_reported_income_cents: int
    self_reported_benefit: bool
    provisional_tier: str
    attached_document_count: int
    required_document_count: int
    status: str
    documented_income_cents: Optional[int]
    documented_benefit: Optional[bool]
    final_tier: Optional[str]
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class USCISCase(TypedDict):
    id: str
    applicant_id: str
    packet_id: str
    receipt_number: str
    stage: str
    rfe_status: str
    rfe_issued_at: Optional[str]
    rfe_deadline: Optional[str]
    oath_ceremony_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MockInterview(TypedDict):
    id: str
    applicant_id: str
    volunteer_id: str
    scheduled_start: str
    duration_minutes: int
    status: str
    english_pct: Optional[int]
    civics_pct: Optional[int]
    n400_pct: Optional[int]
    overall_score: Optional[int]
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OathCeremony(TypedDict):
    id: str
    ceremony_date: str
    venue: str
    capacity: int
    assigned_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
