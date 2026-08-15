"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class PayFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    SEMIMONTHLY = "SEMIMONTHLY"
    MONTHLY = "MONTHLY"


class EmployerStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    ATTENTION = "ATTENTION"
    RESTRICTED = "RESTRICTED"


class RegistrationAgency(str, Enum):
    SIT_WITHHOLDING = "SIT_WITHHOLDING"
    SUTA = "SUTA"
    NEW_HIRE_DIRECTORY = "NEW_HIRE_DIRECTORY"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"


class WorkerStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    CLASSIFIED = "CLASSIFIED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class Classification(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    EMPLOYEE = "EMPLOYEE"
    CONTRACTOR = "CONTRACTOR"


class WorkArrangement(str, Enum):
    LIVE_IN = "LIVE_IN"
    LIVE_OUT = "LIVE_OUT"


class PayMethod(str, Enum):
    HOURLY = "HOURLY"
    GUARANTEED_SALARY_FWW = "GUARANTEED_SALARY_FWW"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class TimesheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class PayRunStatus(str, Enum):
    OPEN = "OPEN"
    CALCULATED = "CALCULATED"
    FINALIZED = "FINALIZED"


class RecalcStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"


class PaycheckStatus(str, Enum):
    CALCULATED = "CALCULATED"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class PaycheckBasis(str, Enum):
    GUARANTEE_FALLBACK = "GUARANTEE_FALLBACK"
    TIMESHEET = "TIMESHEET"


class DepositStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    REVERSAL_PENDING = "REVERSAL_PENDING"


class StubStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    NOT_REQUIRED = "NOT_REQUIRED"


class LeaveStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class TaxType(str, Enum):
    FICA_EE = "FICA_EE"
    FICA_ER = "FICA_ER"
    FUTA_ER = "FUTA_ER"
    SIT_EE = "SIT_EE"
    SUTA_ER = "SUTA_ER"


class FilingStatus(str, Enum):
    OPEN = "OPEN"
    PREPARED = "PREPARED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    EXPIRED = "EXPIRED"


class YearEndStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class UserRole(str, Enum):
    PAYROLL_ADMIN = "PayrollAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    HOUSEHOLD_CLIENT = "HouseholdClient"
    WORKER = "Worker"


class HouseholdEmployer(TypedDict, total=False):
    id: str
    legal_name: str
    primary_state_code: str
    fein: str
    pay_frequency: str
    prior_year_schedule_h_cents: int
    status: str
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class StateRulePack(TypedDict, total=False):
    # Immutable configuration entity: carries id + created_at only.
    id: str
    created_at: str
    state_code: str
    min_pay_frequency: str
    weekly_ot_threshold_minutes: int
    daily_ot_threshold_minutes: int
    daily_dt_threshold_minutes: int
    live_in_weekly_ot_eligible: bool
    live_in_daily_ot_eligible: bool
    min_wage_cents: int
    sit_rate: float
    suta_rate: float
    suta_wage_base_cents: int
    workers_comp_required: bool
    new_hire_report_days: int
    pay_stub_required: bool


class StateRegistration(TypedDict, total=False):
    id: str
    employer_id: str
    state_code: str
    agency: str
    agency_account_number: Optional[str]
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DomesticWorker(TypedDict, total=False):
    id: str
    employer_id: str
    full_name: str
    ssn: Optional[str]
    work_state_code: str
    hire_date: str
    work_arrangement: str
    classification: str
    classification_answers: List[dict]
    status: str
    new_hire_report_date: Optional[str]
    termination_date: Optional[str]
    cash_wages_ytd_cents: int
    fica_covered: bool
    ss_wages_paid_ytd_cents: int
    futa_wages_ytd_cents: int
    ytd_approved_minutes: int
    accrued_leave_minutes: int
    used_leave_minutes: int
    available_leave_minutes: int
    created_at: str
    updated_at: str
    version: int


class EmploymentAgreement(TypedDict, total=False):
    id: str
    worker_id: str
    hourly_rate_cents: int
    pay_method: str
    guaranteed_minutes_per_week: int
    fit_withholding_cents_per_period: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Timesheet(TypedDict, total=False):
    id: str
    worker_id: str
    pay_run_id: Optional[str]
    period_start: str
    period_end: str
    entries: List[dict]
    total_worked_minutes: int
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayRun(TypedDict, total=False):
    id: str
    employer_id: str
    period_start: str
    period_end: str
    pay_date: str
    status: str
    recalc_status: str
    total_gross_cents: int
    total_net_cents: int
    total_employer_tax_cents: int
    created_at: str
    updated_at: str
    version: int


class Paycheck(TypedDict, total=False):
    id: str
    pay_run_id: str
    worker_id: str
    basis: str
    basis_stale: bool
    pay_method: str
    regular_minutes: int
    overtime_minutes: int
    double_minutes: int
    guarantee_top_up_minutes: int
    fww_effective_rate_cents_per_minute: Optional[float]
    provisional_gross_cents: int
    gross_cents: int
    withholding_lines: List[dict]
    employer_tax_lines: List[dict]
    net_pay_cents: int
    status: str
    deposit_status: str
    stub_status: str
    created_at: str
    updated_at: str
    version: int


class LeaveRequest(TypedDict, total=False):
    id: str
    worker_id: str
    start_date: str
    end_date: str
    requested_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxLiabilityAccount(TypedDict, total=False):
    id: str
    employer_id: str
    tax_year: int
    tax_type: str
    accrued_cents: int
    projected_annual_cents: int
    deposited_cents: int
    penalty_cents: int
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class TaxDeposit(TypedDict, total=False):
    # Append-only record: carries id + created_at only.
    id: str
    created_at: str
    employer_id: str
    tax_year: int
    quarter: int
    amount_cents: int
    remitted_on: str
    required_amount_cents: int
    due_date: str
    late_days: int
    penalty_cents: int
    unapplied_cents: int


class QuarterlyFiling(TypedDict, total=False):
    id: str
    employer_id: str
    tax_year: int
    quarter: int
    status: str
    total_cash_wages_cents: int
    futa_applies: bool
    futa_due_cents: int
    suta_due_cents: int
    estimated_federal_payment_cents: int
    prepared_by_user_id: Optional[str]
    prepared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkersCompPolicy(TypedDict, total=False):
    id: str
    employer_id: str
    state_code: str
    policy_number: str
    coverage_start: str
    coverage_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class YearEndPackage(TypedDict, total=False):
    id: str
    employer_id: str
    tax_year: int
    status: str
    schedule_h_total_cents: int
    w2_lines: List[dict]
    underpayment_penalty_applies: bool
    created_at: str
    updated_at: str
    version: int
