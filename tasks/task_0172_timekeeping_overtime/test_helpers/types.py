"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: every common-fields resource carries id, created_at, updated_at,
and version. The following entities are append-only / leaf records that
carry ONLY id + created_at (no updated_at, no version):
    - Punch
    - MealBreak
    - DetentionEvent
    - AuditEntry
Their TypedDicts omit updated_at and version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    EMPLOYEE = "Employee"
    SUPERVISOR = "Supervisor"
    PAYROLL_ADMIN = "PayrollAdmin"


# ===========================================================================
# Status / enum types — PRD §3
# ===========================================================================
class Jurisdiction(str, Enum):
    CA = "CA"
    FED = "FED"


class Classification(str, Enum):
    EXEMPT = "EXEMPT"
    NON_EXEMPT = "NON_EXEMPT"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ShiftState(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class PunchType(str, Enum):
    IN = "IN"
    OUT = "OUT"
    MEAL_OUT = "MEAL_OUT"
    MEAL_IN = "MEAL_IN"


class PunchSource(str, Enum):
    TIMECLOCK = "TIMECLOCK"
    EDIT = "EDIT"


class TimeEditState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERTED = "REVERTED"


class TimeEditReasonCode(str, Enum):
    CLERICAL = "CLERICAL"
    MISSED_PUNCH = "MISSED_PUNCH"
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"
    FRAUD_CORRECTION = "FRAUD_CORRECTION"


class DetentionTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class WorkweekPayrollStatus(str, Enum):
    OPEN = "OPEN"
    POSTED = "POSTED"
    LOCKED = "LOCKED"


class AuditAction(str, Enum):
    TIME_EDIT_SUBMITTED = "TIME_EDIT_SUBMITTED"
    TIME_EDIT_APPROVED = "TIME_EDIT_APPROVED"
    TIME_EDIT_REJECTED = "TIME_EDIT_REJECTED"
    TIME_EDIT_REVERTED = "TIME_EDIT_REVERTED"
    SHIFT_FINALIZED = "SHIFT_FINALIZED"
    WORKWEEK_LOCKED = "WORKWEEK_LOCKED"


class AuditSubjectEntity(str, Enum):
    SHIFT = "Shift"
    TIME_EDIT = "TimeEdit"
    WORKWEEK = "Workweek"


# ===========================================================================
# Entity TypedDicts — PRD §2.4
# ===========================================================================
# common_fields: true — id + created_at + updated_at + version
class Employee(TypedDict, total=False):
    id: str
    full_name: str
    jurisdiction: str
    classification: str
    base_hourly_rate_cents: int
    tipped_role: bool
    tipped_cash_rate_cents: Optional[int]
    applicable_minimum_wage_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    employee_id: str
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    state: str
    workweek_id: Optional[str]
    requires_meal_break: bool
    meal_break_premium_owed_cents: int
    detention_minutes: int
    created_at: str
    updated_at: str
    version: int


class TimeEdit(TypedDict, total=False):
    id: str
    shift_id: str
    target_punch_id: str
    proposed_punched_at: str
    reason_code: str
    requested_by_user_id: str
    requested_by_role: str
    approved_by_user_id: Optional[str]
    state: str
    idempotency_key: str
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TipDeclaration(TypedDict, total=False):
    id: str
    shift_id: str
    declared_tips_cents: int
    tip_credit_applied_cents: int
    shortfall_topup_cents: int
    created_at: str
    updated_at: str
    version: int


class Workweek(TypedDict, total=False):
    id: str
    employee_id: str
    week_start: str
    total_hours: float
    regular_hours: float
    overtime_hours: float
    double_time_hours: float
    gross_pay_cents: int
    payroll_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — id + created_at only
class Punch(TypedDict, total=False):
    id: str
    shift_id: str
    employee_id: str
    punch_type: str
    punched_at: str
    source: str
    superseded_by_edit_id: Optional[str]
    created_at: str


class MealBreak(TypedDict, total=False):
    id: str
    shift_id: str
    meal_out_punch_id: str
    meal_in_punch_id: str
    duration_minutes: int
    taken_before_fifth_hour: bool
    created_at: str


class DetentionEvent(TypedDict, total=False):
    id: str
    shift_id: str
    minutes_past_scheduled_end: int
    premium_owed_cents: int
    tier: str
    created_at: str


class AuditEntry(TypedDict, total=False):
    id: str
    actor_user_id: str
    actor_role: str
    action: str
    subject_entity: str
    subject_id: str
    before_snapshot: dict
    after_snapshot: dict
    created_at: str


__all__ = [
    "UserRole",
    "Jurisdiction",
    "Classification",
    "EmployeeStatus",
    "ShiftState",
    "PunchType",
    "PunchSource",
    "TimeEditState",
    "TimeEditReasonCode",
    "DetentionTier",
    "WorkweekPayrollStatus",
    "AuditAction",
    "AuditSubjectEntity",
    "Employee",
    "Shift",
    "TimeEdit",
    "TipDeclaration",
    "Workweek",
    "Punch",
    "MealBreak",
    "DetentionEvent",
    "AuditEntry",
]
