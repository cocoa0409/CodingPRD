"""Payload factories - one per write endpoint, carrying only client-supplied fields."""
from typing import Any, Dict, List, Optional

DEFAULTS = {
    "SCHOOL_NAME": "Maple Grove Elementary",
    "DISTRICT_CODE": "D-07",
    "ENROLLMENT_COUNT": 640,
    "SESSION_START_DATE": "2026-08-24",
    "SESSION_END_DATE": "2027-06-11",
    "AM_WINDOW_START_UTC": "07:15",
    "AM_WINDOW_END_UTC": "08:15",
    "PM_WINDOW_START_UTC": "14:45",
    "PM_WINDOW_END_UTC": "15:45",
    "BASELINE_MODE_SHARE_PCT": 18.50,
    "CROSS_STREETS": "Maple St & 3rd Ave",
    "GUARD_NAME": "Rita Alvarez",
    "ZONE_CODE": "Z-NORTH",
    "HIRE_DATE": "2026-08-03",
    "CURRICULUM_CODE": "SRTS-BASIC",
    "POST_LABEL": "Maple NW corner",
    "PROGRAM_NAME": "FY27 Safe Routes Capital",
    "FISCAL_YEAR": 2027,
}


def create_school_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": DEFAULTS["SCHOOL_NAME"],
        "district_code": DEFAULTS["DISTRICT_CODE"],
        "enrollment_count": DEFAULTS["ENROLLMENT_COUNT"],
        "session_start_date": DEFAULTS["SESSION_START_DATE"],
        "session_end_date": DEFAULTS["SESSION_END_DATE"],
        "am_window_start_utc": DEFAULTS["AM_WINDOW_START_UTC"],
        "am_window_end_utc": DEFAULTS["AM_WINDOW_END_UTC"],
        "pm_window_start_utc": DEFAULTS["PM_WINDOW_START_UTC"],
        "pm_window_end_utc": DEFAULTS["PM_WINDOW_END_UTC"],
        "baseline_walk_bike_mode_share_pct": DEFAULTS["BASELINE_MODE_SHARE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_intersection_payload(school_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "school_id": school_id,
        "cross_streets": DEFAULTS["CROSS_STREETS"],
        "control_type": "UNCONTROLLED",
        "speed_limit_mph": 30,
        "lanes_crossed": 2,
        "posted_school_zone": True,
    }
    payload.update(overrides)
    return payload


def create_crash_record_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "crash_date": "2025-05-14",
        "severity": "SEVERE_INJURY",
        "involved_pedestrian": True,
        "involved_school_age": True,
    }
    payload.update(overrides)
    return payload


def create_mode_share_survey_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "term_code": "2026FA",
        "survey_date": "2026-10-14",
        "classrooms_reporting": 18,
        "enrollment_at_survey": 640,
        "walk_count": 120,
        "bike_count": 40,
        "bus_count": 130,
        "car_count": 180,
        "other_count": 30,
    }
    payload.update(overrides)
    return payload


def create_warrant_study_payload(intersection_id: str,
                                 expected_intersection_version: int,
                                 **overrides) -> Dict[str, Any]:
    payload = {
        "intersection_id": intersection_id,
        "count_window_start": "2026-09-08",
        "count_window_end": "2026-09-30",
        "expected_intersection_version": expected_intersection_version,
    }
    payload.update(overrides)
    return payload


def create_count_session_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "session_date": "2026-09-08",
        "period": "AM_ARRIVAL",
        "observed_minutes": 60,
        "child_count": 70,
        "adult_count": 10,
        "vehicle_count": 500,
        "adequate_gaps": 28,
    }
    payload.update(overrides)
    return payload


def reopen_counting_payload(**overrides) -> Dict[str, Any]:
    payload = {"reopen_reason": "Field crew miscounted the arrival period."}
    payload.update(overrides)
    return payload


def finalize_study_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def create_guard_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": DEFAULTS["GUARD_NAME"],
        "home_zone_code": DEFAULTS["ZONE_CODE"],
        "hire_date": DEFAULTS["HIRE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_training_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "training_date": "2026-08-05",
        "hours": 12.0,
        "curriculum_code": DEFAULTS["CURRICULUM_CODE"],
    }
    payload.update(overrides)
    return payload


def create_equipment_payload(item_type: str, **overrides) -> Dict[str, Any]:
    payload = {"item_type": item_type, "issued_on": "2026-08-06"}
    payload.update(overrides)
    return payload


def certify_guard_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "certified_on": "2026-08-07",
        "certification_expires_on": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def duty_status_payload(duty_action: str) -> Dict[str, Any]:
    return {"duty_action": duty_action}


def create_guard_post_payload(intersection_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "intersection_id": intersection_id,
        "post_label": DEFAULTS["POST_LABEL"],
        "zone_code": DEFAULTS["ZONE_CODE"],
        "required_shift": "AM",
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(guard_id: str, expected_guard_post_version: int,
                              **overrides) -> Dict[str, Any]:
    payload = {
        "guard_id": guard_id,
        "start_date": "2026-09-08",
        "end_date": "2026-09-18",
        "expected_guard_post_version": expected_guard_post_version,
    }
    payload.update(overrides)
    return payload


def create_absence_report_payload(post_assignment_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "post_assignment_id": post_assignment_id,
        "absence_date": "2026-09-16",
        "reason": "ILLNESS",
    }
    payload.update(overrides)
    return payload


def offer_response_payload(response: str) -> Dict[str, Any]:
    return {"response": response}


def rescind_absence_payload(**overrides) -> Dict[str, Any]:
    payload = {"rescind_reason": "Guard recovered and will work the shift."}
    payload.update(overrides)
    return payload


def route_segment(segment_order: int, hazard_type: str, length_ft: int,
                  mitigated: bool = False,
                  intersection_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "segment_order": segment_order,
        "hazard_type": hazard_type,
        "length_ft": length_ft,
        "mitigated": mitigated,
        "intersection_id": intersection_id,
    }


def create_walking_route_payload(school_id: str,
                                 segments: Optional[List[Dict[str, Any]]] = None,
                                 **overrides) -> Dict[str, Any]:
    payload = {
        "school_id": school_id,
        "route_code": "RT-NORTH",
        "route_name": "North corridor to Maple Grove",
        "segments": segments if segments is not None else [
            route_segment(1, "NO_SIDEWALK", 133),
        ],
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "complaint_type": "SPEEDING",
        "reporter_name": "Dana Whitfield",
        "occurred_at": "2026-09-02T15:10:00Z",
        "narrative": "Cars routinely run the crossing during dismissal.",
        "severity_claim": "HIGH",
    }
    payload.update(overrides)
    return payload


def triage_complaint_payload(disposition: str = "REFER_TO_ENGINEERING",
                             **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": disposition}
    payload.update(overrides)
    return payload


def create_grant_program_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "program_name": DEFAULTS["PROGRAM_NAME"],
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "total_cents": 4_000_000,
        "application_deadline": "2026-09-15",
    }
    payload.update(overrides)
    return payload


def create_project_payload(grant_program_id: str, intersection_id: str,
                           **overrides) -> Dict[str, Any]:
    payload = {
        "grant_program_id": grant_program_id,
        "intersection_id": intersection_id,
        "project_type": "RRFB",
        "scope_summary": "Install a rectangular rapid flashing beacon.",
        "requested_cost_cents": 4_000_000,
        "students_benefited": 320,
    }
    payload.update(overrides)
    return payload


def fund_project_payload(expected_grant_program_version: int,
                         **overrides) -> Dict[str, Any]:
    payload = {"expected_grant_program_version": expected_grant_program_version}
    payload.update(overrides)
    return payload


def withdraw_funding_payload(expected_grant_program_version: int,
                             **overrides) -> Dict[str, Any]:
    payload = {
        "withdrawal_reason": "Bid came in over the award ceiling.",
        "expected_grant_program_version": expected_grant_program_version,
    }
    payload.update(overrides)
    return payload
