"""Typed shapes and enumerations for the busy-season scheduling service.

Every enumeration mirrors the value set the API contract declares for the
corresponding field. Two record types -- availability exceptions and time
entries -- are append-only and carry only ``id`` and ``created_at``; their
TypedDicts deliberately omit ``updated_at`` and ``version``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    SCHEDULING_MANAGER = "SchedulingManager"
    ENGAGEMENT_PARTNER = "EngagementPartner"
    ENGAGEMENT_STAFF = "EngagementStaff"
    INDEPENDENCE_OFFICER = "IndependenceOfficer"


ALL_ROLE_NAMES: List[str] = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Reference-data enumerations
# ---------------------------------------------------------------------------


class IndustryCode(str, Enum):
    FINANCIAL_SERVICES = "FINANCIAL_SERVICES"
    MANUFACTURING = "MANUFACTURING"
    GOVERNMENT = "GOVERNMENT"
    TECHNOLOGY = "TECHNOLOGY"
    HEALTHCARE = "HEALTHCARE"


class StaffLevel(str, Enum):
    STAFF = "STAFF"
    SENIOR = "SENIOR"
    MANAGER = "MANAGER"
    PARTNER = "PARTNER"


class ServiceCenter(str, Enum):
    DOMESTIC = "DOMESTIC"
    OFFSHORE = "OFFSHORE"


class WorkloadStatus(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class TurnoverRiskBand(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class ServiceLine(str, Enum):
    AUDIT = "AUDIT"
    TAX = "TAX"
    ADVISORY = "ADVISORY"


class ScheduleRiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PhaseType(str, Enum):
    PLANNING = "PLANNING"
    INTERIM = "INTERIM"
    FIELDWORK = "FIELDWORK"
    REVIEW = "REVIEW"
    WRAP_UP = "WRAP_UP"


class RateModel(str, Enum):
    ONSHORE_STANDARD = "ONSHORE_STANDARD"
    OFFSHORE_SHARED_SERVICE = "OFFSHORE_SHARED_SERVICE"


class ExceptionType(str, Enum):
    PTO = "PTO"
    LICENSURE_STUDY_LEAVE = "LICENSURE_STUDY_LEAVE"
    TRAINING = "TRAINING"
    FIRM_HOLIDAY = "FIRM_HOLIDAY"


class TimeEntryType(str, Enum):
    EXECUTION = "EXECUTION"
    REVIEW = "REVIEW"
    REWORK = "REWORK"


class RestrictionType(str, Enum):
    FINANCIAL_INTEREST = "FINANCIAL_INTEREST"
    EMPLOYMENT_NEGOTIATION = "EMPLOYMENT_NEGOTIATION"
    ROTATION_COOLING_OFF = "ROTATION_COOLING_OFF"
    RELATIVE_EMPLOYED = "RELATIVE_EMPLOYED"


class TriggerReason(str, Enum):
    CLIENT_READINESS_SLIP = "CLIENT_READINESS_SLIP"
    SCOPE_EXPANSION = "SCOPE_EXPANSION"
    STAFF_ATTRITION = "STAFF_ATTRITION"


class WaiverExpiryReason(str, Enum):
    ENGAGEMENT_BLOCKED = "ENGAGEMENT_BLOCKED"
    RESTRICTION_IMPOSED = "RESTRICTION_IMPOSED"


# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------


class EngagementStatus(str, Enum):
    SETUP = "SETUP"
    SCHEDULED = "SCHEDULED"
    IN_FIELDWORK = "IN_FIELDWORK"
    CLIENT_BLOCKED = "CLIENT_BLOCKED"
    DELIVERED = "DELIVERED"


class PhaseStaffingStatus(str, Enum):
    NOT_STAFFED = "NOT_STAFFED"
    PARTIALLY_STAFFED = "PARTIALLY_STAFFED"
    FULLY_STAFFED = "FULLY_STAFFED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class AssignmentStaffingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class AssignmentReviewStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_REVIEW = "PENDING_REVIEW"
    IN_REVIEW = "IN_REVIEW"
    REWORK_REQUESTED = "REWORK_REQUESTED"
    REVIEW_ACCEPTED = "REVIEW_ACCEPTED"


class RestrictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class ReschedulePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SIMULATED = "SIMULATED"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"


class WaiverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class Client(TypedDict):
    id: str
    name: str
    industry_code: str
    public_interest_entity: bool
    fiscal_year_end: str
    partner_rotation_limit_years: int
    engagement_count: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    full_name: str
    level: str
    service_center: str
    industry_specialization: str
    cpa_licensed: bool
    base_weekly_cap_hours: float
    hourly_bill_rate: float
    review_capable: bool
    committed_hours_current_week: float
    effective_weekly_cap_hours: float
    daily_capacity_hours: float
    workload_status: str
    burnout_risk_score_actual: float
    burnout_risk_score_committed: float
    turnover_risk_band: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    client_id: str
    engagement_partner_staff_id: str
    service_line: str
    busy_season_year: int
    deadline_date: str
    budget_fee_amount: float
    status: str
    pre_block_status: Optional[str]
    client_block_count: int
    scope_change_count: int
    staffing_completion_pct: float
    schedule_risk_band: str
    realization_pct_provisional: float
    realization_pct_final: float
    created_at: str
    updated_at: str
    version: int


class EngagementPhase(TypedDict):
    id: str
    engagement_id: str
    phase_type: str
    expected_hours: float
    window_start_date: str
    window_end_date: str
    required_level: str
    required_industry_specialization: Optional[str]
    requires_cpa_licensed: bool
    staffing_status: str
    staffed_hours: float
    unstaffed_hours: float
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    engagement_phase_id: str
    staff_member_id: str
    start_date: str
    end_date: str
    allocated_hours: float
    review_owner_staff_id: Optional[str]
    review_capacity_window_id: Optional[str]
    daily_hours: float
    calendar_day_count: int
    rate_model: str
    review_hours_charged: float
    fit_score: float
    staffing_status: str
    review_status: str
    rework_cycles: int
    superseded_by_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AvailabilityException(TypedDict):
    """Append-only record: no ``updated_at`` and no ``version``."""

    id: str
    staff_member_id: str
    exception_type: str
    start_date: str
    end_date: str
    available_hours_per_day: float
    created_at: str


class TimeEntry(TypedDict):
    """Append-only record: no ``updated_at`` and no ``version``."""

    id: str
    assignment_id: str
    work_date: str
    hours: float
    entry_type: str
    created_at: str


class IndependenceRestriction(TypedDict):
    id: str
    client_id: str
    staff_member_id: str
    restriction_type: str
    effective_start_date: str
    effective_end_date: str
    status: str
    released_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class ReviewCapacityWindow(TypedDict):
    id: str
    reviewer_staff_id: str
    week_start_date: str
    review_capacity_hours: float
    committed_review_hours: float
    remaining_review_hours: float
    created_at: str
    updated_at: str
    version: int


class ReschedulePlan(TypedDict):
    id: str
    engagement_id: str
    trigger_reason: str
    shift_days: int
    added_hours: float
    status: str
    target_phase_id: Optional[str]
    simulated_at_engagement_version: Optional[int]
    simulation_stale: bool
    projected_unstaffed_hours: Optional[float]
    projected_dropped_assignment_count: Optional[int]
    projected_cap_breach_count: Optional[int]
    projected_realization_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class WorkloadWaiver(TypedDict):
    id: str
    staff_member_id: str
    engagement_id: str
    week_start_date: str
    extra_hours_allowance: float
    status: str
    approved_by_user_id: Optional[str]
    expiry_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Read-model shapes (non-entity projections)
# ---------------------------------------------------------------------------


class WorkloadRead(TypedDict):
    staff_member_id: str
    week_start_date: str
    committed_hours: float
    logged_hours: float
    approved_waiver_hours: float
    effective_weekly_cap_hours: float
    daily_capacity_hours: float
    remaining_week_hours: float
    workload_status: str
    burnout_risk_score_actual: float
    burnout_risk_score_committed: float
    turnover_risk_band: str


class RealizationRead(TypedDict):
    engagement_id: str
    budget_fee_amount: float
    committed_hours_total: float
    logged_hours_total: float
    standard_value_provisional: float
    standard_value_final: float
    realization_pct_provisional: float
    realization_pct_final: float
    onshore_standard_value: float
    offshore_standard_value: float


class ClockRead(TypedDict):
    current_utc: str
    current_date: str
    iso_week_start_date: str


Headers = Dict[str, str]
JsonDict = Dict[str, Any]

__all__ = [
    "UserRole",
    "ALL_ROLE_NAMES",
    "IndustryCode",
    "StaffLevel",
    "ServiceCenter",
    "WorkloadStatus",
    "TurnoverRiskBand",
    "ServiceLine",
    "ScheduleRiskBand",
    "PhaseType",
    "RateModel",
    "ExceptionType",
    "TimeEntryType",
    "RestrictionType",
    "TriggerReason",
    "WaiverExpiryReason",
    "EngagementStatus",
    "PhaseStaffingStatus",
    "AssignmentStaffingStatus",
    "AssignmentReviewStatus",
    "RestrictionStatus",
    "ReschedulePlanStatus",
    "WaiverStatus",
    "Client",
    "StaffMember",
    "Engagement",
    "EngagementPhase",
    "Assignment",
    "AvailabilityException",
    "TimeEntry",
    "IndependenceRestriction",
    "ReviewCapacityWindow",
    "ReschedulePlan",
    "WorkloadWaiver",
    "WorkloadRead",
    "RealizationRead",
    "ClockRead",
    "Headers",
    "JsonDict",
]
