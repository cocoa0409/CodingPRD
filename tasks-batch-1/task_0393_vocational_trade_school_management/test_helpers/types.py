"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system are mutable aggregates that carry id, created_at,
updated_at, and version (see PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    REGISTRAR = "Registrar"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    ACADEMIC_ADVISOR = "AcademicAdvisor"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CohortStatus(str, Enum):
    FORMING = "FORMING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class CredentialType(str, Enum):
    DIPLOMA = "DIPLOMA"
    CERTIFICATE = "CERTIFICATE"
    ASSOCIATE = "ASSOCIATE"


class AgreementStatus(str, Enum):
    DRAFTED = "DRAFTED"
    ENROLLED = "ENROLLED"
    LEAVE_OF_ABSENCE = "LEAVE_OF_ABSENCE"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class SapStandingValue(str, Enum):
    GOOD = "GOOD"
    WARNING = "WARNING"
    PROBATION = "PROBATION"
    DISMISSED = "DISMISSED"


class AppealStatus(str, Enum):
    NONE = "NONE"
    APPEALED = "APPEALED"
    APPEAL_GRANTED = "APPEAL_GRANTED"
    APPEAL_DENIED = "APPEAL_DENIED"


class AttendanceKind(str, Enum):
    THEORY = "THEORY"
    EXTERNSHIP = "EXTERNSHIP"


class AttendanceStatus(str, Enum):
    POSTED = "POSTED"
    EXCUSED = "EXCUSED"
    VOIDED = "VOIDED"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class RefundMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    STATE_TABLE = "STATE_TABLE"


class RefundStatus(str, Enum):
    COMPUTED = "COMPUTED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ExternshipSiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AssignmentStatus(str, Enum):
    PLACED = "PLACED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class ExamResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class OutcomeType(str, Enum):
    EMPLOYED_IN_FIELD = "EMPLOYED_IN_FIELD"
    EMPLOYED_RELATED = "EMPLOYED_RELATED"
    CONTINUING_EDUCATION = "CONTINUING_EDUCATION"
    NOT_PLACED = "NOT_PLACED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all common_fields: true → id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Program(TypedDict):
    id: str
    name: str
    credential_type: str
    required_clock_hours: int
    required_theory_hours: int
    required_externship_hours: int
    tuition_cents: int
    sap_warning_min_pace_pct: float
    sap_probation_min_pace_pct: float
    licensure_min_attendance_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict):
    id: str
    program_id: str
    code: str
    start_term_index: int
    end_term_index: int
    seat_capacity: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    email: str
    hs_diploma_verified: bool
    created_at: str
    updated_at: str
    version: int


class ExternshipSite(TypedDict):
    id: str
    name: str
    daily_slot_capacity: int
    active_assignment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EnrollmentAgreement(TypedDict):
    id: str
    student_id: str
    cohort_id: str
    program_id: str
    contract_tuition_cents: int
    scheduled_aid_cents: int
    cancellation_window_term_index: int
    theory_hours_completed: float
    externship_hours_completed: float
    clock_hours_completed: float
    scheduled_hours_to_date: float
    attendance_pct: float
    completion_pct: float
    disbursed_aid_cents: int
    ledger_balance_cents: int
    sap_standing: str
    licensure_eligible: bool
    status: str
    withdrawal_term_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AttendanceEntry(TypedDict):
    id: str
    agreement_id: str
    term_index: int
    kind: str
    scheduled_hours: float
    attended_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SapStanding(TypedDict):
    id: str
    agreement_id: str
    checkpoint_term_index: int
    measured_pace_pct: float
    measured_attendance_pct: float
    standing: str
    appeal_status: str
    created_at: str
    updated_at: str
    version: int


class AidDisbursement(TypedDict):
    id: str
    agreement_id: str
    disbursement_index: int
    planned_amount_cents: int
    required_clock_hours_gate: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundCase(TypedDict):
    id: str
    agreement_id: str
    method: str
    withdrawal_term_index: int
    tuition_earned_cents: int
    tuition_refund_cents: int
    aid_return_cents: int
    student_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExternshipAssignment(TypedDict):
    id: str
    agreement_id: str
    site_id: str
    start_term_index: int
    end_term_index: int
    planned_hours: float
    verified_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LicensureExamAttempt(TypedDict):
    id: str
    agreement_id: str
    attempt_index: int
    scaled_score: int
    passing_score: int
    result: str
    created_at: str
    updated_at: str
    version: int


class PlacementOutcome(TypedDict):
    id: str
    agreement_id: str
    outcome_term_index: int
    outcome_type: str
    employer_name: Optional[str]
    counts_as_placed: bool
    created_at: str
    updated_at: str
    version: int


class SystemClock(TypedDict):
    id: str
    current_term_index: int
    created_at: str
    updated_at: str
    version: int
