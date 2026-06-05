"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Entities that carry the uniform
system-managed fields (id, created_at, updated_at, version) are modeled with
those four; the append-only TimeEdit audit record carries only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────

class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TimePunchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class TimesheetWeekStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    LOCKED = "LOCKED"


class TipPoolStatus(str, Enum):
    OPEN = "OPEN"
    DISTRIBUTED = "DISTRIBUTED"
    CANCELLED = "CANCELLED"


class PayrollRunStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"


class Classification(str, Enum):
    EXEMPT = "EXEMPT"
    NON_EXEMPT = "NON_EXEMPT"


class BreakKind(str, Enum):
    MEAL = "MEAL"
    REST = "REST"


class EditField(str, Enum):
    CLOCK_IN = "CLOCK_IN"
    CLOCK_OUT = "CLOCK_OUT"


class UserRole(str, Enum):
    PAYROLL_ADMIN = "PayrollAdmin"
    SUPERVISOR = "Supervisor"
    EMPLOYEE = "Employee"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ──

class Employer(TypedDict):
    id: str
    legal_name: str
    workweek_start_dow: str
    federal_min_wage_cents: int
    federal_tipped_cash_wage_cents: int
    created_at: str
    updated_at: str
    version: int


class WageRuleSet(TypedDict):
    id: str
    state_code: str
    employer_id: str
    daily_ot_enabled: bool
    daily_ot_threshold_hours: float
    daily_dt_threshold_hours: float
    weekly_ot_threshold_hours: float
    seventh_day_rule_enabled: bool
    meal_break_premium_enabled: bool
    rest_break_premium_enabled: bool
    state_min_wage_cents: int
    created_at: str
    updated_at: str
    version: int


class Worksite(TypedDict):
    id: str
    employer_id: str
    name: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    employer_id: str
    home_worksite_id: str
    full_name: str
    classification: str
    base_rate_cents: int
    is_tipped: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    employee_id: str
    worksite_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    detention_minutes: int
    detention_flagged: bool
    created_at: str
    updated_at: str
    version: int


class TimePunch(TypedDict):
    id: str
    employee_id: str
    shift_id: str
    clock_in: str
    clock_out: Optional[str]
    status: str
    worked_minutes: int
    workday_date: str
    edited: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit record: id + created_at only.
class TimeEdit(TypedDict):
    id: str
    punch_id: str
    editor_user_id: str
    field: str
    old_value: str
    new_value: str
    reason: str
    created_at: str


class BreakRecord(TypedDict):
    id: str
    shift_id: str
    employee_id: str
    kind: str
    taken: bool
    minutes: int
    premium_owed: bool
    created_at: str
    updated_at: str
    version: int


class TipDeclaration(TypedDict):
    id: str
    employee_id: str
    workday_date: str
    declared_cents: int
    pool_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TipPool(TypedDict):
    id: str
    worksite_id: str
    workday_date: str
    status: str
    pooled_cents: int
    distributed_cents: int
    created_at: str
    updated_at: str
    version: int


class TimesheetWeek(TypedDict):
    id: str
    employee_id: str
    workweek_start: str
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    regular_minutes: int
    ot_minutes: int
    dt_minutes: int
    break_premium_hours: int
    gross_wages_cents: int
    tip_true_up_cents: int
    payroll_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollRun(TypedDict):
    id: str
    employer_id: str
    period_start: str
    period_end: str
    status: str
    total_gross_cents: int
    included_week_count: int
    created_at: str
    updated_at: str
    version: int
