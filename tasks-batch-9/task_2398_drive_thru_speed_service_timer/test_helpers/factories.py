"""Request-body builders.

Each builder returns the minimal valid body declared by the PRD for that
endpoint and accepts `**overrides` so a test can perturb exactly one field
(including setting it to `None` or deleting it via `drop()`).
"""

from typing import Any, Dict, Optional

from .constants import (
    BASE_GREET_TARGET,
    BASE_ORDER_TARGET,
    BASE_PULL_FORWARD_TARGET,
    BASE_WINDOW_TARGET,
    CLOCK_EPOCH,
    LUNCH_END_MINUTE,
    LUNCH_START_MINUTE,
)


def drop(payload: Dict[str, Any], *field_names: str) -> Dict[str, Any]:
    """Return a copy of `payload` with the named fields removed."""
    return {k: v for k, v in payload.items() if k not in field_names}


# --- Clock (PRD §2.4) ---------------------------------------------------------
def clock_body(to_iso8601: str = CLOCK_EPOCH, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_iso8601": to_iso8601}
    body.update(overrides)
    return body


# --- Restaurant (PRD §3.1) ----------------------------------------------------
def restaurant_body(
    store_number: str,
    name: Optional[str] = None,
    lane_config: str = "SINGLE",
    merge_slots_capacity: int = 1,
    labor_minutes_budget: int = 300,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "name": name if name is not None else f"Store {store_number}",
        "store_number": store_number,
        "lane_config": lane_config,
        "merge_slots_capacity": merge_slots_capacity,
        "labor_minutes_budget": labor_minutes_budget,
    }
    body.update(overrides)
    return body


def restaurant_patch_body(**overrides: Any) -> Dict[str, Any]:
    """PATCH body; both declared fields are optional so callers pass what they set."""
    return dict(overrides)


def freeze_body(freeze_reason: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"freeze_reason": freeze_reason}
    body.update(overrides)
    return body


# --- VolumeTierPolicy (PRD §2.8) ---------------------------------------------
def tier_policy_body(
    tier: str,
    cars_per_hour_floor: float,
    target_relief_pct: float,
    min_oot_count: int,
    merge_award_bias: str,
    cars_per_hour_ceiling: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "tier": tier,
        "cars_per_hour_floor": cars_per_hour_floor,
        "target_relief_pct": target_relief_pct,
        "min_oot_count": min_oot_count,
        "merge_award_bias": merge_award_bias,
    }
    if cars_per_hour_ceiling is not None:
        body["cars_per_hour_ceiling"] = cars_per_hour_ceiling
    body.update(overrides)
    return body


# --- DaypartProfile (PRD §3.2) ------------------------------------------------
def daypart_profile_body(
    restaurant_id: str,
    daypart: str = "LUNCH",
    start_minute: int = LUNCH_START_MINUTE,
    end_minute: int = LUNCH_END_MINUTE,
    greet_target_seconds: int = BASE_GREET_TARGET,
    order_target_seconds: int = BASE_ORDER_TARGET,
    pull_forward_target_seconds: int = BASE_PULL_FORWARD_TARGET,
    window_target_seconds: int = BASE_WINDOW_TARGET,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "restaurant_id": restaurant_id,
        "daypart": daypart,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "greet_target_seconds": greet_target_seconds,
        "order_target_seconds": order_target_seconds,
        "pull_forward_target_seconds": pull_forward_target_seconds,
        "window_target_seconds": window_target_seconds,
    }
    body.update(overrides)
    return body


# --- StaffMember (PRD §3.3) ---------------------------------------------------
def staff_member_body(
    restaurant_id: str, full_name: str = "Avery Lane", **overrides: Any
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"restaurant_id": restaurant_id, "full_name": full_name}
    body.update(overrides)
    return body


# --- OrderTakerDeployment (PRD §3.4) -----------------------------------------
def deployment_body(
    restaurant_id: str,
    staff_member_id: str,
    daypart_profile_id: str,
    planned_start_at: str,
    planned_end_at: str,
    position: str = "OOT_LANE_A",
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "restaurant_id": restaurant_id,
        "staff_member_id": staff_member_id,
        "daypart_profile_id": daypart_profile_id,
        "position": position,
        "planned_start_at": planned_start_at,
        "planned_end_at": planned_end_at,
    }
    body.update(overrides)
    return body


def abort_body(abort_reason: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"abort_reason": abort_reason}
    body.update(overrides)
    return body


# --- TimerLoop (PRD §3.5) -----------------------------------------------------
def timer_loop_body(
    restaurant_id: str,
    daypart_profile_id: str,
    lane: str = "SINGLE",
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "restaurant_id": restaurant_id,
        "daypart_profile_id": daypart_profile_id,
        "lane": lane,
    }
    body.update(overrides)
    return body


def order_complete_body(order_items_count: int = 4, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"order_items_count": order_items_count}
    body.update(overrides)
    return body


def abandon_body(abandon_reason: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"abandon_reason": abandon_reason}
    body.update(overrides)
    return body


# --- PullForwardOrder (PRD §3.7) ---------------------------------------------
def pull_forward_body(
    timer_loop_id: str,
    reason: str = "ITEM_LAG",
    lag_seconds: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"timer_loop_id": timer_loop_id, "reason": reason}
    if lag_seconds is not None:
        body["lag_seconds"] = lag_seconds
    body.update(overrides)
    return body


# --- AccuracyIncident (PRD §3.6) ---------------------------------------------
def accuracy_incident_body(
    timer_loop_id: str,
    logged_by_staff_id: str,
    incident_type: str = "WRONG_ITEM",
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "timer_loop_id": timer_loop_id,
        "logged_by_staff_id": logged_by_staff_id,
        "incident_type": incident_type,
    }
    body.update(overrides)
    return body


def deliver_remake_body(remade_by_staff_id: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"remade_by_staff_id": remade_by_staff_id}
    body.update(overrides)
    return body


def waive_body(waiver_reason: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"waiver_reason": waiver_reason}
    body.update(overrides)
    return body


# --- ThroughputReport (PRD §3.8) ---------------------------------------------
def throughput_report_body(
    restaurant_id: str,
    window_start_at: str,
    window_end_at: str,
    expected_restaurant_version: int,
    variant: str = "PROVISIONAL",
    supersedes_report_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "restaurant_id": restaurant_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "variant": variant,
        "expected_restaurant_version": expected_restaurant_version,
    }
    if supersedes_report_id is not None:
        body["supersedes_report_id"] = supersedes_report_id
    body.update(overrides)
    return body


def retract_body(retraction_reason: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"retraction_reason": retraction_reason}
    body.update(overrides)
    return body


# --- CoachingIntervention (PRD §3.9) -----------------------------------------
def coaching_body(
    throughput_report_id: str,
    staff_member_id: str,
    focus_segment: str = "GREET",
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "throughput_report_id": throughput_report_id,
        "staff_member_id": staff_member_id,
        "focus_segment": focus_segment,
    }
    body.update(overrides)
    return body


def contest_body(contest_reason: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"contest_reason": contest_reason}
    body.update(overrides)
    return body


def closure_body(closure_note: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"closure_note": closure_note}
    body.update(overrides)
    return body


# --- ForecastOverride (PRD §3.10) --------------------------------------------
def forecast_override_body(
    restaurant_id: str,
    effective_start_at: str,
    effective_end_at: str,
    projected_cars_delta_pct: float,
    expected_restaurant_version: int,
    source: str = "WEATHER",
    target_relief_pct_override: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "restaurant_id": restaurant_id,
        "source": source,
        "effective_start_at": effective_start_at,
        "effective_end_at": effective_end_at,
        "projected_cars_delta_pct": projected_cars_delta_pct,
        "expected_restaurant_version": expected_restaurant_version,
    }
    if target_relief_pct_override is not None:
        body["target_relief_pct_override"] = target_relief_pct_override
    body.update(overrides)
    return body


def reject_body(rejection_reason: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"rejection_reason": rejection_reason}
    body.update(overrides)
    return body
