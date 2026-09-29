"""Typed shapes and enumerations for the fire-staffing-overtime API.

Every resource in this API carries the four common properties described by the
PRD: a server-generated ``id``, a ``created_at``, an ``updated_at`` and an
integer ``version`` that starts at 1 and increments on each mutation.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class Role(str, Enum):
    STAFFING_OFFICER = "StaffingOfficer"
    COMPANY_OFFICER = "CompanyOfficer"
    FIREFIGHTER = "Firefighter"
    PAYROLL_ANALYST = "PayrollAnalyst"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class BudgetPosture(str, Enum):
    WITHIN = "WITHIN"
    WATCH = "WATCH"
    OVER = "OVER"


class ApparatusType(str, Enum):
    ENGINE = "ENGINE"
    LADDER = "LADDER"
    RESCUE = "RESCUE"
    MEDIC = "MEDIC"
    HAZMAT = "HAZMAT"


class ApparatusStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class Certification(str, Enum):
    PARAMEDIC = "PARAMEDIC"
    HAZMAT_TECH = "HAZMAT_TECH"
    TECHNICAL_RESCUE = "TECHNICAL_RESCUE"


class SeatCertification(str, Enum):
    NONE = "NONE"
    PARAMEDIC = "PARAMEDIC"
    HAZMAT_TECH = "HAZMAT_TECH"
    TECHNICAL_RESCUE = "TECHNICAL_RESCUE"


class Rank(str, Enum):
    FIREFIGHTER = "FIREFIGHTER"
    ENGINEER = "ENGINEER"
    LIEUTENANT = "LIEUTENANT"
    CAPTAIN = "CAPTAIN"


class Platoon(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INJURY_LEAVE = "INJURY_LEAVE"
    SEPARATED = "SEPARATED"


class RosterStanding(str, Enum):
    AVAILABLE = "AVAILABLE"
    PASSED = "PASSED"
    UNAVAILABLE = "UNAVAILABLE"


class RosterType(str, Enum):
    VOLUNTARY_OT = "VOLUNTARY_OT"
    MANDATORY_HOLDOVER = "MANDATORY_HOLDOVER"
    CALLBACK = "CALLBACK"


class DutyShiftStatus(str, Enum):
    DRAFT = "DRAFT"
    HIRING = "HIRING"
    STAFFED = "STAFFED"
    COMPLETED = "COMPLETED"


class StaffingPosture(str, Enum):
    FULLY_STAFFED = "FULLY_STAFFED"
    SHORT = "SHORT"
    CRITICAL = "CRITICAL"


class AssignmentType(str, Enum):
    REGULAR = "REGULAR"
    KELLY_RELIEF = "KELLY_RELIEF"
    OVERTIME = "OVERTIME"
    HOLDOVER = "HOLDOVER"
    CALLBACK = "CALLBACK"
    TRADE = "TRADE"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WORKED = "WORKED"
    RELIEVED = "RELIEVED"
    CANCELLED = "CANCELLED"


class LeaveType(str, Enum):
    INJURY = "INJURY"
    SICK = "SICK"
    KELLY_DAY = "KELLY_DAY"
    BEREAVEMENT = "BEREAVEMENT"
    VACATION = "VACATION"


class LeaveStatus(str, Enum):
    QUEUED = "QUEUED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class DenialReason(str, Enum):
    STAFFING_FLOOR = "STAFFING_FLOOR"


class TradeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERSIGNED = "COUNTERSIGNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TradeDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RETURN_FOR_REVISION = "RETURN_FOR_REVISION"


class VacancyDriver(str, Enum):
    VACANT_POSITION = "VACANT_POSITION"
    LEAVE = "LEAVE"
    INJURY = "INJURY"


class VacancyStatus(str, Enum):
    OPEN = "OPEN"
    OFFERING = "OFFERING"
    FILLED = "FILLED"
    CLOSED_BY_COMPANY_CLOSURE = "CLOSED_BY_COMPANY_CLOSURE"
    CANCELLED = "CANCELLED"


class HiringMode(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    MANDATORY_HOLDOVER = "MANDATORY_HOLDOVER"
    CALLBACK = "CALLBACK"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"
    MANDATED = "MANDATED"


class OfferResponse(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class WorkPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AdjustmentBasis(str, Enum):
    SCHEDULED = "SCHEDULED"
    WORKED = "WORKED"


class ForecastMethod(str, Enum):
    VACANCY_DRIVEN = "VACANCY_DRIVEN"
    RUN_RATE = "RUN_RATE"


class AcademySignalTier(str, Enum):
    NONE = "NONE"
    MONITOR = "MONITOR"
    RECRUIT = "RECRUIT"
    SURGE = "SURGE"


# ---------------------------------------------------------------------------
# Common resource properties
# ---------------------------------------------------------------------------
class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
class Station(CommonFields):
    name: str
    battalion_code: str
    minimum_staffing_floor: int
    fiscal_ot_budget_cents: int
    fiscal_period_start_date: str
    fiscal_period_end_date: str
    ot_committed_cents: int
    ot_actual_cents: int
    budget_posture: str


class Apparatus(CommonFields):
    station_id: str
    unit_designation: str
    apparatus_type: str
    minimum_crew_size: int
    required_certifications: List[str]
    closure_priority: int
    closure_exempt: bool
    status: str


class Firefighter(CommonFields):
    station_id: str
    acting_supervisor_id: Optional[str]
    full_name: str
    rank: str
    platoon: str
    seniority_rank: int
    kelly_day_cycle_position: int
    certifications: List[str]
    hourly_rate_cents: int
    employment_status: str
    roster_standing: str
    voluntary_ot_hours_charged: int
    mandatory_holdover_count: int
    callback_count: int
    ot_pass_count: int
    pending_offer_count: int


class HiringRoster(CommonFields):
    station_id: str
    roster_type: str
    certification_scope: str
    dispatch_count: int


class DutyShift(CommonFields):
    station_id: str
    shift_date: str
    platoon: str
    status: str
    required_staffing: int
    assigned_headcount: int
    certification_gap_count: int
    staffing_gap: int
    leave_floor_headcount: int
    staffing_posture: str
    closed_apparatus_ids: List[str]
    open_vacancy_count: int
    ops_run_index: int


class ShiftAssignment(CommonFields):
    duty_shift_id: str
    firefighter_id: str
    apparatus_id: str
    source_offer_id: Optional[str]
    relieved_by_leave_request_id: Optional[str]
    assignment_type: str
    seat_certification: str
    scheduled_hours: int
    actual_hours: Optional[int]
    projected_premium_cents: int
    status: str


class LeaveRequest(CommonFields):
    firefighter_id: str
    duty_shift_id: str
    leave_type: str
    requested_hours: int
    status: str
    decision_order_index: Optional[int]
    denial_reason: Optional[str]
    backfill_vacancy_id: Optional[str]


class TradeRequest(CommonFields):
    requesting_firefighter_id: str
    counterparty_firefighter_id: str
    duty_shift_id: str
    traded_assignment_id: Optional[str]
    status: str
    revision_count: int
    decided_by_user_id: Optional[str]


class Vacancy(CommonFields):
    duty_shift_id: str
    apparatus_id: str
    filled_by_assignment_id: Optional[str]
    driver: str
    driver_source_id: Optional[str]
    required_certification: str
    seat_index: int
    status: str


class OvertimeOffer(CommonFields):
    vacancy_id: str
    firefighter_id: str
    roster_id: str
    hiring_mode: str
    offer_hours: int
    projected_cost_cents: int
    expires_at: str
    status: str


class WorkPeriod(CommonFields):
    firefighter_id: str
    period_start_date: str
    period_end_date: str
    flsa_threshold_hours: int
    adjusted_scheduled_hours: int
    adjusted_worked_hours: int
    scheduled_hours: int
    worked_hours: int
    leave_hours: int
    projected_flsa_overtime_hours: int
    final_flsa_overtime_hours: Optional[int]
    flsa_premium_cents: int
    status: str


JsonDict = Dict[str, Any]
