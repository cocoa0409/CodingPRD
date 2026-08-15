"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SAFETY_OFFICER = "SafetyOfficer"
    RECORDKEEPING_COORDINATOR = "RecordkeepingCoordinator"
    INVESTIGATING_SUPERVISOR = "InvestigatingSupervisor"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    STANDARD = "STANDARD"
    LARGE = "LARGE"


class EstablishmentPosture(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    ELEVATED = "ELEVATED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SEPARATED = "SEPARATED"


class EventType(str, Enum):
    INJURY = "INJURY"
    SKIN_DISORDER = "SKIN_DISORDER"
    RESPIRATORY = "RESPIRATORY"
    POISONING = "POISONING"
    HEARING_LOSS = "HEARING_LOSS"
    OTHER_ILLNESS = "OTHER_ILLNESS"


class SevereEventKind(str, Enum):
    NONE = "NONE"
    FATALITY = "FATALITY"
    INPATIENT_HOSPITALIZATION = "INPATIENT_HOSPITALIZATION"
    AMPUTATION = "AMPUTATION"
    EYE_LOSS = "EYE_LOSS"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    PENDING_REVIEW = "PENDING_REVIEW"
    RECORDABLE = "RECORDABLE"
    NOT_RECORDABLE = "NOT_RECORDABLE"
    RECLASSIFIED = "RECLASSIFIED"
    FINALIZED = "FINALIZED"


class Classification(str, Enum):
    NONE = "NONE"
    FIRST_AID_ONLY = "FIRST_AID_ONLY"
    MEDICAL_TREATMENT = "MEDICAL_TREATMENT"
    JOB_TRANSFER_RESTRICTION = "JOB_TRANSFER_RESTRICTION"
    DAYS_AWAY = "DAYS_AWAY"
    DEATH = "DEATH"


class DayType(str, Enum):
    DAYS_AWAY = "DAYS_AWAY"
    RESTRICTED = "RESTRICTED"


class DayEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    ROOT_CAUSE_SUBMITTED = "ROOT_CAUSE_SUBMITTED"
    CLOSED = "CLOSED"


class RootCause(str, Enum):
    HUMAN_FACTOR = "HUMAN_FACTOR"
    EQUIPMENT = "EQUIPMENT"
    PROCESS = "PROCESS"
    ENVIRONMENT = "ENVIRONMENT"
    TRAINING = "TRAINING"
    INDETERMINATE = "INDETERMINATE"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    OVERDUE = "OVERDUE"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


class CorrectiveActionPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    IMMINENT_DANGER = "IMMINENT_DANGER"


class SummaryStatus(str, Enum):
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    CERTIFIED = "CERTIFIED"
    POSTED = "POSTED"
    AMENDED = "AMENDED"


class HourLogStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class ReportKind(str, Enum):
    FATALITY = "FATALITY"
    INPATIENT_HOSPITALIZATION = "INPATIENT_HOSPITALIZATION"
    AMPUTATION = "AMPUTATION"
    EYE_LOSS = "EYE_LOSS"


class SevereReportStatus(str, Enum):
    TIMELY = "TIMELY"
    LATE = "LATE"


class InspectionType(str, Enum):
    PROGRAMMED = "PROGRAMMED"
    COMPLAINT = "COMPLAINT"
    REFERRAL = "REFERRAL"
    FATALITY_CATASTROPHE = "FATALITY_CATASTROPHE"
    FOLLOW_UP = "FOLLOW_UP"


class InspectionScope(str, Enum):
    COMPREHENSIVE = "COMPREHENSIVE"
    PARTIAL = "PARTIAL"
    RECORDS_ONLY = "RECORDS_ONLY"


class InspectionStatus(str, Enum):
    OPEN = "OPEN"
    CITATIONS_ISSUED = "CITATIONS_ISSUED"
    CLOSED_NO_CITATION = "CLOSED_NO_CITATION"


class ViolationType(str, Enum):
    OTHER_THAN_SERIOUS = "OTHER_THAN_SERIOUS"
    SERIOUS = "SERIOUS"
    WILLFUL = "WILLFUL"
    REPEAT = "REPEAT"
    FAILURE_TO_ABATE = "FAILURE_TO_ABATE"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    CONTESTED = "CONTESTED"
    FINAL_ORDER = "FINAL_ORDER"
    ABATEMENT_PENDING = "ABATEMENT_PENDING"
    ABATED = "ABATED"
    VACATED = "VACATED"
    OVERDUE = "OVERDUE"


class ContestOutcome(str, Enum):
    AFFIRMED = "AFFIRMED"
    MODIFIED = "MODIFIED"
    VACATED = "VACATED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).
# CaseDayCountEntry is the sole exception: it carries only id + created_at.
# ---------------------------------------------------------------------------


class Company(TypedDict):
    id: str
    legal_name: str
    fein: str
    created_at: str
    updated_at: str
    version: int


class Establishment(TypedDict):
    id: str
    company_id: str
    site_name: str
    naics_code: str
    state_code: str
    size_class: str
    is_partially_exempt: bool
    posture: str
    risk_score: float
    current_year_hours: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    company_id: str
    full_name: str
    job_title: str
    hire_date: str
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class IncidentCase(TypedDict):
    id: str
    establishment_id: str
    employee_id: str
    case_number: str
    occurred_at: str
    reported_at: str
    description: str
    body_part: str
    event_type: str
    is_privacy_case: bool
    is_severe_event: str
    status: str
    classification: str
    is_recordable: bool
    is_dart: bool
    days_away_count: int
    restricted_days_count: int
    projected_days_away_count: int
    projected_restricted_days_count: int
    day_count_closed: bool
    recordability_deadline: str
    log_year: int
    revision_index: int
    created_at: str
    updated_at: str
    version: int


class CaseDayCountEntry(TypedDict):
    # Append-only: only id + created_at; no updated_at, no version (PRD §2.5).
    id: str
    case_id: str
    day_type: str
    start_date: str
    end_date: str
    calendar_days: int
    status: str
    created_at: str


class IncidentInvestigation(TypedDict):
    id: str
    case_id: str
    lead_supervisor_id: str
    opened_at: str
    root_cause: Optional[str]
    contributing_factors: Optional[str]
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict):
    id: str
    establishment_id: str
    case_id: Optional[str]
    citation_id: Optional[str]
    description: str
    assigned_to: str
    due_date: str
    priority: str
    status: str
    completed_at: Optional[str]
    completed_by: Optional[str]
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnnualSummary(TypedDict):
    id: str
    establishment_id: str
    year: int
    status: str
    total_recordable_cases: int
    total_dart_cases: int
    total_days_away: int
    total_restricted_days: int
    annual_avg_employment: int
    total_hours_worked: int
    trir: Optional[float]
    dart_rate: Optional[float]
    prepared_by: Optional[str]
    certified_by: Optional[str]
    certified_at: Optional[str]
    posting_window_open: str
    posting_window_close: str
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EstablishmentHourLog(TypedDict):
    id: str
    establishment_id: str
    year: int
    month: int
    hours_worked: int
    employment_count: int
    status: str
    approved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SevereInjuryReport(TypedDict):
    id: str
    case_id: str
    report_kind: str
    occurred_at: str
    reported_to_agency_at: str
    deadline: str
    within_clock: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    establishment_id: str
    opened_on: str
    inspection_type: str
    scope: str
    status: str
    closed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    inspection_id: str
    standard_cited: str
    violation_type: str
    proposed_penalty_usd: float
    abatement_due_date: str
    status: str
    contested_at: Optional[str]
    contest_deadline: str
    final_penalty_usd: Optional[float]
    abated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
