"""Output shapes.  Derived fields are recomputed at serialisation time."""

import clock
import derive


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = clock.fmt(row["created_at"])
    if "updated_at" in row:
        out["updated_at"] = clock.fmt(row["updated_at"])
    if "version" in row:
        out["version"] = row["version"]
    return out


def intersection(row):
    out = {
        "location_name": row["location_name"],
        "controller_type": row["controller_type"],
        "detection_status": row["detection_status"],
        "comm_status": row["comm_status"],
        "aps_installed": row["aps_installed"],
        "walking_speed_standard": row["walking_speed_standard"],
        "pedestrian_recall": row["pedestrian_recall"],
        "max_cycle_length_sec": row["max_cycle_length_sec"],
        "last_retimed_at": clock.fmt(row.get("last_retimed_at")),
        "timing_plan_age_days": derive.plan_age_days(row),
        "operational_posture": derive.posture(row),
        "deployed_coordinated_cycle_sec": derive.deployed_coordinated_cycle_sec(row["id"]),
    }
    out.update(derive.budget_fields(row["id"]))
    return _common(row, out)


def corridor(row):
    out = {
        "name": row["name"],
        "jurisdiction_class": row["jurisdiction_class"],
        "annual_volume_change_pct": row["annual_volume_change_pct"],
        "selection_status": row["selection_status"],
        "member_count": derive.member_count(row["id"]),
        "avg_plan_age_days": row["avg_plan_age_days"],
        "complaint_count_12mo": row["complaint_count_12mo"],
        "priority_score": row["priority_score"],
        "priority_score_variant": row["priority_score_variant"],
        "screened_at": clock.fmt(row.get("screened_at")),
    }
    out.update(derive.complaint_counters(row["id"]))
    return _common(row, out)


def corridor_member(row):
    out = {
        "corridor_id": row["corridor_id"],
        "intersection_id": row["intersection_id"],
        "sequence_index": row["sequence_index"],
        "distance_from_prev_ft": row["distance_from_prev_ft"],
    }
    return _common(row, out)


def requester(row):
    out = {
        "display_name": row["display_name"],
        "email": row["email"],
        "contact_pref": row["contact_pref"],
        "open_complaint_count": derive.requester_open_complaint_count(row["id"]),
    }
    return _common(row, out)


def complaint(row):
    out = {
        "requester_id": row["requester_id"],
        "corridor_id": row["corridor_id"],
        "linked_project_id": row.get("linked_project_id"),
        "category": row["category"],
        "narrative": row["narrative"],
        "received_at": clock.fmt(row["received_at"]),
        "status": row["status"],
        "reopen_count": row["reopen_count"],
    }
    return _common(row, out)


def project(row):
    out = {
        "corridor_id": row["corridor_id"],
        "status": row["status"],
        "study_window_start_at": clock.fmt(row["study_window_start_at"]),
        "study_window_days": row["study_window_days"],
        "tuning_round": row["tuning_round"],
        "last_tuning_completed_at": clock.fmt(row.get("last_tuning_completed_at")),
        "lead_engineer_user_id": row["lead_engineer_user_id"],
        "eligible_member_count": row["eligible_member_count"],
    }
    return _common(row, out)


def turning_movement_count(row):
    out = {
        "project_id": row["project_id"],
        "intersection_id": row["intersection_id"],
        "study_role": row["study_role"],
        "count_date": clock.fmt(row["count_date"]),
        "period": row["period"],
        "phase_volumes": row["phase_volumes"],
        "critical_flow_ratio_sum": row["critical_flow_ratio_sum"],
        "recommended_cycle_sec": row["recommended_cycle_sec"],
    }
    return _common(row, out)


def travel_time_run(row):
    out = {
        "project_id": row["project_id"],
        "study_role": row["study_role"],
        "direction": row["direction"],
        "started_at": clock.fmt(row["started_at"]),
        "duration_sec": row["duration_sec"],
        "stops_count": row["stops_count"],
        "arrivals_on_green_count": row["arrivals_on_green_count"],
        "total_arrivals": row["total_arrivals"],
        "recorded_at": clock.fmt(row["recorded_at"]),
    }
    return _common(row, out)


def timing_plan(row):
    out = {
        "project_id": row["project_id"],
        "intersection_id": row["intersection_id"],
        "tod_period": row["tod_period"],
        "tod_start_min": row["tod_start_min"],
        "tod_end_min": row["tod_end_min"],
        "coordination_ref": row["coordination_ref"],
        "cycle_length_sec": row["cycle_length_sec"],
        "drafted_cycle_length_sec": row["drafted_cycle_length_sec"],
        "offset_sec": row["offset_sec"],
        "status": row["status"],
        "ped_compliance_state": row["ped_compliance_state"],
        "drafted_split_total_sec": row["drafted_split_total_sec"],
        "effective_split_total_sec": row["effective_split_total_sec"],
        "authored_by_user_id": row["authored_by_user_id"],
        "certified_by_user_id": row.get("certified_by_user_id"),
        "return_count": row["return_count"],
    }
    return _common(row, out)


def phase_split(row):
    out = {
        "timing_plan_id": row["timing_plan_id"],
        "phase_number": row["phase_number"],
        "split_sec": row["split_sec"],
        "effective_split_sec": row["effective_split_sec"],
        "min_green_sec": row["min_green_sec"],
        "yellow_sec": row["yellow_sec"],
        "red_clearance_sec": row["red_clearance_sec"],
        "is_pedestrian_phase": row["is_pedestrian_phase"],
        "walk_sec": row["walk_sec"],
        "ped_clear_sec": row["ped_clear_sec"],
        "crosswalk_length_ft": row["crosswalk_length_ft"],
    }
    return _common(row, out)


def ped_check(row):
    out = {
        "timing_plan_id": row["timing_plan_id"],
        "phase_number": row["phase_number"],
        "walking_speed_fps": row["walking_speed_fps"],
        "required_ped_clear_sec": row["required_ped_clear_sec"],
        "provided_ped_clear_sec": row["provided_ped_clear_sec"],
        "required_walk_sec": row["required_walk_sec"],
        "provided_walk_sec": row["provided_walk_sec"],
        "required_phase_length_sec": row["required_phase_length_sec"],
        "provided_phase_length_sec": row["provided_phase_length_sec"],
        "result": row["result"],
        "failure_reason": row.get("failure_reason"),
        "waived_by_user_id": row.get("waived_by_user_id"),
        "waiver_justification": row.get("waiver_justification"),
    }
    return _common(row, out)


def priority_config(row):
    out = {
        "intersection_id": row["intersection_id"],
        "priority_type": row["priority_type"],
        "approval_status": row["approval_status"],
        "deployment_status": row["deployment_status"],
        "requested_max_extension_sec": row["requested_max_extension_sec"],
        "max_early_green_sec": row["max_early_green_sec"],
        "conflict_resolution_rank": row["conflict_resolution_rank"],
        "granted_extension_sec": derive.granted_extension_sec(row),
        "proposed_by_user_id": row["proposed_by_user_id"],
        "approved_by_user_id": row.get("approved_by_user_id"),
    }
    return _common(row, out)


def field_observation(row):
    out = {
        "project_id": row["project_id"],
        "intersection_id": row["intersection_id"],
        "tod_period": row["tod_period"],
        "observed_at": clock.fmt(row["observed_at"]),
        "finding_code": row["finding_code"],
        "requires_adjustment": row["requires_adjustment"],
        "resolution_status": row["resolution_status"],
        "observer_user_id": row["observer_user_id"],
    }
    return _common(row, out)


def performance_evaluation(row):
    out = {
        "project_id": row["project_id"],
        "status": row["status"],
        "metric_variant": row["metric_variant"],
        "mean_travel_time_before_sec": row["mean_travel_time_before_sec"],
        "mean_travel_time_after_sec": row["mean_travel_time_after_sec"],
        "delay_reduction_pct": row["delay_reduction_pct"],
        "total_stops_before": row["total_stops_before"],
        "total_stops_after": row["total_stops_after"],
        "stops_reduction_pct": row["stops_reduction_pct"],
        "aog_pct_before": row["aog_pct_before"],
        "aog_pct_after": row["aog_pct_after"],
        "included_after_run_count": row["included_after_run_count"],
        "certified_by_user_id": row.get("certified_by_user_id"),
    }
    return _common(row, out)
