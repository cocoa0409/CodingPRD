"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this API carries the common system-managed fields id,
created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SURVEY_ADMIN = "SurveyAdmin"
    FIELD_SUPERVISOR = "FieldSupervisor"
    ENUMERATOR = "Enumerator"
    QC_REVIEWER = "QCReviewer"


class SurveyProjectStatus(str, Enum):
    PLANNING = "PLANNING"
    IN_FIELD = "IN_FIELD"
    CLOSED = "CLOSED"


class AssignmentAreaStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_FIELD = "IN_FIELD"
    FROZEN = "FROZEN"
    COMPLETE = "COMPLETE"


class EnumeratorStatus(str, Enum):
    APPLICANT = "APPLICANT"
    HIRED = "HIRED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CaseStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    REFUSED = "REFUSED"
    VACANT = "VACANT"
    MAX_ATTEMPTS = "MAX_ATTEMPTS"


class CaseAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RELEASED = "RELEASED"


class AttemptStatus(str, Enum):
    LOGGED = "LOGGED"
    CANCELLED = "CANCELLED"


class AttemptMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    PHONE = "PHONE"


class AttemptDisposition(str, Enum):
    NO_ONE_HOME = "NO_ONE_HOME"
    REFUSED = "REFUSED"
    VACANT = "VACANT"
    LANGUAGE_BARRIER = "LANGUAGE_BARRIER"
    CONTACT_MADE = "CONTACT_MADE"
    APPOINTMENT_SET = "APPOINTMENT_SET"


class ResponseStatus(str, Enum):
    CAPTURED = "CAPTURED"
    ACCEPTED = "ACCEPTED"
    INVALIDATED = "INVALIDATED"


class ReinterviewStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISCREPANT = "DISCREPANT"
    FRAUD = "FRAUD"


class ReinterviewReason(str, Enum):
    RANDOM_SAMPLE = "RANDOM_SAMPLE"
    HIGH_FRAUD_SCORE = "HIGH_FRAUD_SCORE"
    MANUAL = "MANUAL"


class ReinterviewOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    DISCREPANT = "DISCREPANT"
    FRAUD = "FRAUD"


class PayPeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    PAID = "PAID"


class PayLineType(str, Enum):
    STIPEND = "STIPEND"
    MILEAGE = "MILEAGE"
    BONUS = "BONUS"


class PayLineStatus(str, Enum):
    ACCRUED = "ACCRUED"
    REVERSED = "REVERSED"


# --- Entity TypedDicts (all entities carry id/created_at/updated_at/version) ---

class SurveyProject(TypedDict):
    id: str
    name: str
    region_code: str
    default_language: str
    supported_languages: List[str]
    fraud_score_threshold: int
    max_attempts: int
    mileage_rate_cents_per_mile: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AssignmentArea(TypedDict):
    id: str
    survey_project_id: str
    area_code: str
    budget_cents: int
    budget_committed_cents: int
    budget_remaining_cents: int
    total_case_count: int
    pending_case_count: int
    in_progress_case_count: int
    complete_case_count: int
    refused_case_count: int
    vacant_case_count: int
    max_attempts_case_count: int
    projected_coverage_rate: float
    final_coverage_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Enumerator(TypedDict):
    id: str
    survey_project_id: str
    full_name: str
    languages: List[str]
    hourly_rate_cents: int
    gross_pay_cents: int
    reversed_pay_cents: int
    net_pay_cents: int
    fraud_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    assignment_area_id: str
    address: str
    respondent_language: str
    assigned_enumerator_id: Optional[str]
    attempt_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CaseAssignment(TypedDict):
    id: str
    case_id: str
    enumerator_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Attempt(TypedDict):
    id: str
    case_id: str
    acting_enumerator_id: str
    mode: str
    window_start: str
    window_end: str
    disposition: str
    mileage_miles: float
    pay_committed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Response(TypedDict):
    id: str
    case_id: str
    capturing_enumerator_id: str
    mode: str
    language_used: str
    duration_minutes: int
    flagged_answer_count: int
    gps_variance_meters: float
    fraud_score: int
    needs_reinterview: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReinterviewCase(TypedDict):
    id: str
    response_id: str
    reviewer_enumerator_id: str
    reason: str
    finding_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PayPeriod(TypedDict):
    id: str
    survey_project_id: str
    label: str
    overtime_threshold_cents: int
    provisional_total_cents: int
    final_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayLine(TypedDict):
    id: str
    enumerator_id: str
    pay_period_id: str
    line_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
