"""Domain types: entity TypedDicts, status/tier enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (X-User-Role header values) ---
class UserRole(str, Enum):
    ADMINISTRATOR = "Administrator"
    ATTENDANCE_CLERK = "AttendanceClerk"
    CASE_MANAGER = "CaseManager"
    COURT_OFFICER = "CourtOfficer"


# --- Enumerations ---
class StaffRoleType(str, Enum):
    CASE_MANAGER = "CASE_MANAGER"
    OFFICER = "OFFICER"
    COUNSELOR = "COUNSELOR"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    TARDY = "TARDY"
    EXCUSED = "EXCUSED"
    UNEXCUSED = "UNEXCUSED"
    VOIDED = "VOIDED"


class CaseTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    COURT_REFERRED = "COURT_REFERRED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ConferenceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    BREACHED = "BREACHED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    MENTOR = "MENTOR"
    COUNSELING = "COUNSELING"
    HEALTH = "HEALTH"
    OTHER = "OTHER"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    DECLINED = "DECLINED"


class CitationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HEARD = "HEARD"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class ComplianceResult(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


# --- Entities (common_fields: true => id, created_at, updated_at, version) ---
class School(TypedDict):
    id: str
    name: str
    tier1_unexcused_threshold: int
    tier2_unexcused_threshold: int
    tier3_unexcused_threshold: int
    court_unexcused_threshold: int
    required_instructional_days: int
    chronic_absence_pct_threshold: float
    created_at: str
    updated_at: str
    version: int


class Staff(TypedDict):
    id: str
    school_id: str
    full_name: str
    role_type: str
    max_caseload: int
    active_caseload: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    school_id: str
    full_name: str
    grade_level: int
    enrollment_status: str
    present_count: int
    tardy_count: int
    excused_count: int
    unexcused_count: int
    attendance_rate_recorded: Optional[float]
    attendance_rate_official: Optional[float]
    chronic_absent: bool
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict):
    id: str
    student_id: str
    attendance_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TruancyCase(TypedDict):
    id: str
    student_id: str
    assigned_staff_id: Optional[str]
    tier: str
    status: str
    unexcused_at_open: int
    breach_count: int
    created_at: str
    updated_at: str
    version: int


class Conference(TypedDict):
    id: str
    case_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceContract(TypedDict):
    id: str
    case_id: str
    start_date: str
    end_date: str
    status: str
    goals: List[dict]
    compliance_score_actual: Optional[float]
    compliance_score_projected: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ServiceReferral(TypedDict):
    id: str
    case_id: str
    service_type: str
    provider_name: str
    status: str
    auto_created: bool
    created_at: str
    updated_at: str
    version: int


class CourtCitation(TypedDict):
    id: str
    case_id: str
    courtroom_id: str
    hearing_start: str
    hearing_end: str
    status: str
    disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false => append-only event, only id + created_at
class ComplianceCheck(TypedDict):
    id: str
    case_id: str
    check_date: str
    result: str
    notes: Optional[str]
    created_at: str
