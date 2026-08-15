"""Domain types: entity TypedDicts, status enums, role enum (PRD 2.1, 2.4, 3.x)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    DISTRICT_ADMIN = "DistrictAdmin"
    SCHOOL_COORDINATOR = "SchoolCoordinator"
    TEACHER = "Teacher"
    SUBSTITUTE = "Substitute"
    PAYROLL_CLERK = "PayrollClerk"


class SubstituteStatus(str, Enum):
    PENDING_CLEARANCE = "PENDING_CLEARANCE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClearanceStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class ClearanceType(str, Enum):
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    TEACHING_CREDENTIAL = "TEACHING_CREDENTIAL"
    TB_TEST = "TB_TEST"


class MarkType(str, Enum):
    PREFERRED = "PREFERRED"
    DO_NOT_RETURN = "DO_NOT_RETURN"


class MarkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class AbsenceFillStatus(str, Enum):
    REPORTED = "REPORTED"
    DISPATCHING = "DISPATCHING"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    UNFILLED = "UNFILLED"
    COVERED_INTERNALLY = "COVERED_INTERNALLY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AbsenceApprovalStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AbsenceType(str, Enum):
    SICK = "SICK"
    PERSONAL = "PERSONAL"
    PROFESSIONAL_DEVELOPMENT = "PROFESSIONAL_DEVELOPMENT"
    JURY_DUTY = "JURY_DUTY"


class GradeBand(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"


class HardToFillTier(str, Enum):
    NONE = "NONE"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    WORKED = "WORKED"
    NO_SHOW = "NO_SHOW"
    VERIFIED = "VERIFIED"
    PAID = "PAID"


class OfferSource(str, Enum):
    AUTO_DISPATCH = "AUTO_DISPATCH"
    MANUAL_OFFER = "MANUAL_OFFER"
    SELF_CLAIM = "SELF_CLAIM"


class CancelReason(str, Enum):
    SUB_CANCEL = "SUB_CANCEL"
    COORDINATOR_CANCEL = "COORDINATOR_CANCEL"
    DNR_CANCEL = "DNR_CANCEL"
    SUSPENSION_CANCEL = "SUSPENSION_CANCEL"
    ABSENCE_CANCEL = "ABSENCE_CANCEL"


class CoverageStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WORKED = "WORKED"
    COMPENSATED = "COMPENSATED"
    CANCELLED = "CANCELLED"


class TimesheetStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPORTED = "EXPORTED"


class PayrollPeriodStatus(str, Enum):
    OPEN = "OPEN"
    EXPORTED = "EXPORTED"


class FlagType(str, Enum):
    NO_SHOW = "NO_SHOW"
    CONDUCT = "CONDUCT"
    QUALITY = "QUALITY"
    TARDINESS = "TARDINESS"


class FlagSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD 2.4).


class District(TypedDict, total=False):
    id: str
    name: str
    offer_response_window_minutes: int
    long_term_approval_days: int
    long_term_threshold_days: int
    long_term_rate_multiplier: float
    htf_high_premium_pct: float
    htf_moderate_premium_pct: float
    short_notice_hours: int
    short_notice_premium_pct: float
    moderate_notice_hours: int
    moderate_notice_premium_pct: float
    premium_cap_multiplier: float
    preference_rank_boost: int
    reliability_window_days: int
    suspension_score_threshold: int
    suspension_min_completions: int
    period_comp_rate_cents: int
    daily_period_cap: int
    weekly_period_cap: int
    created_at: str
    updated_at: str
    version: int


class School(TypedDict, total=False):
    id: str
    district_id: str
    name: str
    hard_to_fill_tier: str
    coverage_budget_total_cents: int
    coverage_budget_committed_cents: int
    coverage_budget_spent_cents: int
    coverage_budget_available_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    school_id: str
    full_name: str
    subject: str
    grade_band: str
    is_coordinator: bool
    created_at: str
    updated_at: str
    version: int


class Substitute(TypedDict, total=False):
    id: str
    full_name: str
    base_daily_rate_cents: int
    status: str
    reliability_events: List[Dict[str, Any]]
    reliability_lifetime_score: int
    reliability_trailing_score: int
    completions_lifetime: int
    completions_trailing: int
    created_at: str
    updated_at: str
    version: int


class Clearance(TypedDict, total=False):
    id: str
    substitute_id: str
    clearance_type: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SchoolSubstituteMark(TypedDict, total=False):
    id: str
    school_id: str
    substitute_id: str
    mark_type: str
    priority_rank: Optional[int]
    reason: Optional[str]
    status: str
    source_flag_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Absence(TypedDict, total=False):
    id: str
    staff_member_id: str
    school_id: str
    start_date: str
    end_date: str
    absence_type: str
    required_subject: str
    required_grade_band: str
    total_days: int
    fill_status: str
    approval_status: str
    days_covered_internal: int
    days_covered_sub: int
    days_uncovered: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    absence_id: str
    substitute_id: str
    school_id: str
    offer_source: str
    offer_sequence: int
    status: str
    cancel_reason: Optional[str]
    offered_at: str
    offer_expires_at: str
    start_date: str
    end_date: str
    scheduled_days: int
    premium_multiplier_snapshot: float
    provisional_pay_cents: int
    worked_days_count: int
    long_term_converted: bool
    final_payout_cents: Optional[int]
    payout_capped: bool
    created_at: str
    updated_at: str
    version: int


class InternalCoverage(TypedDict, total=False):
    id: str
    absence_id: str
    staff_member_id: str
    school_id: str
    coverage_date: str
    periods: int
    status: str
    compensation_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Timesheet(TypedDict, total=False):
    id: str
    assignment_id: str
    substitute_id: str
    payroll_period_id: Optional[str]
    work_date: str
    hours_worked: float
    status: str
    streak_index: Optional[int]
    day_pay_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PayrollPeriod(TypedDict, total=False):
    id: str
    district_id: str
    period_start: str
    period_end: str
    status: str
    total_payout_cents: Optional[int]
    assignments_paid_count: Optional[int]
    coverages_compensated_count: Optional[int]
    exported_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceFlag(TypedDict, total=False):
    id: str
    substitute_id: str
    school_id: str
    assignment_id: Optional[str]
    flag_type: str
    severity: str
    status: str
    auto_created: bool
    created_at: str
    updated_at: str
    version: int


# Append-only record types (PRD 2.4): only id + created_at, no updated_at/version.


class Qualification(TypedDict, total=False):
    id: str
    substitute_id: str
    subject: str
    grade_band: str
    created_at: str


class DispatchBatch(TypedDict, total=False):
    id: str
    district_id: str
    run_for_date: Optional[str]
    executed_at: str
    absences_considered: int
    offers_created: int
    offers_expired: int
    absences_marked_unfilled: int
    created_at: str
