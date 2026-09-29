"""Response shapes for the twelve declared entities.

The PRD states that every entity carries `id`, `created_at`, `updated_at` and
`version`, and that no entity omits `updated_at` or `version`; those four live on
`CommonFields` and every entity shape inherits them.

These TypedDicts are `total=False` on purpose: tests assert on the fields the PRD
declares for the pathway under test rather than on whole-object equality.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict, total=False):
    """The four fields present on every entity."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Restaurant(CommonFields, total=False):
    name: str
    store_number: str
    lane_config: str
    merge_slots_capacity: int
    merge_slots_free: int
    labor_minutes_budget: int
    labor_minutes_committed: int
    labor_minutes_available: int
    staffing_basis: str
    cars_closed_trailing: int
    cars_per_hour_observed: float
    cars_per_hour_effective: float
    volume_tier: str
    required_oot_count: int
    deployed_oot_count: int
    open_remake_count: int
    remake_cost_accrued_cents: int
    posture_override: str
    freeze_reason: Optional[str]
    service_posture: str


class VolumeTierPolicy(CommonFields, total=False):
    tier: str
    cars_per_hour_floor: float
    cars_per_hour_ceiling: Optional[float]
    target_relief_pct: float
    min_oot_count: int
    merge_award_bias: str


class DaypartProfile(CommonFields, total=False):
    restaurant_id: str
    daypart: str
    start_minute: int
    end_minute: int
    greet_target_seconds: int
    order_target_seconds: int
    pull_forward_target_seconds: int
    window_target_seconds: int
    total_target_seconds: int
    profile_state: str


class StaffMember(CommonFields, total=False):
    restaurant_id: str
    full_name: str
    oot_certified: bool
    window_certified: bool
    max_consecutive_deployment_minutes: int
    deployed_minutes_today: int
    staff_state: str


class OrderTakerDeployment(CommonFields, total=False):
    restaurant_id: str
    staff_member_id: str
    daypart_profile_id: str
    position: str
    planned_start_at: str
    planned_end_at: str
    planned_minutes: int
    activated_at: Optional[str]
    released_at: Optional[str]
    labor_minutes_charged: int
    deployment_state: str
    abort_reason: Optional[str]


class TimerLoop(CommonFields, total=False):
    restaurant_id: str
    daypart_profile_id: str
    served_after_loop_id: Optional[str]
    lane: str
    car_sequence: int
    arrive_at: str
    greet_at: Optional[str]
    order_complete_at: Optional[str]
    merge_at: Optional[str]
    window_arrive_at: Optional[str]
    depart_at: Optional[str]
    order_items_count: Optional[int]
    greet_seconds: Optional[int]
    order_seconds: Optional[int]
    merge_wait_seconds: Optional[int]
    pull_forward_seconds: Optional[int]
    window_seconds: Optional[int]
    total_seconds: Optional[int]
    adjusted_total_seconds: Optional[int]
    greet_target_pinned: int
    order_target_pinned: int
    pull_forward_target_pinned: int
    window_target_pinned: int
    target_total_seconds_pinned: int
    breach_flags: List[str]
    timing_state: str
    accuracy_state: str
    abandon_reason: Optional[str]


class MergeSlot(CommonFields, total=False):
    restaurant_id: str
    timer_loop_id: str
    sequence_index: int
    source_lane: str
    awarded_at: str
    award_reason: str
    slot_state: str


class PullForwardOrder(CommonFields, total=False):
    restaurant_id: str
    timer_loop_id: str
    reason: str
    lag_seconds: int
    issued_at: str
    reissued_at: Optional[str]
    cleared_at: Optional[str]
    escalation_count: int
    pf_state: str


class AccuracyIncident(CommonFields, total=False):
    restaurant_id: str
    timer_loop_id: str
    logged_by_staff_id: str
    remade_by_staff_id: Optional[str]
    incident_type: str
    severity: str
    penalty_seconds: int
    remake_cost_cents: int
    incident_state: str
    settlement_state: str
    waiver_reason: Optional[str]


class ThroughputReport(CommonFields, total=False):
    restaurant_id: str
    supersedes_report_id: Optional[str]
    window_start_at: str
    window_end_at: str
    variant: str
    metric_basis: str
    cars_served: int
    cars_per_hour: float
    window_tier: str
    avg_metric_seconds: Optional[float]
    mean_pinned_target_seconds: Optional[float]
    target_total_seconds_effective: Optional[int]
    attainment_pct: Optional[float]
    attainment_band: Optional[str]
    open_remake_incident_count: int
    coaching_pool_points: int
    report_state: str
    retraction_reason: Optional[str]


class CoachingIntervention(CommonFields, total=False):
    restaurant_id: str
    throughput_report_id: str
    staff_member_id: str
    issued_by_user_id: Optional[str]
    focus_segment: str
    segment_gap_seconds: float
    priority_score: float
    tier: str
    revision_count: int
    contest_reason: Optional[str]
    closure_note: Optional[str]
    ci_state: str


class ForecastOverride(CommonFields, total=False):
    restaurant_id: str
    source: str
    effective_start_at: str
    effective_end_at: str
    projected_cars_delta_pct: float
    target_relief_pct_override: Optional[float]
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    fo_state: str


# Field names shared by every entity, for the "common fields present" checks.
COMMON_FIELD_NAMES = ("id", "created_at", "updated_at", "version")

# The state field each entity uses, keyed by entity name.
STATE_FIELD_BY_ENTITY: Dict[str, str] = {
    "Restaurant": "service_posture",
    "DaypartProfile": "profile_state",
    "StaffMember": "staff_state",
    "OrderTakerDeployment": "deployment_state",
    "TimerLoop": "timing_state",
    "MergeSlot": "slot_state",
    "PullForwardOrder": "pf_state",
    "AccuracyIncident": "incident_state",
    "ThroughputReport": "report_state",
    "CoachingIntervention": "ci_state",
    "ForecastOverride": "fo_state",
}

JsonDict = Dict[str, Any]
