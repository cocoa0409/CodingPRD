"""Response shapes for the hotel pre-opening program management API.

These TypedDicts document what a caller may read off each entity payload.
Two record types are append-only rows and therefore carry only ``id`` and
``created_at``: a milestone dependency edge and a system test run. Their
TypedDicts deliberately omit ``updated_at`` and ``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """The four properties every non-append-only record carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Program(CommonFields):
    property_name: str
    brand_code: str
    room_count: int
    construction_start_date: str
    target_opening_date: str
    schedule_state: str
    commercial_state: str
    readiness_posture: str
    readiness_score: float
    licensing_buffer_days: int
    rework_buffer_days: int
    slip_tolerance_days: int
    stabilization_window_days: int
    storage_capacity_pallets: int
    relocation_rate_cents: int
    guarantee_penalty_cents: int
    room_night_ceiling: int
    contingency_liability_cap_cents: int
    projected_opening_date: Optional[str]
    projected_opening_date_optimistic: Optional[str]
    projected_opening_date_committed: Optional[str]
    schedule_slip_days: int
    critical_path_milestone_count: int
    open_critical_punch_count: int
    required_system_count: int
    certified_system_count: int
    issued_mandatory_permit_count: int
    hiring_plan_count: int
    departments_ready_count: int
    committed_room_nights: int
    contingency_liability_cents: int
    payroll_accrual_cents: int
    cost_at_completion_commitment_cents: int
    cost_at_completion_accrual_cents: int
    soft_opening_date: Optional[str]
    baselined_by_user_id: Optional[str]
    soft_opening_authorized_by_user_id: Optional[str]


class Readiness(TypedDict):
    """The dedicated computed read: the posture breakdown side by side."""

    readiness_posture: str
    readiness_score: float
    systems_ratio: float
    staffing_ratio: float
    permit_ratio: float
    schedule_term: float
    schedule_slip_days: int
    projected_opening_date_optimistic: Optional[str]
    projected_opening_date_committed: Optional[str]
    variant_gap_days: int
    cost_at_completion_commitment_cents: int
    cost_at_completion_accrual_cents: int
    payroll_accrual_cents: int
    contingency_liability_cents: int
    committed_room_nights: int


class Milestone(CommonFields):
    program_id: str
    code: str
    name: str
    duration_days: int
    planned_start_date: str
    state: str
    actual_start_date: Optional[str]
    actual_finish_date: Optional[str]
    actual_duration_days: Optional[int]
    blocked_days_accrued: int
    rework_count: int
    earliest_start_date: Optional[str]
    earliest_finish_date: Optional[str]
    latest_finish_date: Optional[str]
    total_float_days: Optional[int]
    is_critical: bool


class MilestoneDependency(TypedDict):
    """Append-only join row: only id and created_at."""

    id: str
    created_at: str
    predecessor_milestone_id: str
    successor_milestone_id: str
    dependency_type: str
    lag_days: int


class PermitApplication(CommonFields):
    program_id: str
    gating_milestone_id: str
    permit_type: str
    review_days: int
    state: str
    is_mandatory: bool
    submitted_at: Optional[str]
    issued_at: Optional[str]
    deficiency_reason: Optional[str]
    resubmission_count: int


class SystemImplementation(CommonFields):
    program_id: str
    system_type: str
    is_required: bool
    prerequisite_system_id: Optional[str]
    state: str
    test_run_count: int
    latest_pass_rate: Optional[float]
    cumulative_pass_rate: Optional[float]
    open_blocker_count: int
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]


class SystemTestRun(TypedDict):
    """Append-only evidence row: only id and created_at."""

    id: str
    created_at: str
    system_implementation_id: str
    executed_at: str
    cases_total: int
    cases_passed: int
    blocker_count: int
    pass_rate: float
    result: str
    executed_by_user_id: str


class DepartmentHiringPlan(CommonFields):
    program_id: str
    department: str
    headcount_target: int
    wave_start_date: str
    offered_count: int
    accepted_count: int
    onboarded_count: int
    staffing_ratio: float
    readiness_flag: str


class Hire(CommonFields):
    hiring_plan_id: str
    full_name: str
    hourly_rate_cents: float
    scheduled_hours_per_day: float
    start_date: str
    orientation_session_id: Optional[str]
    state: str
    accrual_cents: int
    onboarded_at: Optional[str]


class TrainingSession(CommonFields):
    program_id: str
    title: str
    training_room_code: str
    starts_at: str
    ends_at: str
    capacity: int
    department: str
    state: str
    enrolled_count: int


class BudgetLine(CommonFields):
    program_id: str
    category: str
    authorized_cents: int
    committed_cents: int
    spent_cents: int
    available_cents: int


class OseOrder(CommonFields):
    program_id: str
    budget_line_id: str
    description: str
    amount_cents: int
    pallet_count: int
    delivery_window_start: str
    delivery_window_end: str
    state: str
    received_at: Optional[str]
    stored_bay_code: Optional[str]


class ReservationBlock(CommonFields):
    program_id: str
    account_name: str
    arrival_date: str
    night_count: int
    room_count: int
    rate_cents: int
    room_nights: int
    revenue_cents: int
    contingency_cents: int
    is_pre_opening: bool
    state: str
    at_risk_reason: Optional[str]


class PunchListItem(CommonFields):
    program_id: str
    milestone_id: Optional[str]
    description: str
    severity: str
    state: str
    blocks_certificate_of_occupancy: bool
    submitted_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    rejection_count: int


class PaginationMeta(TypedDict):
    total_count: int
    has_more: bool
    limit: int
    offset: int


# Loose aliases for helper signatures that accept any decoded ``data`` payload.
JsonObject = Dict[str, Any]
JsonArray = List[Dict[str, Any]]
