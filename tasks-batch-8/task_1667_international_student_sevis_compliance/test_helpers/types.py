"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PDSO = "PDSO"
    DSO = "DSO"
    STUDENT = "Student"


class DegreeLevel(str, Enum):
    UNDERGRADUATE = "UNDERGRADUATE"
    GRADUATE = "GRADUATE"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    AT_RISK = "AT_RISK"
    VIOLATION_OPEN = "VIOLATION_OPEN"


class DocumentType(str, Enum):
    BANK_STATEMENT = "BANK_STATEMENT"
    SCHOLARSHIP_LETTER = "SCHOLARSHIP_LETTER"
    SPONSOR_AFFIDAVIT = "SPONSOR_AFFIDAVIT"


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SevisRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    INITIAL = "INITIAL"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"
    REINSTATEMENT_PENDING = "REINSTATEMENT_PENDING"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class I20FormStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"
    NOT_ENROLLED = "NOT_ENROLLED"
    COMPLETED = "COMPLETED"


class RclReasonCategory(str, Enum):
    ACADEMIC = "ACADEMIC"
    MEDICAL = "MEDICAL"
    FINAL_TERM = "FINAL_TERM"


class RclStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AuthType(str, Enum):
    CPT = "CPT"
    OPT_PRE = "OPT_PRE"
    OPT_POST = "OPT_POST"


class AuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    RECOMMENDED = "RECOMMENDED"
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    REVOKED = "REVOKED"


class EndorsementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class TransferDirection(str, Enum):
    OUT = "OUT"
    IN = "IN"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class ExtensionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ViolationType(str, Enum):
    FAILURE_TO_ENROLL = "FAILURE_TO_ENROLL"
    UNAUTHORIZED_EMPLOYMENT = "UNAUTHORIZED_EMPLOYMENT"
    UNEMPLOYMENT_LIMIT_EXCEEDED = "UNEMPLOYMENT_LIMIT_EXCEEDED"
    ADDRESS_REPORT_OVERDUE = "ADDRESS_REPORT_OVERDUE"
    OTHER = "OTHER"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    REINSTATEMENT_PENDING = "REINSTATEMENT_PENDING"
    RESOLVED_REINSTATED = "RESOLVED_REINSTATED"
    RESOLVED_DENIED = "RESOLVED_DENIED"
    DISMISSED = "DISMISSED"


class AddressReportStatus(str, Enum):
    REPORTED = "REPORTED"
    FLAGGED_LATE = "FLAGGED_LATE"


# ---------------------------------------------------------------------------
# Entity payloads. All resources here carry the standard system-managed
# fields id / created_at / updated_at / version (PRD §2.4).
# ---------------------------------------------------------------------------


class Student(TypedDict, total=False):
    id: str
    sevis_id: str
    full_name: str
    email: str
    date_of_birth: str
    country_of_citizenship: str
    degree_level: str
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class FinancialDocument(TypedDict, total=False):
    id: str
    student_id: str
    document_type: str
    amount_usd_cents: int
    issue_date: str
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SevisRecord(TypedDict, total=False):
    id: str
    student_id: str
    program_start_date: str
    program_end_date: str
    status: str
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class I20Form(TypedDict, total=False):
    id: str
    student_id: str
    sevis_record_id: str
    program_name: str
    program_start_date: Optional[str]
    program_end_date: Optional[str]
    tuition_cents: int
    living_cents: int
    insurance_cents: int
    other_cents: int
    estimated_total_cents: int
    verified_funding_cents: Optional[int]
    provisional_funding_cents: Optional[int]
    supersedes_i20_form_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TermEnrollment(TypedDict, total=False):
    id: str
    student_id: str
    term_code: str
    term_start_date: str
    term_end_date: str
    enrolled_credits: int
    effective_min_credits: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReducedCourseLoad(TypedDict, total=False):
    id: str
    enrollment_id: str
    reason_category: str
    requested_credits: int
    status: str
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmploymentAuthorization(TypedDict, total=False):
    id: str
    student_id: str
    auth_type: str
    employer_name: Optional[str]
    hours_per_week: int
    start_date: str
    end_date: str
    uscis_receipt_number: Optional[str]
    unemployment_days_settled: int
    unemployment_days_as_of: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EmploymentPeriod(TypedDict, total=False):
    id: str
    authorization_id: str
    employer_name: str
    start_date: str
    end_date: Optional[str]
    hours_per_week: int
    created_at: str
    updated_at: str
    version: int


class TravelEndorsement(TypedDict, total=False):
    id: str
    i20_form_id: str
    travel_departure_date: str
    travel_return_date: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict, total=False):
    id: str
    student_id: str
    direction: str
    target_school_code: str
    release_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramExtension(TypedDict, total=False):
    id: str
    student_id: str
    new_program_end_date: str
    reason: str
    status: str
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StatusViolation(TypedDict, total=False):
    id: str
    student_id: str
    violation_type: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AddressReport(TypedDict, total=False):
    id: str
    student_id: str
    move_date: str
    address_line1: str
    city: str
    state_code: str
    postal_code: str
    status: str
    created_at: str
    updated_at: str
    version: int
