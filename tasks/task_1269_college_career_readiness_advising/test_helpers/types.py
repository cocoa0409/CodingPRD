"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    """The five roles recognized by the API (PRD §2.1)."""
    DISTRICT_ADMIN = "DistrictAdmin"
    ADVISOR = "Advisor"
    STUDENT = "Student"
    TEACHER = "Teacher"
    WBL_COORDINATOR = "WblCoordinator"


class StudentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    GRADUATED = "GRADUATED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"
    WITHDRAWN = "WITHDRAWN"


class AdvisorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TeacherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PathwayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVISING = "REVISING"
    SUPERSEDED = "SUPERSEDED"


class EnrollmentStatus(str, Enum):
    PLANNED = "PLANNED"
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DROPPED = "DROPPED"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class DecisionStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    WAITLISTED = "WAITLISTED"
    DENIED = "DENIED"
    DEFERRED = "DEFERRED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    WAIVED = "WAIVED"


class MilestoneKind(str, Enum):
    ESSAY = "ESSAY"
    TRANSCRIPT = "TRANSCRIPT"
    FEE_PAYMENT = "FEE_PAYMENT"
    TEST_SCORES = "TEST_SCORES"
    REC_LETTERS = "REC_LETTERS"
    FAFSA = "FAFSA"
    INTERVIEW = "INTERVIEW"
    OTHER = "OTHER"


class RecRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    WITHDRAWN = "WITHDRAWN"


class CertificationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    EXAM_SCHEDULED = "EXAM_SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PlacementStatus(str, Enum):
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    TERMINATED = "TERMINATED"


class AuditStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    FLAGGED = "FLAGGED"
    CERTIFIED = "CERTIFIED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


class DemographicGroup(str, Enum):
    GROUP_A = "GROUP_A"
    GROUP_B = "GROUP_B"
    GROUP_C = "GROUP_C"
    GROUP_D = "GROUP_D"


class ProgramType(str, Enum):
    COLLEGE_4YR = "COLLEGE_4YR"
    COLLEGE_2YR = "COLLEGE_2YR"
    TRADE_PROGRAM = "TRADE_PROGRAM"


class OutcomeType(str, Enum):
    ENROLLED_4YR = "ENROLLED_4YR"
    ENROLLED_2YR = "ENROLLED_2YR"
    APPRENTICESHIP = "APPRENTICESHIP"
    EMPLOYED = "EMPLOYED"
    MILITARY = "MILITARY"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every entity carries the four system-managed properties
# id / created_at / updated_at / version (PRD §2.4).
# ---------------------------------------------------------------------------

class Student(TypedDict, total=False):
    id: str
    student_ref: str
    full_name: str
    grade_level: int
    demographic_group: str
    first_generation: bool
    status: str
    assigned_advisor_id: Optional[str]
    graduated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Advisor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    max_caseload: int
    status: str
    active_caseload_count: int
    caseload_load_simple: float
    caseload_load_weighted: float
    equity_gap_index: float
    target_caseload: float
    created_at: str
    updated_at: str
    version: int


class Teacher(TypedDict, total=False):
    id: str
    full_name: str
    department: str
    max_active_letters: int
    open_request_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pathway(TypedDict, total=False):
    id: str
    pathway_code: str
    name: str
    required_course_codes: List[str]
    required_certification_code: Optional[str]
    required_work_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StudentPlan(TypedDict, total=False):
    id: str
    student_id: str
    pathway_id: str
    interest_inventory: List[Dict[str, Any]]
    status: str
    alignment_provisional_pct: float
    alignment_official_pct: float
    milestone_pct: float
    milestone_pct_lenient: float
    wbl_hours_pct: float
    certification_points: float
    readiness_provisional: float
    readiness_official: float
    created_at: str
    updated_at: str
    version: int


class CourseEnrollment(TypedDict, total=False):
    id: str
    student_id: str
    plan_id: str
    course_code: str
    term: str
    credits: float
    grade: Optional[str]
    status: str
    counts_toward_pathway: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    student_id: str
    college_name: str
    program_type: str
    deadline_at: str
    submission_status: str
    decision_status: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApplicationMilestone(TypedDict, total=False):
    id: str
    application_id: str
    kind: str
    required: bool
    due_at: str
    depends_on_milestone_id: Optional[str]
    status: str
    completed_at: Optional[str]
    last_reminder_sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecommendationRequest(TypedDict, total=False):
    id: str
    student_id: str
    teacher_id: str
    application_id: Optional[str]
    due_at: str
    status: str
    reroute_count: int
    submitted_at: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    student_id: str
    cert_code: str
    status: str
    exam_at: Optional[str]
    earned_at: Optional[str]
    retake_count: int
    created_at: str
    updated_at: str
    version: int


class PlacementSite(TypedDict, total=False):
    id: str
    site_code: str
    name: str
    max_concurrent_placements: int
    status: str
    confirmed_active_count: int
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict, total=False):
    id: str
    student_id: str
    site_id: str
    term_start: str
    term_end: str
    hours_per_week: float
    status: str
    hours_logged: float
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeniorAudit(TypedDict, total=False):
    id: str
    student_id: str
    auditor_advisor_id: str
    status: str
    flag_reason: Optional[str]
    required_credits: float
    credits_earned: float
    pathway_requirements_met: bool
    certification_requirement_met: bool
    work_hours_met: bool
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutcomeRecord(TypedDict, total=False):
    id: str
    student_id: str
    outcome_type: str
    institution_name: Optional[str]
    reported_at: str
    verification_status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OpsRun(TypedDict, total=False):
    id: str
    run_index: int
    executed_at: str
    milestones_marked_missed: int
    applications_regressed: int
    reminders_queued: int
    plans_recomputed: int
    created_at: str
    updated_at: str
    version: int


class EquityReport(TypedDict, total=False):
    advisor_id: str
    active_caseload_count: int
    caseload_load_simple: float
    caseload_load_weighted: float
    equity_gap_index: float
    target_caseload: float
    district_total_students: int
    district_total_capacity: int
