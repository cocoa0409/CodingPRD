"""Payload factories — one per entity, input fields only (PRD §3).

Optional inputs (retention_years, action_fraction, is_primary, the plan's
methodological rules, legal_hold) are omitted entirely when None so the
server-side default applies.
"""
from .constants import PLAN_END_DATE, PLAN_START_DATE

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_site_payload(**overrides) -> dict:
    n = _next()
    payload = {"name": f"Site {n}", "industry_code": "332812"}
    payload.update(overrides)
    return payload


def create_employee_payload(site_id: str, **overrides) -> dict:
    n = _next()
    payload = {
        "site_id": site_id,
        "full_name": f"Employee {n}",
        "external_ref": f"E{n}",
        "job_title": "Painter",
    }
    payload.update(overrides)
    return payload


def create_limit_payload(**overrides) -> dict:
    payload = {
        "analyte_code": "PB",
        "basis": "OSHA_PEL",
        "limit_type": "TWA8",
        "limit_mg_m3": 0.05,
    }
    payload.update(overrides)
    return payload


def create_pump_payload(site_id: str, **overrides) -> dict:
    n = _next()
    payload = {"site_id": site_id, "serial_number": f"P-{n:03d}"}
    payload.update(overrides)
    return payload


def create_seg_payload(site_id: str, exposure_limit_id: str, **overrides) -> dict:
    n = _next()
    payload = {
        "site_id": site_id,
        "name": f"SEG {n}",
        "analyte_code": "PB",
        "exposure_limit_id": exposure_limit_id,
        "task_description": "spray line",
    }
    payload.update(overrides)
    return payload


def create_membership_payload(seg_id: str, employee_id: str, **overrides) -> dict:
    payload = {"seg_id": seg_id, "employee_id": employee_id}
    payload.update(overrides)
    return payload


def create_plan_payload(seg_id: str, **overrides) -> dict:
    payload = {
        "seg_id": seg_id,
        "purpose": "INITIAL",
        "planned_start_date": PLAN_START_DATE,
        "planned_end_date": PLAN_END_DATE,
    }
    payload.update(overrides)
    return payload


def revise_plan_payload(expected_plan_version: int, **overrides) -> dict:
    payload = {"expected_plan_version": expected_plan_version}
    payload.update(overrides)
    return payload


def create_calibration_payload(pump_id: str, **overrides) -> dict:
    payload = {"pump_id": pump_id, "pre_flow_lpm": 2.0}
    payload.update(overrides)
    return payload


def record_post_payload(post_flow_lpm: float = 2.0) -> dict:
    return {"post_flow_lpm": post_flow_lpm}


def create_sample_payload(
    sampling_plan_id: str,
    sample_type: str = "PERSONAL",
    collection_date: str = PLAN_START_DATE,
    start_minute: int = 480,
    duration_minutes: int = 240,
    employee_id=None,
    pump_id=None,
    pre_calibration_id=None,
    **overrides,
) -> dict:
    payload = {
        "sampling_plan_id": sampling_plan_id,
        "sample_type": sample_type,
        "collection_date": collection_date,
        "start_minute": start_minute,
        "duration_minutes": duration_minutes,
    }
    if employee_id is not None:
        payload["employee_id"] = employee_id
    if pump_id is not None:
        payload["pump_id"] = pump_id
    if pre_calibration_id is not None:
        payload["pre_calibration_id"] = pre_calibration_id
    payload.update(overrides)
    return payload


def create_batch_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "analyte_code": "PB",
        "lod_ug": 5,
        "loq_ug": 10,
        "window_start_date": "2026-08-10",
        "window_end_date": "2026-08-14",
        "max_capacity": 10,
    }
    payload.update(overrides)
    return payload


def create_lab_result_payload(
    field_sample_id: str, lab_batch_id: str, mass_ug, **overrides
) -> dict:
    payload = {
        "field_sample_id": field_sample_id,
        "lab_batch_id": lab_batch_id,
        "mass_ug": mass_ug,
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(sampling_plan_id: str, expected_seg_version: int) -> dict:
    return {
        "sampling_plan_id": sampling_plan_id,
        "expected_seg_version": expected_seg_version,
    }


def create_control_payload(exposure_assessment_id: str, **overrides) -> dict:
    payload = {
        "exposure_assessment_id": exposure_assessment_id,
        "control_type": "ENGINEERING",
        "description": "Install downdraft booth",
        "priority": "HIGH",
    }
    payload.update(overrides)
    return payload


def create_clearance_payload(employee_id: str) -> dict:
    return {"employee_id": employee_id}


def decide_clearance_payload(decision: str) -> dict:
    return {"decision": decision}


def create_fit_test_payload(
    employee_id: str, medical_clearance_id: str, **overrides
) -> dict:
    payload = {
        "employee_id": employee_id,
        "medical_clearance_id": medical_clearance_id,
        "respirator_model": "3M-6800",
        "test_date": "2026-08-03",
    }
    payload.update(overrides)
    return payload


def record_fit_result_payload(result: str) -> dict:
    return {"result": result}
