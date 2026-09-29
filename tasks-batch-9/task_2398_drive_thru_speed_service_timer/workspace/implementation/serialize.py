"""Resource serializers — field names come straight from scaffold §1.1."""

from decimal import Decimal

from db import fmt_dt, fmt_ts


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def restaurant(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "store_number": row["store_number"],
        "lane_config": row["lane_config"],
        "merge_slots_capacity": row["merge_slots_capacity"],
        "merge_slots_free": row["merge_slots_free"],
        "labor_minutes_budget": row["labor_minutes_budget"],
        "labor_minutes_committed": row["labor_minutes_committed"],
        "labor_minutes_available": row["labor_minutes_available"],
        "staffing_basis": row["staffing_basis"],
        "cars_closed_trailing": row["cars_closed_trailing"],
        "cars_per_hour_observed": _num(row["cars_per_hour_observed"]),
        "cars_per_hour_effective": _num(row["cars_per_hour_effective"]),
        "volume_tier": row["volume_tier"],
        "required_oot_count": row["required_oot_count"],
        "deployed_oot_count": row["deployed_oot_count"],
        "open_remake_count": row["open_remake_count"],
        "remake_cost_accrued_cents": row["remake_cost_accrued_cents"],
        "posture_override": row["posture_override"],
        "freeze_reason": row["freeze_reason"],
        "service_posture": row["service_posture"],
    })
    return out


def tier_policy(row):
    out = _common(row)
    out.update({
        "tier": row["tier"],
        "cars_per_hour_floor": _num(row["cars_per_hour_floor"]),
        "cars_per_hour_ceiling": _num(row["cars_per_hour_ceiling"]),
        "target_relief_pct": _num(row["target_relief_pct"]),
        "min_oot_count": row["min_oot_count"],
        "merge_award_bias": row["merge_award_bias"],
    })
    return out


def daypart_profile(row):
    out = _common(row)
    out.update({
        "restaurant_id": row["restaurant_id"],
        "daypart": row["daypart"],
        "start_minute": row["start_minute"],
        "end_minute": row["end_minute"],
        "greet_target_seconds": row["greet_target_seconds"],
        "order_target_seconds": row["order_target_seconds"],
        "pull_forward_target_seconds": row["pull_forward_target_seconds"],
        "window_target_seconds": row["window_target_seconds"],
        "total_target_seconds": row["total_target_seconds"],
        "profile_state": row["profile_state"],
    })
    return out


def staff_member(row):
    out = _common(row)
    out.update({
        "restaurant_id": row["restaurant_id"],
        "full_name": row["full_name"],
        "oot_certified": row["oot_certified"],
        "window_certified": row["window_certified"],
        "max_consecutive_deployment_minutes": row["max_consecutive_deployment_minutes"],
        "deployed_minutes_today": row["deployed_minutes_today"],
        "staff_state": row["staff_state"],
    })
    return out


def deployment(row):
    out = _common(row)
    out.update({
        "restaurant_id": row["restaurant_id"],
        "staff_member_id": row["staff_member_id"],
        "daypart_profile_id": row["daypart_profile_id"],
        "position": row["position"],
        "planned_start_at": fmt_dt(row["planned_start_at"]),
        "planned_end_at": fmt_dt(row["planned_end_at"]),
        "planned_minutes": row["planned_minutes"],
        "activated_at": fmt_dt(row["activated_at"]),
        "released_at": fmt_dt(row["released_at"]),
        "labor_minutes_charged": row["labor_minutes_charged"],
        "deployment_state": row["deployment_state"],
        "abort_reason": row["abort_reason"],
    })
    return out


def timer_loop(row):
    out = _common(row)
    out.update({
        "restaurant_id": row["restaurant_id"],
        "daypart_profile_id": row["daypart_profile_id"],
        "served_after_loop_id": row["served_after_loop_id"],
        "lane": row["lane"],
        "car_sequence": row["car_sequence"],
        "arrive_at": fmt_dt(row["arrive_at"]),
        "greet_at": fmt_dt(row["greet_at"]),
        "order_complete_at": fmt_dt(row["order_complete_at"]),
        "merge_at": fmt_dt(row["merge_at"]),
        "window_arrive_at": fmt_dt(row["window_arrive_at"]),
        "depart_at": fmt_dt(row["depart_at"]),
        "order_items_count": row["order_items_count"],
        "greet_seconds": row["greet_seconds"],
        "order_seconds": row["order_seconds"],
        "merge_wait_seconds": row["merge_wait_seconds"],
        "pull_forward_seconds": row["pull_forward_seconds"],
        "window_seconds": row["window_seconds"],
        "total_seconds": row["total_seconds"],
        "adjusted_total_seconds": row["adjusted_total_seconds"],
        "greet_target_pinned": row["greet_target_pinned"],
        "order_target_pinned": row["order_target_pinned"],
        "pull_forward_target_pinned": row["pull_forward_target_pinned"],
        "window_target_pinned": row["window_target_pinned"],
        "target_total_seconds_pinned": row["target_total_seconds_pinned"],
        "breach_flags": list(row["breach_flags"]),
        "timing_state": row["timing_state"],
        "accuracy_state": row["accuracy_state"],
        "abandon_reason": row["abandon_reason"],
    })
    return out


def merge_slot(row):
    out = _common(row)
    out.update({
        "restaurant_id": row["restaurant_id"],
        "timer_loop_id": row["timer_loop_id"],
        "sequence_index": row["sequence_index"],
        "source_lane": row["source_lane"],
        "awarded_at": fmt_dt(row["awarded_at"]),
        "award_reason": row["award_reason"],
        "slot_state": row["slot_state"],
    })
    return out


def pull_forward_order(row):
    out = _common(row)
    out.update({
        "restaurant_id": row["restaurant_id"],
        "timer_loop_id": row["timer_loop_id"],
        "reason": row["reason"],
        "lag_seconds": row["lag_seconds"],
        "issued_at": fmt_dt(row["issued_at"]),
        "reissued_at": fmt_dt(row["reissued_at"]),
        "cleared_at": fmt_dt(row["cleared_at"]),
        "escalation_count": row["escalation_count"],
        "pf_state": row["pf_state"],
    })
    return out


def accuracy_incident(row):
    out = _common(row)
    out.update({
        "restaurant_id": row["restaurant_id"],
        "timer_loop_id": row["timer_loop_id"],
        "logged_by_staff_id": row["logged_by_staff_id"],
        "remade_by_staff_id": row["remade_by_staff_id"],
        "incident_type": row["incident_type"],
        "severity": row["severity"],
        "penalty_seconds": row["penalty_seconds"],
        "remake_cost_cents": row["remake_cost_cents"],
        "incident_state": row["incident_state"],
        "settlement_state": row["settlement_state"],
        "waiver_reason": row["waiver_reason"],
    })
    return out


def throughput_report(row):
    out = _common(row)
    out.update({
        "restaurant_id": row["restaurant_id"],
        "supersedes_report_id": row["supersedes_report_id"],
        "window_start_at": fmt_dt(row["window_start_at"]),
        "window_end_at": fmt_dt(row["window_end_at"]),
        "variant": row["variant"],
        "metric_basis": row["metric_basis"],
        "cars_served": row["cars_served"],
        "cars_per_hour": _num(row["cars_per_hour"]),
        "window_tier": row["window_tier"],
        "avg_metric_seconds": _num(row["avg_metric_seconds"]),
        "mean_pinned_target_seconds": _num(row["mean_pinned_target_seconds"]),
        "target_total_seconds_effective": row["target_total_seconds_effective"],
        "attainment_pct": _num(row["attainment_pct"]),
        "attainment_band": row["attainment_band"],
        "open_remake_incident_count": row["open_remake_incident_count"],
        "coaching_pool_points": row["coaching_pool_points"],
        "report_state": row["report_state"],
        "retraction_reason": row["retraction_reason"],
    })
    return out


def coaching_intervention(row):
    out = _common(row)
    out.update({
        "restaurant_id": row["restaurant_id"],
        "throughput_report_id": row["throughput_report_id"],
        "staff_member_id": row["staff_member_id"],
        "issued_by_user_id": row["issued_by_user_id"],
        "focus_segment": row["focus_segment"],
        "segment_gap_seconds": _num(row["segment_gap_seconds"]),
        "priority_score": _num(row["priority_score"]),
        "tier": row["tier"],
        "revision_count": row["revision_count"],
        "contest_reason": row["contest_reason"],
        "closure_note": row["closure_note"],
        "ci_state": row["ci_state"],
    })
    return out


def forecast_override(row):
    out = _common(row)
    out.update({
        "restaurant_id": row["restaurant_id"],
        "source": row["source"],
        "effective_start_at": fmt_dt(row["effective_start_at"]),
        "effective_end_at": fmt_dt(row["effective_end_at"]),
        "projected_cars_delta_pct": _num(row["projected_cars_delta_pct"]),
        "target_relief_pct_override": _num(row["target_relief_pct_override"]),
        "approved_by_user_id": row["approved_by_user_id"],
        "rejection_reason": row["rejection_reason"],
        "fo_state": row["fo_state"],
    })
    return out
