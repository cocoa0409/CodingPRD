"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-4)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD section 2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    APPLICANT = "Applicant"
    INTAKE_OFFICER = "IntakeOfficer"
    CREDENTIAL_EVALUATOR = "CredentialEvaluator"
    BACKGROUND_INVESTIGATOR = "BackgroundInvestigator"
    LEGAL_OFFICER = "LegalOfficer"
    PROGRAM_APPROVAL_OFFICER = "ProgramApprovalOfficer"
    AGENCY_ADMIN = "AgencyAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD section 3)
# ---------------------------------------------------------------------------

class ApplicantStatus(str, Enum):
    REGISTERED = "REGISTERED"
    APPLICATION_IN_PROGRESS = "APPLICATION_IN_PROGRESS"
    LICENSED = "LICENSED"
    BARRED = "BARRED"


class ProgramApprovalStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PROBATION = "PROBATION"
    APPROVAL_WITHDRAWN = "APPROVAL_WITHDRAWN"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INTAKE_REVIEW = "INTAKE_REVIEW"
    EVALUATION = "EVALUATION"
    DEFICIENCY_PENDING = "DEFICIENCY_PENDING"
    BACKGROUND_REVIEW = "BACKGROUND_REVIEW"
    PENDING_DECISION = "PENDING_DECISION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class FeeStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class Pathway(str, Enum):
    TRADITIONAL = "TRADITIONAL"
    ALTERNATIVE = "ALTERNATIVE"
    RECIPROCITY = "RECIPROCITY"
    REINSTATEMENT = "REINSTATEMENT"


class SubjectArea(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    MATHEMATICS = "MATHEMATICS"
    SCIENCE = "SCIENCE"
    SPECIAL_EDUCATION = "SPECIAL_EDUCATION"


class GradeBand(str, Enum):
    PK_6 = "PK_6"
    G5_8 = "G5_8"
    G7_12 = "G7_12"


class DegreeLevel(str, Enum):
    BACHELORS = "BACHELORS"
    MASTERS = "MASTERS"
    DOCTORATE = "DOCTORATE"


class LetterGrade(str, Enum):
    A = "A"
    A_MINUS = "A_MINUS"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ExamCode(str, Enum):
    PRAXIS_CORE = "PRAXIS_CORE"
    PRAXIS_SUBJECT = "PRAXIS_SUBJECT"
    PEDAGOGY = "PEDAGOGY"


class TestScoreStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class BackgroundCheckStatus(str, Enum):
    INITIATED = "INITIATED"
    PRINTS_SUBMITTED = "PRINTS_SUBMITTED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    ADJUDICATION = "ADJUDICATION"
    DENIED = "DENIED"


class OffenseCategory(str, Enum):
    FELONY_VIOLENT = "FELONY_VIOLENT"
    FELONY_OTHER = "FELONY_OTHER"
    MISDEMEANOR_DRUG = "MISDEMEANOR_DRUG"
    MISDEMEANOR_OTHER = "MISDEMEANOR_OTHER"
    INFRACTION = "INFRACTION"


class Disposition(str, Enum):
    CONVICTION = "CONVICTION"
    DISMISSED = "DISMISSED"
    PENDING = "PENDING"


class LicenseType(str, Enum):
    STANDARD = "STANDARD"
    PROFESSIONAL = "PROFESSIONAL"
    PROVISIONAL = "PROVISIONAL"


class MappingMode(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    COMMITTEE = "COMMITTEE"


class ReciprocityOutcome(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"


class DeficiencyPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    EXTENDED = "EXTENDED"
    SUPERSEDED = "SUPERSEDED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    SURRENDERED = "SURRENDERED"


class EndorsementStatus(str, Enum):
    PENDING_EVALUATION = "PENDING_EVALUATION"
    ACTIVE = "ACTIVE"
    DENIED = "DENIED"
    REMOVED = "REMOVED"
    REVOKED = "REVOKED"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CONVERTED = "CONVERTED"
    REVOKED = "REVOKED"


class CECreditCategory(str, Enum):
    PEDAGOGY = "PEDAGOGY"
    CONTENT = "CONTENT"
    ETHICS = "ETHICS"
    TECHNOLOGY = "TECHNOLOGY"


class CECreditStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class AuditVariant(str, Enum):
    STANDARD = "STANDARD"
    RESTORATION = "RESTORATION"


class CEAuditStatus(str, Enum):
    INITIATED = "INITIATED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REMEDIATION = "REMEDIATION"


class AllegationCategory(str, Enum):
    BOUNDARY_VIOLATION = "BOUNDARY_VIOLATION"
    FINANCIAL_MISCONDUCT = "FINANCIAL_MISCONDUCT"
    INCOMPETENCE = "INCOMPETENCE"
    CRIMINAL_CONDUCT = "CRIMINAL_CONDUCT"


class Finding(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class MisconductCaseStatus(str, Enum):
    OPENED = "OPENED"
    INVESTIGATING = "INVESTIGATING"
    HEARING = "HEARING"
    ADJUDICATED = "ADJUDICATED"
    SANCTION_ISSUED = "SANCTION_ISSUED"
    DISMISSED = "DISMISSED"


class SanctionType(str, Enum):
    REPRIMAND = "REPRIMAND"
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"
    FINE = "FINE"


class DisciplinaryActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ISSUED = "ISSUED"
    SERVED = "SERVED"
    VACATED = "VACATED"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every entity in this PRD carries the common fields
# id + created_at + updated_at + version (PRD section 2.4).
# ---------------------------------------------------------------------------

class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    ssn_last4: str
    moral_character_attestation: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EducatorPrepProgram(TypedDict):
    id: str
    institution_name: str
    program_code: str
    approved_subject_areas: List[str]
    approval_status: str
    created_at: str
    updated_at: str
    version: int


class CredentialApplication(TypedDict):
    id: str
    applicant_id: str
    pathway: str
    subject_area: str
    grade_band: str
    program_id: Optional[str]
    expedite_requested: bool
    fee_cents: int
    fee_status: str
    status: str
    deficiency_hours_required: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    course_code: str
    credit_hours: float
    letter_grade: str


class Transcript(TypedDict):
    id: str
    application_id: str
    institution_name: str
    degree_level: str
    total_semester_hours: float
    courses: List[Course]
    scaled_gpa: Optional[float]
    subject_relevant_hours: Optional[float]
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class TestScore(TypedDict):
    id: str
    application_id: str
    exam_code: str
    raw_score: int
    scaled_score: Optional[int]
    passing: Optional[bool]
    tested_on: str
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class AdverseFinding(TypedDict):
    offense_category: str
    offense_date: str
    disposition: str


class BackgroundCheck(TypedDict):
    id: str
    application_id: str
    adverse_findings: List[AdverseFinding]
    fingerprint_submitted_at: Optional[str]
    risk_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReciprocityEvaluation(TypedDict):
    id: str
    application_id: str
    source_state: str
    source_license_type: str
    years_teaching: int
    mapping_mode: Optional[str]
    outcome: Optional[str]
    deficiency_subject_hours: Optional[int]
    finalized: bool
    created_at: str
    updated_at: str
    version: int


class DeficiencyPlan(TypedDict):
    id: str
    application_id: str
    required_hours: int
    completed_hours: int
    deadline: str
    extension_used: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    application_id: str
    applicant_id: str
    license_number: str
    subject_area: str
    grade_band: str
    issued_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict):
    id: str
    license_id: str
    subject_area: str
    grade_band: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EmergencyPermit(TypedDict):
    id: str
    application_id: str
    applicant_id: str
    district_code: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CECredit(TypedDict):
    id: str
    license_id: str
    provider_name: str
    category: str
    hours: float
    earned_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CEAudit(TypedDict):
    id: str
    license_id: str
    audit_variant: str
    cycle_start: str
    cycle_end: str
    required_hours: int
    verified_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MisconductCase(TypedDict):
    id: str
    license_id: str
    allegation_category: str
    investigator_user_id: Optional[str]
    finding: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisciplinaryAction(TypedDict):
    id: str
    case_id: str
    license_id: str
    sanction_type: str
    suspension_start: Optional[str]
    suspension_end: Optional[str]
    fine_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
