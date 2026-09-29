"""Domain types for the professional engineering licensure & comity API.

Status enums, entity TypedDicts and the role enum described by the PRD.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    SUPERVISING_ENGINEER = "SupervisingEngineer"
    LICENSEE = "Licensee"
    FIRM_ADMIN = "FirmAdmin"
    BOARD_REVIEWER = "BoardReviewer"
    BOARD_LICENSING_OFFICER = "BoardLicensingOfficer"
    BOARD_INVESTIGATOR = "BoardInvestigator"
    BOARD_SECRETARY = "BoardSecretary"
    TESTING_SERVICE = "TestingService"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class LicenseType(str, Enum):
    STANDARD = "STANDARD"
    COMITY = "COMITY"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DEFICIENT = "DEFICIENT"
    EXAM_APPROVED = "EXAM_APPROVED"
    LICENSE_ISSUED = "LICENSE_ISSUED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class EducationStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    EABET_ACCREDITED = "EABET_ACCREDITED"
    NON_ACCREDITED_EVALUATED = "NON_ACCREDITED_EVALUATED"
    REJECTED = "REJECTED"


class Pathway(str, Enum):
    STANDARD_EXAM = "STANDARD_EXAM"
    COMITY = "COMITY"


class ExamCode(str, Enum):
    PE_CIVIL = "PE_CIVIL"
    PE_MECHANICAL = "PE_MECHANICAL"
    PE_ELECTRICAL = "PE_ELECTRICAL"


class DegreeLevel(str, Enum):
    BS = "BS"
    MS = "MS"
    PHD = "PHD"


class NceesRecordStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"


class ResponsibilityLevel(str, Enum):
    SUBORDINATE = "SUBORDINATE"
    PROGRESSIVE = "PROGRESSIVE"
    RESPONSIBLE_CHARGE = "RESPONSIBLE_CHARGE"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    RECANTED = "RECANTED"


class ReferenceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RECANTED = "RECANTED"


class Relationship(str, Enum):
    DIRECT_SUPERVISOR = "DIRECT_SUPERVISOR"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    PEER = "PEER"


class TestCenterStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class ExamAuthorizationStatus(str, Enum):
    APPROVED_TO_SIT = "APPROVED_TO_SIT"
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ExamResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class ExamAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED_BY_CANDIDATE = "CANCELLED_BY_CANDIDATE"
    CANCELLED_BY_BOARD = "CANCELLED_BY_BOARD"


class FirmRegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED_NO_RESPONSIBLE_CHARGE = "LAPSED_NO_RESPONSIBLE_CHARGE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PlanSubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    FLAGGED = "FLAGGED"
    VOIDED = "VOIDED"


class CPCAuditStatus(str, Enum):
    SAMPLED = "SAMPLED"
    CLOSED = "CLOSED"


class CPCReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"
    ACCEPTED = "ACCEPTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    AUDIT_CLEARED = "AUDIT_CLEARED"
    AUDIT_DEFICIENT = "AUDIT_DEFICIENT"


class ActivityType(str, Enum):
    COURSE = "COURSE"
    SEMINAR = "SEMINAR"
    TEACHING = "TEACHING"
    PUBLICATION = "PUBLICATION"
    PATENT = "PATENT"
    SELF_STUDY = "SELF_STUDY"


class DocumentationStatus(str, Enum):
    NONE = "NONE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AllegationType(str, Enum):
    NEGLIGENCE = "NEGLIGENCE"
    UNLICENSED_PRACTICE = "UNLICENSED_PRACTICE"
    PLAN_STAMPING = "PLAN_STAMPING"
    CPC_FRAUD = "CPC_FRAUD"


class InvestigationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INVESTIGATING = "INVESTIGATING"
    PROBABLE_CAUSE = "PROBABLE_CAUSE"
    NO_CAUSE = "NO_CAUSE"
    CLOSED = "CLOSED"


class SanctionStatus(str, Enum):
    NONE = "NONE"
    PROPOSED = "PROPOSED"
    CONSENT_EXECUTED = "CONSENT_EXECUTED"
    HEARING_REFERRED = "HEARING_REFERRED"


class SanctionType(str, Enum):
    REPRIMAND = "REPRIMAND"
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"


class ConsentOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SUPERSEDED = "SUPERSEDED"
    EXECUTED = "EXECUTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Every entity except PDHRecord carries the common fields id, created_at,
# updated_at and version.  PDHRecord is append-only: it exposes only id and
# created_at (PRD 2.4).
# ---------------------------------------------------------------------------
class Engineer(TypedDict):
    id: str
    full_name: str
    email: str
    home_jurisdiction: str
    ncees_record_id: Optional[str]
    active_license_number: Optional[str]
    open_case_count: int
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    engineer_id: str
    license_number: str
    license_type: str
    status: str
    issued_on: str
    current_period_start: str
    current_period_end: str
    renewal_window_opens_at: str
    pdh_requirement: float
    reinstatement_eligible_until: Optional[str]
    suspension_ends_at: Optional[str]
    discipline_flag: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    engineer_id: str
    pathway: str
    exam_code: str
    expedite_requested: bool
    status: str
    education_status: str
    degree_level: Optional[str]
    provisional_experience_months: int
    verified_experience_months: int
    credit_determined_by_user_id: Optional[str]
    reviewer_user_id: Optional[str]
    deficiency_cycle_count: int
    deficiency_reason: Optional[str]
    deficiency_due_at: Optional[str]
    fee_assessment_cents: int
    fee_paid_cents: int
    submitted_at: Optional[str]
    ncees_record_status: str
    ncees_verified_exam_pass: bool
    ncees_verified_years_licensed: int
    ncees_disciplinary_history_count: int
    ncees_record_expires_on: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExperienceRecord(TypedDict):
    id: str
    application_id: str
    employer_name: str
    position_title: str
    period_start_month: str
    period_end_month: str
    responsibility_level: str
    post_degree: bool
    raw_months: int
    credit_multiplier: float
    credited_months: int
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class Reference(TypedDict):
    id: str
    experience_record_id: str
    referee_engineer_id: str
    relationship: str
    status: str
    evaluation_score: Optional[int]
    months_confirmed: Optional[int]
    responsibility_confirmed: Optional[bool]
    submitted_at: Optional[str]
    recant_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestCenter(TypedDict):
    id: str
    name: str
    state_code: str
    seat_labels: List[str]
    seat_count: int
    seats_committed: int
    seats_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExamAuthorization(TypedDict):
    id: str
    application_id: str
    exam_code: str
    status: str
    authorization_expires_at: str
    attempt_number: int
    raw_score: Optional[int]
    result: str
    retake_eligible_at: Optional[str]
    ncees_transmission_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamAppointment(TypedDict):
    id: str
    exam_authorization_id: str
    test_center_id: str
    seat_label: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FirmRegistration(TypedDict):
    id: str
    firm_name: str
    state_code: str
    responsible_charge_license_id: str
    status: str
    registration_expires_at: str
    lapsed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanSubmission(TypedDict):
    id: str
    firm_registration_id: str
    project_name: str
    sheet_count: int
    sealing_license_id: Optional[str]
    responsible_charge_attested: bool
    seal_affixed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CPCAudit(TypedDict):
    id: str
    audit_cycle_label: str
    sample_pct: float
    as_of_period_end: str
    pool_size: int
    sampled_count: int
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CPCReport(TypedDict):
    id: str
    license_id: str
    period_start: str
    period_end: str
    self_certified_pdh: float
    carryover_pdh_claimed: float
    self_certified_total_pdh: float
    audit_verified_total_pdh: float
    shortfall_pdh: float
    audit_id: Optional[str]
    supersedes_report_id: Optional[str]
    audit_decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PDHRecord(TypedDict):
    """Append-only: exposes only id and created_at, never updated_at/version."""

    id: str
    cpc_report_id: str
    activity_type: str
    pdh_hours: float
    completed_on: str
    ethics_flag: bool
    documentation_status: str
    created_at: str


class Case(TypedDict):
    id: str
    allegation_type: str
    respondent_license_id: Optional[str]
    subject_plan_submission_id: Optional[str]
    unlicensed_respondent_name: Optional[str]
    complainant_name: str
    received_on: str
    investigation_status: str
    sanction_status: str
    assigned_investigator_user_id: Optional[str]
    aggravating_factor_count: int
    mitigating_factor_count: int
    violation_count: int
    penalty_factor: float
    assessed_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class ConsentOrder(TypedDict):
    id: str
    case_id: str
    sanction_type: str
    suspension_months: int
    penalty_cents: int
    penalty_paid_cents: int
    executed_on: Optional[str]
    executed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
