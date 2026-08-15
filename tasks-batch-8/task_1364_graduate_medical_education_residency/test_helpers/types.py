"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    DIO = "DesignatedInstitutionalOfficial"
    PD = "ProgramDirector"
    PC = "ProgramCoordinator"
    RESIDENT = "Resident"
    FACULTY = "FacultyEvaluator"
    CCC_CHAIR = "CCCChair"


class Specialty(str, Enum):
    INTERNAL_MEDICINE = "INTERNAL_MEDICINE"
    GENERAL_SURGERY = "GENERAL_SURGERY"
    PEDIATRICS = "PEDIATRICS"
    EMERGENCY_MEDICINE = "EMERGENCY_MEDICINE"
    OBSTETRICS_GYNECOLOGY = "OBSTETRICS_GYNECOLOGY"


class AccreditationStatus(str, Enum):
    CONTINUED = "CONTINUED"
    CONTINUED_WITH_WARNING = "CONTINUED_WITH_WARNING"
    PROBATIONARY = "PROBATIONARY"


class AcademicYearStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ScheduleBlockStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class ComplementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    LOCKED = "LOCKED"


class LifecycleStatus(str, Enum):
    INCOMING = "INCOMING"
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    GRADUATED = "GRADUATED"
    DISMISSED = "DISMISSED"
    TRANSFERRED = "TRANSFERRED"


class StandingStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    UNDER_REMEDIATION = "UNDER_REMEDIATION"
    ON_PROBATION = "ON_PROBATION"


class RotationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AssignmentStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DutyLogStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ATTESTED = "ATTESTED"
    VOID = "VOID"


class ViolationRule(str, Enum):
    HOURS_80_AVG = "HOURS_80_AVG"
    REST_8H = "REST_8H"
    DAY_OFF_4_IN_28 = "DAY_OFF_4_IN_28"


class ViolationStatus(str, Enum):
    FLAGGED = "FLAGGED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class MoonlightingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    REVOKED = "REVOKED"
    WITHDRAWN = "WITHDRAWN"


class MoonlightingType(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class EvaluatorRole(str, Enum):
    FACULTY = "FACULTY"
    PROGRAM_DIRECTOR = "PROGRAM_DIRECTOR"


class ReportingPeriod(str, Enum):
    H1 = "H1"
    H2 = "H2"


class Competency(str, Enum):
    PATIENT_CARE = "PATIENT_CARE"
    MEDICAL_KNOWLEDGE = "MEDICAL_KNOWLEDGE"
    PROFESSIONALISM = "PROFESSIONALISM"
    COMMUNICATION = "COMMUNICATION"
    PRACTICE_BASED_LEARNING = "PRACTICE_BASED_LEARNING"
    SYSTEMS_BASED_PRACTICE = "SYSTEMS_BASED_PRACTICE"


class CCCStatus(str, Enum):
    OPEN = "OPEN"
    IN_DELIBERATION = "IN_DELIBERATION"
    FINALIZED = "FINALIZED"


class CCCOutcome(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    UNSATISFACTORY = "UNSATISFACTORY"


class ProcedureCategory(str, Enum):
    MAJOR_SURGERY = "MAJOR_SURGERY"
    ENDOSCOPY = "ENDOSCOPY"
    TRAUMA_CARE = "TRAUMA_CARE"
    DELIVERIES = "DELIVERIES"
    AMBULATORY_PROCEDURE = "AMBULATORY_PROCEDURE"


class CaseRole(str, Enum):
    SURGEON = "SURGEON"
    ASSIST = "ASSIST"


class CaseLogStatus(str, Enum):
    LOGGED = "LOGGED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class RemediationTrigger(str, Enum):
    MANUAL = "MANUAL"
    CCC_OUTCOME = "CCC_OUTCOME"
    DUTY_HOUR_VIOLATIONS = "DUTY_HOUR_VIOLATIONS"


class RemediationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED_SUCCESS = "COMPLETED_SUCCESS"
    COMPLETED_FAILURE = "COMPLETED_FAILURE"
    CANCELLED = "CANCELLED"


class RemediationOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class ProbationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    DISMISSAL_RECOMMENDED = "DISMISSAL_RECOMMENDED"
    DISMISSED = "DISMISSED"


class CitationSeverity(str, Enum):
    WARNING = "WARNING"
    SERIOUS = "SERIOUS"


class CitationArea(str, Enum):
    DUTY_HOURS = "DUTY_HOURS"
    EVALUATION = "EVALUATION"
    CASE_LOGS = "CASE_LOGS"
    SUPERVISION = "SUPERVISION"
    RESPONSE_RATE = "RESPONSE_RATE"
    OTHER = "OTHER"


class CitationStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_DRAFTED = "RESPONSE_DRAFTED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class SurveyStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# --- Entity TypedDicts -------------------------------------------------------
# Every primary resource carries id / created_at / updated_at / version (PRD
# §2.5); the milestone evaluation is the documented exception (id + created_at
# only — immutable once submitted).

class ResidencyProgram(TypedDict):
    id: str
    name: str
    specialty: str
    acgme_program_code: str
    accreditation_status: str
    created_at: str
    updated_at: str
    version: int


class AcademicYear(TypedDict):
    id: str
    program_id: str
    year_label: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScheduleBlock(TypedDict):
    id: str
    academic_year_id: str
    block_index: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplementApproval(TypedDict):
    id: str
    program_id: str
    academic_year_id: str
    pgy_level: int
    approved_positions: int
    annual_funding_budget_cents: int
    blended_stipend_cents: int
    resident_year_stipend_cents: int
    effective_funded_positions: int
    filled_headcount: int
    filled_funded_census: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    program_id: str
    entry_academic_year_id: str
    pgy_level: int
    full_name: str
    email: str
    hire_date: str
    expected_graduation_date: str
    lifecycle_status: str
    standing_status: str
    created_at: str
    updated_at: str
    version: int


class Rotation(TypedDict):
    id: str
    program_id: str
    name: str
    min_pgy_level: int
    max_residents_per_block: int
    is_night_float: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RotationAssignment(TypedDict):
    id: str
    resident_id: str
    schedule_block_id: str
    rotation_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DutyHourLog(TypedDict):
    id: str
    resident_id: str
    started_at: str
    ended_at: str
    duration_hours: float
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DutyHourViolation(TypedDict):
    id: str
    resident_id: str
    duty_hour_log_id: str
    rule_code: str
    window_start: str
    window_end: str
    measured_value: float
    threshold_value: float
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoonlightingRequest(TypedDict):
    id: str
    resident_id: str
    type: str
    site_name: str
    start_date: str
    end_date: str
    hours_per_week: float
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MilestoneEvaluation(TypedDict):
    """Append-only (PRD §2.5): id + created_at only — NO updated_at, NO version."""
    id: str
    resident_id: str
    academic_year_id: str
    reporting_period: str
    evaluator_id: str
    evaluator_role: str
    competency_ratings: List[dict]
    created_at: str


class CCCReview(TypedDict):
    id: str
    resident_id: str
    academic_year_id: str
    reporting_period: str
    status: str
    outcome: Optional[str]
    milestone_levels: Optional[List[dict]]
    composite_snapshot: Optional[dict]
    created_at: str
    updated_at: str
    version: int


class ProcedureCaseLog(TypedDict):
    id: str
    resident_id: str
    rotation_id: str
    procedure_category: str
    performed_date: str
    role: str
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseRequirement(TypedDict):
    id: str
    program_id: str
    procedure_category: str
    required_count: int
    required_primary_count: int
    created_at: str
    updated_at: str
    version: int


class RemediationPlan(TypedDict):
    id: str
    resident_id: str
    ccc_review_id: Optional[str]
    trigger_source: str
    goals: str
    start_date: str
    end_date: str
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProbationCase(TypedDict):
    id: str
    resident_id: str
    remediation_plan_id: Optional[str]
    reason: str
    status: str
    recommended_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccreditationCitation(TypedDict):
    id: str
    program_id: str
    annual_survey_id: Optional[str]
    citation_code: str
    area_code: str
    severity: str
    received_date: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualSurvey(TypedDict):
    id: str
    program_id: str
    academic_year_id: str
    status: str
    resident_response_rate: Optional[float]
    faculty_response_rate: Optional[float]
    area_results: Optional[List[dict]]
    flagged_area_count: Optional[int]
    created_at: str
    updated_at: str
    version: int
