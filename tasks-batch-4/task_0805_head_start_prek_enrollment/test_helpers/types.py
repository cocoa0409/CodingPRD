"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    ENROLLMENT_SPECIALIST = "EnrollmentSpecialist"
    FAMILY_SERVICES_WORKER = "FamilyServicesWorker"
    FAMILY = "Family"


# ---------------------------------------------------------------------------
# Status / enum domains
# ---------------------------------------------------------------------------
class ProgramType(str, Enum):
    HEAD_START = "HEAD_START"
    PRE_K = "PRE_K"
    EARLY_HEAD_START = "EARLY_HEAD_START"


class AgeBand(str, Enum):
    INFANT = "INFANT"
    TODDLER = "TODDLER"
    PRESCHOOL_3 = "PRESCHOOL_3"
    PRESCHOOL_4 = "PRESCHOOL_4"


class CohortSelectionStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class CategoricalEligibility(str, Enum):
    NONE = "NONE"
    TANF = "TANF"
    SSI = "SSI"
    SNAP = "SNAP"
    FOSTER = "FOSTER"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    WAITLISTED = "WAITLISTED"
    OFFERED = "OFFERED"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class EligibilityCategory(str, Enum):
    HOMELESS = "HOMELESS"
    CATEGORICAL = "CATEGORICAL"
    INCOME = "INCOME"
    OVER_INCOME = "OVER_INCOME"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED_TRANSITION = "COMPLETED_TRANSITION"
    WITHDRAWN = "WITHDRAWN"
    DISENROLLED = "DISENROLLED"


class HealthComplianceStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    EXEMPT = "EXEMPT"


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT_EXCUSED = "ABSENT_EXCUSED"
    ABSENT_UNEXCUSED = "ABSENT_UNEXCUSED"


class ScreeningType(str, Enum):
    IMMUNIZATION = "IMMUNIZATION"
    PHYSICAL = "PHYSICAL"
    DENTAL = "DENTAL"


class ScreeningStatus(str, Enum):
    DUE = "DUE"
    UP_TO_DATE = "UP_TO_DATE"
    OVERDUE = "OVERDUE"
    EXEMPT = "EXEMPT"


class HomeVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class TransitionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PIRReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true — id + created_at + updated_at + version
class Program(TypedDict):
    id: str
    name: str
    program_type: str
    funded_enrollment: int
    age_cutoff_date: str
    total_instructional_days: int
    ada_chronic_threshold_pct: float
    created_at: str
    updated_at: str
    version: int


class AgeCohort(TypedDict):
    id: str
    program_id: str
    age_band: str
    funded_slots: int
    min_age_months: int
    max_age_months: int
    session_start: str
    session_end: str
    filled_slots: int
    reserved_slots: int
    available_slots: int
    selection_status: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict):
    id: str
    guardian_name: str
    household_size: int
    annual_income_cents: int
    categorical_eligibility: str
    homeless_status: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    program_id: str
    cohort_id: str
    family_id: str
    child_first_name: str
    child_last_name: str
    child_dob: str
    child_has_iep: bool
    verified_income_cents: Optional[int]
    status: str
    eligibility_category: Optional[str]
    income_ratio: Optional[float]
    age_months_at_cutoff: Optional[int]
    priority_points: Optional[int]
    submitted_at: Optional[str]
    waitlisted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    application_id: str
    cohort_id: str
    status: str
    offered_at: str
    offer_expires_at: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    application_id: str
    cohort_id: str
    status: str
    health_compliance_status: str
    enrolled_at: str
    ada_rate: float
    annualized_ada_rate: float
    unexcused_absence_rate: float
    chronic_absence: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only fact, ONLY id + created_at
class AttendanceRecord(TypedDict):
    id: str
    enrollment_id: str
    attendance_date: str
    status: str
    instructional_day: bool
    created_at: str


class HealthScreening(TypedDict):
    id: str
    enrollment_id: str
    screening_type: str
    status: str
    due_date: str
    completed_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HomeVisit(TypedDict):
    id: str
    enrollment_id: str
    scheduled_date: str
    window_start: str
    window_end: str
    visit_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransitionPlan(TypedDict):
    id: str
    enrollment_id: str
    target_school: str
    transition_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PIRReport(TypedDict):
    id: str
    program_id: str
    reporting_period: str
    total_enrolled: int
    income_eligible_count: int
    categorical_count: int
    homeless_count: int
    immunization_compliant_count: int
    avg_ada_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int
