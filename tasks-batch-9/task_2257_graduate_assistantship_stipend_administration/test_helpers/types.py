"""Domain types for the Graduate Assistantship Stipend Administration API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them.  Every collection in this API carries ``id``, ``created_at``,
``updated_at`` and ``version``, so every TypedDict below lists all four.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    GRAD_SCHOOL_ADMIN = "GradSchoolAdmin"
    DEPARTMENT_ADMIN = "DepartmentAdmin"
    GRANT_ACCOUNTANT = "GrantAccountant"
    FACULTY_SUPERVISOR = "FacultySupervisor"
    STUDENT_USER = "StudentUser"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class AcademicTermStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    PAYROLL_LOCKED = "PAYROLL_LOCKED"
    CLOSED = "CLOSED"


class PayPeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class FundingSourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AppointmentLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    FUNDING_VERIFIED = "FUNDING_VERIFIED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    NON_RENEWAL_PENDING = "NON_RENEWAL_PENDING"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"
    CANCELLED = "CANCELLED"


class AppointmentPayrollStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    PARTIALLY_DISBURSED = "PARTIALLY_DISBURSED"
    FULLY_DISBURSED = "FULLY_DISBURSED"
    PAY_SUSPENDED = "PAY_SUSPENDED"
    PAY_VOIDED = "PAY_VOIDED"


class FundingAllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    EXPENDED = "EXPENDED"


class StipendDisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    VOIDED = "VOIDED"
    REVERSED = "REVERSED"


class RenewalDecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SAP_CERTIFIED = "SAP_CERTIFIED"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class TaxAssessmentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    AMENDED = "AMENDED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------- #
# Value enums
# --------------------------------------------------------------------------- #
class SessionType(str, Enum):
    IN_SESSION = "IN_SESSION"
    BREAK = "BREAK"


class ProrationMethod(str, Enum):
    CALENDAR_DAY = "CALENDAR_DAY"
    WORKDAY = "WORKDAY"


class AssistantshipType(str, Enum):
    TEACHING = "TEACHING"
    RESEARCH = "RESEARCH"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class DegreeLevel(str, Enum):
    MASTERS = "MASTERS"
    DOCTORAL = "DOCTORAL"


class VisaType(str, Enum):
    F1 = "F1"
    J1 = "J1"
    NONE = "NONE"


class SapStatus(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    PROBATION = "PROBATION"
    UNSATISFACTORY = "UNSATISFACTORY"


class SourceType(str, Enum):
    GRANT = "GRANT"
    DEPARTMENTAL_BUDGET = "DEPARTMENTAL_BUDGET"
    FELLOWSHIP = "FELLOWSHIP"


class SuspensionReason(str, Enum):
    SPONSOR_HOLD = "SPONSOR_HOLD"
    OVERCOMMITMENT = "OVERCOMMITMENT"
    AUDIT = "AUDIT"


class AllocationReleaseReason(str, Enum):
    PLAN_SUPERSEDED = "PLAN_SUPERSEDED"
    APPOINTMENT_RETURNED = "APPOINTMENT_RETURNED"
    APPOINTMENT_TERMINATED = "APPOINTMENT_TERMINATED"
    PREDECESSOR_NON_RENEWED = "PREDECESSOR_NON_RENEWED"


class RenewalOutcome(str, Enum):
    PENDING = "PENDING"
    RENEW = "RENEW"
    NON_RENEW = "NON_RENEW"


class TaxVariant(str, Enum):
    TERM_PROVISIONAL = "TERM_PROVISIONAL"
    CALENDAR_YEAR_FINAL = "CALENDAR_YEAR_FINAL"


# --------------------------------------------------------------------------- #
# Entity TypedDicts
# --------------------------------------------------------------------------- #
class AcademicTerm(TypedDict):
    id: str
    term_code: str
    term_start: str
    term_end: str
    tax_calendar_year: int
    session_type: str
    proration_method: str
    remission_drop_deadline: str
    status: str
    pay_period_count: int
    locked_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict):
    id: str
    code: str
    name: str
    non_renewal_notice_days: int
    created_at: str
    updated_at: str
    version: int


class StipendPolicy(TypedDict):
    id: str
    term_id: str
    assistantship_type: str
    degree_level: str
    min_fte_monthly_stipend_cents: int
    per_credit_tuition_cents: int
    max_remission_cents_per_term: int
    term_insurance_premium_cents: int
    insurance_min_effort_pct: int
    min_insurance_duration_days: int
    tuition_tax_exempt_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class PayPeriod(TypedDict):
    id: str
    term_id: str
    sequence_no: int
    period_start: str
    period_end_exclusive: str
    pay_date: str
    calendar_day_count: int
    workday_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GraduateStudent(TypedDict):
    id: str
    student_number: str
    full_name: str
    degree_level: str
    is_international: bool
    cumulative_gpa: float
    visa_type: str
    enrolled_credit_hours: int
    external_weekly_hours: float
    sap_status: str
    effort_cap_pct: int
    cap_override_by_user_id: Optional[str]
    cap_override_justification: Optional[str]
    total_effort_pct: int
    assigned_hours_per_week: float
    tuition_benefit_ytd_cents: int
    taxable_tuition_benefit_ytd_cents: int
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict):
    id: str
    department_id: str
    source_code: str
    source_type: str
    authorized_amount_cents: int
    budget_period_start: str
    budget_period_end: str
    allows_tuition_remission: bool
    sponsor_code: Optional[str]
    grant_effort_cap_pct: int
    auto_reinstate_threshold_cents: int
    status: str
    committed_amount_cents: int
    expended_amount_cents: int
    available_amount_cents: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    student_id: str
    department_id: str
    term_id: str
    assistantship_type: str
    effort_pct: int
    start_date: str
    end_date: str
    monthly_stipend_cents: int
    supervisor_user_id: str
    renewed_from_appointment_id: Optional[str]
    weekly_hours: float
    duration_days: int
    insurance_eligible: bool
    tuition_remission_pct: int
    lifecycle_status: str
    payroll_status: str
    renewal_eligible: bool
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    return_reason: Optional[str]
    pay_suspension_reason: Optional[str]
    termination_reason: Optional[str]
    termination_date: Optional[str]
    projected_pay_period_count: int
    total_stipend_cents: int
    tuition_remission_cents: int
    insurance_subsidy_cents: int
    employee_premium_cents: int
    net_term_stipend_cents: int
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict):
    id: str
    appointment_id: str
    funding_source_id: str
    share_pct: float
    is_cost_share: bool
    plan_sequence: int
    status: str
    allocated_stipend_cents: int
    allocated_remission_cents: int
    disbursed_amount_cents: int
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationSplitElement(TypedDict):
    funding_allocation_id: str
    plan_sequence: int
    amount_cents: int


class StipendDisbursement(TypedDict):
    id: str
    appointment_id: str
    pay_period_id: str
    proration_method_applied: str
    covered_units: int
    period_units: int
    gross_amount_cents: int
    allocation_split: List[AllocationSplitElement]
    status: str
    paid_at: Optional[str]
    voided_at: Optional[str]
    reversed_at: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalDecision(TypedDict):
    id: str
    appointment_id: str
    renewal_window_open_date: str
    notice_deadline_date: str
    status: str
    decision: str
    sap_certified: bool
    revision_count: int
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    issued_by_user_id: Optional[str]
    notice_sent_date: Optional[str]
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxAssessment(TypedDict):
    id: str
    student_id: str
    term_id: str
    tax_calendar_year: int
    status: str
    variant_applied: str
    benefit_cents: int
    exempt_cents: int
    taxable_cents: int
    imputed_withholding_cents: int
    remaining_cap_cents: int
    amendment_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
