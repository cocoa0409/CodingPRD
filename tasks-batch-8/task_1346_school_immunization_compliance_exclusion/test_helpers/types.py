"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2.1, 2.5, 3.x)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    HEALTH_CLERK = "HealthClerk"
    SCHOOL_NURSE = "SchoolNurse"
    DISTRICT_HEALTH_OFFICER = "DistrictHealthOfficer"
    REGISTRY_COORDINATOR = "RegistryCoordinator"


class Grade(str, Enum):
    PK = "PK"
    K = "K"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"
    G8 = "G8"
    G9 = "G9"
    G10 = "G10"
    G11 = "G11"
    G12 = "G12"


class VaccineCode(str, Enum):
    DTAP = "DTAP"
    IPV = "IPV"
    MMR = "MMR"
    HEPB = "HEPB"
    VAR = "VAR"
    HIB = "HIB"
    PCV = "PCV"
    HEPA = "HEPA"


class StudentStatus(str, Enum):
    ENROLLED_PROVISIONAL = "ENROLLED_PROVISIONAL"
    ENROLLED_COMPLIANT = "ENROLLED_COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    EXCLUDED = "EXCLUDED"
    WITHDRAWN = "WITHDRAWN"


class RecordStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class RecordSource(str, Enum):
    MANUAL = "MANUAL"
    CLINIC = "CLINIC"
    REGISTRY_IMPORT = "REGISTRY_IMPORT"


class ExemptionType(str, Enum):
    MEDICAL = "MEDICAL"
    RELIGIOUS = "RELIGIOUS"


class ExemptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUSPENDED_OUTBREAK = "SUSPENDED_OUTBREAK"


class NoticeType(str, Enum):
    INITIAL_NONCOMPLIANCE = "INITIAL_NONCOMPLIANCE"
    OUTBREAK_EXCLUSION = "OUTBREAK_EXCLUSION"


class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    CURED = "CURED"
    RESCINDED = "RESCINDED"
    EXCLUSION_EFFECTIVE = "EXCLUSION_EFFECTIVE"


class OutbreakStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SyncRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class SnapshotStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class RateVariant(str, Enum):
    CENSUS_DATE = "CENSUS_DATE"
    EVER_ENROLLED = "EVER_ENROLLED"


# All resources carry the standard system-managed fields of PRD section 2.5:
# id, created_at, updated_at, version.


class Student(TypedDict):
    id: str
    legal_name: str
    date_of_birth: str
    grade: str
    school_code: str
    enrollment_date: str
    status: str
    provisional_deadline: str
    deficiency_vaccine_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class VaccineRequirement(TypedDict):
    id: str
    vaccine_code: str
    applies_to_grades: List[str]
    doses_required: int
    min_interval_days: int
    min_age_months: int
    school_year: str
    created_at: str
    updated_at: str
    version: int


class ImmunizationRecord(TypedDict):
    id: str
    student_id: str
    vaccine_code: str
    dose_number: int
    administered_date: str
    source: str
    clinic_appointment_id: Optional[str]
    status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExemptionRequest(TypedDict):
    id: str
    student_id: str
    vaccine_code: str
    exemption_type: str
    document_ref: str
    status: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceNotice(TypedDict):
    id: str
    student_id: str
    notice_type: str
    status: str
    issue_date: str
    exclusion_date: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutbreakEvent(TypedDict):
    id: str
    school_code: str
    vaccine_code: str
    status: str
    declared_at: str
    lifted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClinicSession(TypedDict):
    id: str
    school_code: str
    session_date: str
    duration_minutes: int
    capacity: int
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClinicAppointment(TypedDict):
    id: str
    clinic_session_id: str
    student_id: str
    vaccine_code: str
    start_time: str
    end_time: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistrySyncRun(TypedDict):
    id: str
    school_code: str
    status: str
    registry_doses_seen: int
    imported_count: int
    matched_count: int
    discrepancy_count: int
    created_at: str
    updated_at: str
    version: int


class ComplianceSnapshot(TypedDict):
    id: str
    school_year: str
    school_code: str
    grade: str
    census_date: str
    rate_variant: str
    enrolled_count: int
    compliant_count: int
    exempt_count: int
    compliance_rate: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int
