"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the common system-managed properties
(id, created_at, updated_at, version) per PRD section "Common Resource
Properties".
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD: exactly four roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SCHEDULING_OFFICER = "SchedulingOfficer"
    OPERATOR = "Operator"
    PAYROLL_CLERK = "PayrollClerk"
    UNION_REP = "UnionRep"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class SignUpPeriodStatus(str, Enum):
    DRAFT = "DRAFT"
    RUNS_CUT = "RUNS_CUT"
    OPEN = "OPEN"
    PICKING = "PICKING"
    LOCKED = "LOCKED"
    IMPLEMENTED = "IMPLEMENTED"
    CANCELLED = "CANCELLED"


class RunStatus(str, Enum):
    CUT = "CUT"
    VALIDATED = "VALIDATED"
    POSTED = "POSTED"
    AWARDED = "AWARDED"
    EXTRA_BOARD_HELD = "EXTRA_BOARD_HELD"
    WITHDRAWN = "WITHDRAWN"


class OperatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXTRA_BOARD = "EXTRA_BOARD"
    RETIRED = "RETIRED"


class BidEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    PASSED = "PASSED"
    WITHDRAWN = "WITHDRAWN"


class ExtraBoardSlotStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    EXHAUSTED = "EXHAUSTED"


class DailyAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WORKED = "WORKED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PayStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"


class AssignmentSource(str, Enum):
    BID_AWARD = "BID_AWARD"
    EXTRA_BOARD_FILL = "EXTRA_BOARD_FILL"
    OVERTIME_OFFER = "OVERTIME_OFFER"


class AbsenceCaseStatus(str, Enum):
    REPORTED = "REPORTED"
    COVERED = "COVERED"
    UNCOVERED = "UNCOVERED"
    CLOSED = "CLOSED"


class AbsenceReasonCode(str, Enum):
    SICK = "SICK"
    PERSONAL = "PERSONAL"
    VACATION = "VACATION"
    UNEXCUSED = "UNEXCUSED"


class PayRecordVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class VacationSlotStatus(str, Enum):
    OPEN = "OPEN"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"
    CLOSED = "CLOSED"


class GrievanceCategory(str, Enum):
    OT_EQUALIZATION = "OT_EQUALIZATION"
    SENIORITY_BYPASS = "SENIORITY_BYPASS"
    WORK_RULE_SPREAD = "WORK_RULE_SPREAD"
    PAY_VALIDATION = "PAY_VALIDATION"


class GrievanceCaseStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
class RunPiece(TypedDict):
    report_minutes: int
    release_minutes: int
    platform_minutes: int


class SignUpPeriod(TypedDict):
    id: str
    name: str
    effective_start_date: str
    effective_end_date: str
    spread_limit_minutes: int
    paid_break_minutes: int
    daily_ot_threshold_minutes: int
    weekly_ot_threshold_minutes: int
    extra_board_ratio_pct: int
    schedule_revision: int
    status: str
    picked_through_rank: int
    created_at: str
    updated_at: str
    version: int


class Run(TypedDict):
    id: str
    sign_up_period_id: str
    schedule_revision: int
    run_number: str
    service_date: str
    pieces: List[RunPiece]
    spread_minutes: int
    platform_minutes: int
    paid_minutes: int
    status: str
    awarded_operator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict):
    id: str
    employee_number: str
    full_name: str
    hire_date: str
    seniority_rank: int
    status: str
    board_position: Optional[int]
    weekly_ot_minutes_accum: int
    vacation_hours_balance: int
    created_at: str
    updated_at: str
    version: int


class BidEntry(TypedDict):
    id: str
    sign_up_period_id: str
    operator_id: str
    run_id: str
    preference_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExtraBoardSlot(TypedDict):
    id: str
    sign_up_period_id: str
    operator_id: Optional[str]
    slot_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyAssignment(TypedDict):
    id: str
    sign_up_period_id: str
    operator_id: str
    run_id: Optional[str]
    service_date: str
    source: str
    scheduled_minutes: int
    actual_platform_minutes: Optional[int]
    status: str
    pay_status: str
    created_at: str
    updated_at: str
    version: int


class AbsenceCase(TypedDict):
    id: str
    operator_id: str
    absence_date: str
    reason_code: str
    status: str
    covering_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayRecord(TypedDict):
    id: str
    daily_assignment_id: str
    straight_minutes: int
    overtime_minutes: int
    gross_cents: int
    variant: str
    created_at: str
    updated_at: str
    version: int


class VacationSlot(TypedDict):
    id: str
    sign_up_period_id: str
    week_start_date: str
    capacity: int
    allocated_count: int
    operator_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GrievanceCase(TypedDict):
    id: str
    filed_by_operator_id: str
    sign_up_period_id: str
    category: str
    detail: str
    status: str
    remedy_minutes: int
    created_at: str
    updated_at: str
    version: int
