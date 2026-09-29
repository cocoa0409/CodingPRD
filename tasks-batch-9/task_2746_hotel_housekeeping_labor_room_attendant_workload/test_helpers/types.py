"""TypedDict shapes for the resources of the Hotel Housekeeping Labor API.

Field sets follow PRD 2.4: every resource carries `id` and `created_at`, and all
resources except `Inspection` additionally carry `updated_at` and `version`.
`Inspection` is immutable once filed and carries only `id` and `created_at`.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict


class PropertyResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    ordinance_profile: str
    credit_minute_value: int
    standard_shift_minutes: int
    pre_post_shift_minutes: int
    min_daily_paid_minutes: int
    max_daily_credits: float
    max_daily_square_feet: int
    laundry_sla_minutes: int
    laundry_capacity_sets: int
    reclean_threshold_score: float
    inspection_sample_rate: float
    probation_sample_rate: float
    rest_buffer_minutes: int
    total_rooms: int
    outstanding_incentive_points: int


class RoomTypeResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    code: str
    square_feet: int
    checkout_credits: float
    stayover_credits: float
    deep_clean_credits: float
    linen_sets_per_room: int
    room_count: int


class RoomResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    room_type_id: str
    room_number: str
    floor: int
    service_program: str
    occupancy_state: str
    cleanliness_status: str
    last_serviced_business_date: Optional[str]
    last_deep_cleaned_business_date: Optional[str]


class AttendantResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    employee_code: str
    full_name: str
    seniority_date: str
    hourly_rate_cents: int
    can_inspect: bool
    restricted_duty: bool
    status: str
    quality_probation: bool
    lifetime_fail_count: int


class ForecastDayResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    business_date: str
    status: str
    forecast_occupied_rooms: int
    forecast_arrivals: int
    forecast_departures: int
    planned_deep_clean_rooms: int
    projected_required_credits: float
    required_attendants: int
    allocated_credits_total: float
    actual_reconciled_credits: Optional[float]
    credit_variance_pct: Optional[float]


class ShiftRosterResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    forecast_day_id: str
    attendant_id: str
    planned_start_at: Optional[str]
    status: str
    compliance_state: str
    waiver_state: str
    effective_credit_cap: float
    effective_sqft_cap: Optional[int]
    assigned_credits: float
    assigned_square_feet: int
    waiver_requested_credits: Optional[float]
    waiver_requested_by_user_id: Optional[str]
    waiver_decided_by_user_id: Optional[str]
    worked_minutes: Optional[int]
    break_minutes: int
    paid_minutes: Optional[int]
    overtime_minutes: Optional[int]
    rooms_completed_gross: int
    rooms_credited_net: int
    required_inspection_samples: int
    inspections_completed: int
    minutes_per_room_gross: Optional[float]
    minutes_per_room_net: Optional[float]
    target_minutes_per_room: Optional[float]
    productivity_flag: str
    base_wage_cents: Optional[int]
    ordinance_premium_cents: Optional[int]
    total_labor_cost_cents: Optional[int]


class RoomAssignmentResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    roster_id: str
    room_id: str
    service_type: str
    status: str
    credits: float
    square_feet_snapshot: int
    reclean_generation: int
    supersedes_assignment_id: Optional[str]
    linen_sets_debited: int
    started_at: Optional[str]
    completed_at: Optional[str]
    actual_minutes: Optional[int]
    roster_version_after: int


class InspectionResource(TypedDict, total=False):
    """PRD 2.4: an `Inspection` carries only `id` and `created_at`."""

    id: str
    created_at: str
    assignment_id: str
    inspector_attendant_id: str
    bathroom_points: int
    linen_points: int
    dust_points: int
    amenity_points: int
    floor_points: int
    score_pct: float
    critical_fail: bool
    result: str
    generated_reclean_assignment_id: Optional[str]


class LinenItemResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    linen_type: str
    total_owned_sets: int
    on_hand_clean: int
    in_laundry: int
    soiled_queue: int
    par_required_sets: int
    coverage_ratio: Optional[float]
    shortage_status: str


class LaundryCycleResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    linen_item_id: str
    status: str
    batch_sets: int
    dispatched_at: str
    expected_return_at: str
    returned_at: Optional[str]
    returned_sets: Optional[int]
    turnaround_minutes: Optional[int]
    sla_breach: bool
    linen_item_version_after: int


class LostFoundItemResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    room_id: str
    found_by_attendant_id: str
    description: str
    category: str
    status: str
    logged_at: str
    stored_at: Optional[str]
    storage_bin: Optional[str]
    retention_days: Optional[int]
    retention_expires_at: Optional[str]
    claim_attempt_count: int
    claimant_name: Optional[str]
    claimant_contact: Optional[str]
    proof_kind: Optional[str]
    denial_reason: Optional[str]
    tracking_code: Optional[str]


class ServiceEnrollmentResource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    room_id: str
    reservation_code: str
    program: str
    nights: int
    status: str
    points_per_skip: int
    skips_accrued: int
    points_accrued: int


class SamplePlanResource(TypedDict, total=False):
    """Shape of the computed read at GET .../inspection-sample-plan (PRD 3.6)."""

    roster_id: str
    completed_count: int
    sample_rate: float
    required_samples: int
    inspections_completed: int
    remaining_samples: int
    selected_assignment_ids: list[str]


JsonDict = dict[str, Any]
