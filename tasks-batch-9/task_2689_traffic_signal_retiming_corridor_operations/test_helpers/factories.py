"""Payload factories — one per entity, input fields only."""
import itertools

_seq = itertools.count(1)


def unique_suffix() -> str:
    return str(next(_seq))


def intersection_payload(**overrides) -> dict:
    payload = {
        "location_name": f"Main St @ {unique_suffix()}th Ave",
        "controller_type": "TS2_CABINET",
    }
    payload.update(overrides)
    return payload


def corridor_payload(**overrides) -> dict:
    payload = {
        "name": f"Main St Corridor {unique_suffix()}",
        "jurisdiction_class": "ARTERIAL",
        "annual_volume_change_pct": 20.0,
    }
    payload.update(overrides)
    return payload


def corridor_member_payload(intersection_id: str, sequence_index: int, **overrides) -> dict:
    payload = {
        "intersection_id": intersection_id,
        "sequence_index": sequence_index,
        "distance_from_prev_ft": 0 if sequence_index == 1 else 1320,
    }
    payload.update(overrides)
    return payload


def requester_payload(**overrides) -> dict:
    n = unique_suffix()
    payload = {
        "display_name": f"Citizen {n}",
        "email": f"citizen{n}@example.com",
        "contact_pref": "EMAIL",
    }
    payload.update(overrides)
    return payload


def complaint_payload(requester_id: str, corridor_id: str, **overrides) -> dict:
    payload = {
        "requester_id": requester_id,
        "corridor_id": corridor_id,
        "category": "COORDINATION",
        "narrative": "The northbound signals no longer run together in the evening peak.",
    }
    payload.update(overrides)
    return payload


def retiming_project_payload(corridor_id: str, **overrides) -> dict:
    payload = {
        "corridor_id": corridor_id,
        "study_window_start_at": "2026-07-01T00:00:00Z",
        "study_window_days": 180,
        "lead_engineer_user_id": "timing-eng-1",
    }
    payload.update(overrides)
    return payload


def turning_movement_count_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "study_role": "BEFORE",
        "count_date": "2026-07-15T00:00:00Z",
        "period": "AM_PEAK",
        "phase_volumes": {"1": 350, "2": 500, "4": 250, "6": 180},
    }
    payload.update(overrides)
    return payload


def travel_time_run_payload(**overrides) -> dict:
    payload = {
        "study_role": "BEFORE",
        "direction": "NB",
        "started_at": "2026-07-15T09:00:00Z",
        "duration_sec": 320,
        "stops_count": 5,
        "arrivals_on_green_count": 4,
        "total_arrivals": 12,
    }
    payload.update(overrides)
    return payload


def timing_plan_payload(project_id: str, intersection_id: str, expected_project_version: int,
                        **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "intersection_id": intersection_id,
        "tod_period": "AM_PEAK",
        "tod_start_min": 360,
        "tod_end_min": 540,
        "coordination_ref": "MASTER",
        "cycle_length_sec": 120,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def phase_split_payload(timing_plan_id: str, phase_number: int, **overrides) -> dict:
    payload = {
        "timing_plan_id": timing_plan_id,
        "phase_number": phase_number,
        "split_sec": 30,
        "min_green_sec": 10,
        "yellow_sec": 4.0,
        "red_clearance_sec": 2.0,
    }
    payload.update(overrides)
    return payload


def pedestrian_phase_split_payload(timing_plan_id: str, phase_number: int, **overrides) -> dict:
    payload = phase_split_payload(
        timing_plan_id,
        phase_number,
        is_pedestrian_phase=True,
        walk_sec=7.0,
        ped_clear_sec=12.0,
        crosswalk_length_ft=42.0,
    )
    payload.update(overrides)
    return payload


def priority_config_payload(intersection_id: str, expected_intersection_version: int,
                            **overrides) -> dict:
    payload = {
        "intersection_id": intersection_id,
        "priority_type": "TSP",
        "requested_max_extension_sec": 10,
        "max_early_green_sec": 0,
        "conflict_resolution_rank": 1,
        "expected_intersection_version": expected_intersection_version,
    }
    payload.update(overrides)
    return payload


def field_observation_payload(project_id: str, intersection_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "intersection_id": intersection_id,
        "tod_period": "AM_PEAK",
        "observed_at": "2026-08-01T00:00:00Z",
        "finding_code": "QUEUE_SPILLBACK",
        "requires_adjustment": False,
    }
    payload.update(overrides)
    return payload


def performance_evaluation_payload(expected_project_version: int, **overrides) -> dict:
    payload = {"expected_project_version": expected_project_version}
    payload.update(overrides)
    return payload
